import datetime
import logging
import os
import uuid
from decimal import Decimal

import boto3
from boto3.dynamodb.types import TypeSerializer

from ..commons import deserialize_dynamodb_item, serialize_dynamodb_item
from .config import DynamoConfiguration
from .utils import (
    get_duration_sec,
    get_local_date,
    get_timestamp_iso,
    get_ttl,
    is_not_empty,
    throw_if_false,
    throw_none_or_empty,
    validate_date,
)

PIPELINE_STATUS_ACTIVE = "ACTIVE"

PEH_STATUS_STARTED = "STARTED"
PEH_STATUS_COMPLETED = "COMPLETED"
PEH_STATUS_FAILED = "FAILED"
PEH_STATUS_CANCELED = "CANCELED"


class PipelineExecutionHistoryAPI:
    pipelines = dict()  # Pipelines cache across all instances

    def __init__(
        self,
        run_in_context,
        region: str = "us-east-1",
        profile: str = "default",
        # instance: str = "dev",
        peh_table_instance=None,
        manifests_table_instance=None,
        sns_topic: str = None,
    ):
        self.dynamodb = boto3.client("dynamodb")
        dynamo_config = DynamoConfiguration(
            peh_table_instance=peh_table_instance,
            manifests_table_instance=manifests_table_instance,
        )
        self.peh_table = dynamo_config.peh_table
        self.peh_ttl = 120  # TODO property of dynamo_config?

        self._logger = logging.getLogger(__name__)

        self.region = region
        self.profile = profile
        self.run_in_fargate = run_in_context == "FARGATE"
        self.run_in_lambda = run_in_context == "LAMBDA"
        self.sns_topic = sns_topic

        # No current pipeline execution
        self.pipeline_name = None
        self.pipeline_execution_id = None

        if self.run_in_fargate:
            if "AWS_ACCESS_KEY" in os.environ and "AWS_SECRET_ACCESS_KEY" in os.environ:
                aws_access_key = os.getenv("AWS_ACCESS_KEY")
                aws_secret_access_key = os.getenv("AWS_SECRET_ACCESS_KEY")
                boto3.setup_default_session(
                    profile_name=self.profile,
                    region_name=self.region,
                    aws_access_key_id=aws_access_key,
                    aws_secret_access_key=aws_secret_access_key,
                )
            else:
                msg = "Environment variables AWS_ACCESS_KEY and AWS_SECRET_ACCESS_KEY are not set"
                self._logger.error(msg)
                raise ValueError(msg)
        elif self.run_in_lambda:
            pass
        else:
            boto3.setup_default_session(profile_name=self.profile, region_name=self.region)

        sts_endpoint_url = "https://sts." + os.getenv("AWS_REGION") + ".amazonaws.com"
        self.account_id = boto3.client("sts", endpoint_url=sts_endpoint_url).get_caller_identity().get("Account")

    def start_pipeline_execution(
        self, pipeline_name: str, dataset_name: str = None, dataset_date: str = None, comment: str = None
    ) -> str:
        """Creates a record for Pipeline Execution History

        Arguments:
            pipeline_name {str} -- Name of pipeline

        Keyword Arguments:
            dataset_date {str} -- Optional. ISO 8601 date of dataset
            comment {str} -- Optional. Comment

        Returns:
            str -- Unique reference to a Pipeline Execution History record (uuid4)
        """

        self._logger.debug("peh start_pipeline_execution() called")

        throw_none_or_empty(pipeline_name, "Pipeline name is not specified")

        if dataset_date:
            validate_date(dataset_date)

        peh_id = str(uuid.uuid4())
        current_time = datetime.datetime.now(datetime.UTC)
        utc_time_iso = get_timestamp_iso(current_time)
        local_date_iso = get_local_date()

        item = {}
        # Add extra fields
        item["id"] = peh_id
        item["version"] = 1
        item["pipeline"] = pipeline_name
        item["active"] = True
        item["execution_date"] = local_date_iso

        if dataset_name:
            item["dataset"] = dataset_name
        else:
            item["dataset"] = ""

        if not dataset_date:
            item["dataset_date"] = local_date_iso
        else:
            item["dataset_date"] = dataset_date

        item["status"] = PEH_STATUS_STARTED

        if comment:
            item["comment"] = comment
        else:
            item["comment"] = f"Pipeline: {pipeline_name} has started execution"

        item["start_timestamp"] = utc_time_iso
        item["last_updated_timestamp"] = utc_time_iso
        item["status_last_updated_timestamp"] = PEH_STATUS_STARTED + "#" + utc_time_iso
        item["history"] = [{"status": PEH_STATUS_STARTED, "timestamp": utc_time_iso}]

        if self.peh_ttl > 0:
            item["ttl"] = get_ttl(self.peh_ttl)
        serializer = TypeSerializer()
        self.dynamodb.put_item(TableName=self.peh_table, Item=serialize_dynamodb_item(item, serializer))

        self.set_pipeline_execution(peh_id, pipeline_name)

        return peh_id

    def update_pipeline_execution(self, status: str, component: str = None, issue_comment: str = None):
        """Update status of Pipeline Execution History record

        Arguments:
            status {str} -- New status of Pipeline Execution
            component {str} -- Optional. Component of Pipeline Execution

        Returns:
            bool -- True if successful
        """
        self._logger.debug("peh create_execution() called")

        throw_if_false(self.is_pipeline_set(), "Pipeline execution is not yet assigned")
        peh_id = self.pipeline_execution_id

        peh_rec = self.get_peh_record(peh_id)
        if peh_rec:
            is_active = peh_rec["active"]
        else:
            is_active = False
        throw_if_false(is_active, "Pipeline execution is not active")

        version = peh_rec["version"]
        start_time = peh_rec["start_timestamp"]

        current_time = datetime.datetime.now(datetime.UTC)
        utc_time_iso = get_timestamp_iso(current_time)
        # local_date_iso = get_local_date()

        if status in [PEH_STATUS_COMPLETED, PEH_STATUS_CANCELED, PEH_STATUS_FAILED]:
            duration_sec = get_duration_sec(start_time, utc_time_iso)

            if status == PEH_STATUS_COMPLETED:
                is_success = True
            else:
                is_success = False

            expr_names = {
                "#H": "history",
                "#St": "status",
                "#LUT": "last_updated_timestamp",
                "#STT": "status_last_updated_timestamp",
                "#A": "active",
                "#V": "version",
                "#ETS": "end_timestamp",
                "#S": "success",
                "#D": "duration_in_seconds",
            }

            if component:
                history_list = [{"status": status, "timestamp": utc_time_iso, "component": component}]
            else:
                history_list = [{"status": status, "timestamp": utc_time_iso}]

            expr_values = {
                ":H": history_list,
                ":St": status,
                ":LUT": utc_time_iso,
                ":STT": status + "#" + utc_time_iso,
                ":INC": 1,
                ":ETS": utc_time_iso,
                ":A": False,
                ":S": is_success,
                ":V": version,
                ":D": Decimal(str(duration_sec)),
            }

            update_expr = (
                "SET #H = list_append(#H, :H), #S = :S, #V = :V + :INC,"
                "#LUT = :LUT, #A = :A, #St = :St, #ETS = :ETS, #D = :D,"
                "#STT = :STT"
            )

            if is_not_empty(issue_comment):
                expr_names["#C"] = "issue_comment"
                expr_values[":C"] = issue_comment
                update_expr += ", #C = :C"

        else:
            expr_names = {
                "#H": "history",
                "#St": "status",
                "#V": "version",
                "#LUT": "last_updated_timestamp",
                "#STT": "status_last_updated_timestamp",
            }

            if component:
                history_list = [{"status": status, "timestamp": utc_time_iso, "component": component}]
            else:
                history_list = [{"status": status, "timestamp": utc_time_iso}]

            expr_values = {
                ":H": history_list,
                ":St": status,
                ":STT": status + "#" + utc_time_iso,
                ":LUT": utc_time_iso,
                ":INC": 1,
                ":V": version,
            }
            update_expr = "SET #H = list_append(#H, :H), #St = :St, #STT = :STT, #V = :V + :INC, #LUT = :LUT"

            if is_not_empty(issue_comment):
                expr_names["#C"] = "comment"
                expr_values[":C"] = issue_comment
                update_expr += ", #C = :C"

        # self._logger.debug(f"Update: {update_expr} \nNames: {expr_names} \nValues{expr_values}")

        serializer = TypeSerializer()
        self.dynamodb.update_item(
            TableName=self.peh_table,
            Key={"id": {"S": peh_id}},
            UpdateExpression=update_expr,
            ExpressionAttributeNames=expr_names,
            ExpressionAttributeValues=serialize_dynamodb_item(expr_values, serializer),
            ReturnValues="UPDATED_NEW",
        )

        return True

    def get_peh_record(self, peh_id):
        # self._logger.debug(f"check_peh_active(): {peh_id}")
        result = self.dynamodb.get_item(TableName=self.peh_table, Key={"id": {"S": peh_id}}, ConsistentRead=True)
        # self._logger.debug(f"check_peh_active(): {result}")

        if "Item" in result:
            return deserialize_dynamodb_item(result["Item"])
        else:
            return None

    def retrieve_pipeline_execution(self, peh_id: str):
        """Retrieve pipeline execution information and set as current execution in the Client

        Arguments:
            peh_id {str} -- Unique Pipeline execution ID

        Returns:
            None
        """
        throw_none_or_empty(peh_id, "Pipeline is not specified")

        item = self.get_peh_record(peh_id)
        if item is None:
            raise ValueError("Pipeline execution is not found")

        if not item["active"]:
            raise ValueError("Pipeline execution is inactive")

        self.set_pipeline_execution(peh_id, item["pipeline"])

    def end_pipeline_execution_failed(self, component: str = None, issue_comment: str = None) -> bool:
        """Closes Pipeline Execution History record with FAILED status

        Arguments:
            component {str} -- Optional. Component of Pipeline Execution
            issue_comment {str} -- Optional. Comment

        Returns:
            bool -- True if successful
        """
        return self.update_pipeline_execution(PEH_STATUS_FAILED, component=component, issue_comment=issue_comment)

    def end_pipeline_execution_success(self, component: str = None) -> bool:
        """Closes Pipeline Execution History record with COMPLETED status

        Arguments:
            component {str} -- Optional. Component of Pipeline Execution

        Returns:
            bool -- True if successful
        """
        return self.update_pipeline_execution(PEH_STATUS_COMPLETED, component=component)

    def end_pipeline_execution_cancel(self, component: str = None, issue_comment: str = None) -> bool:
        """Closes Pipeline execution with CANCELED status

        Arguments:
            component {str} -- Optional. Component of Pipeline Execution
            issue_comment {str} -- Optional. Comment

        Returns:
            bool -- True if successful
        """
        return self.update_pipeline_execution(PEH_STATUS_CANCELED, component=component, issue_comment=issue_comment)

    def is_pipeline_set(self) -> bool:
        """Check if current pipeline execution is set

        Returns:
            bool -- True if pipeline execution is set
        """
        return self.pipeline_execution_id is not None and self.pipeline_name is not None

    def reset_pipeline_execution(self):
        """Clears the current pipeline execution"""
        self.pipeline_execution_id = None
        self.pipeline_name = None

    def set_pipeline_execution(self, pipeline_execution_id: str, pipeline_name: str):
        """Sets the current pipeline execution

        Arguments:
            pipeline_execution_id {str} -- Unique identifier of pipeline execution
            pipeline_name {str} -- Pipeline name
        """
        self.pipeline_execution_id = pipeline_execution_id
        self.pipeline_name = pipeline_name
