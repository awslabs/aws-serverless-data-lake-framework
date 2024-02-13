import datetime
import logging
import uuid
from decimal import Decimal

from boto3.dynamodb.types import TypeSerializer

from ..commons import deserialize_dynamodb_item, serialize_dynamodb_item
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

    def __init__(self, client):
        self.logger = logging.getLogger(__name__)
        self.client = client
        self.dynamodb = client.dynamodb
        self.pipelines_table = client.config.get_pipelines_table()
        self.peh_table = client.config.get_peh_table()
        self.peh_ttl = client.config.get_peh_ttl()

    def start_pipeline_execution(self, pipeline_name, dataset_name=None, dataset_date=None, comment=None):
        self.logger.debug("peh start_pipeline_execution() called")

        throw_none_or_empty(pipeline_name, "Pipeline name is not specified")

        if dataset_date:
            validate_date(dataset_date)

        if not self.check_pipeline(pipeline_name):
            self.logger.error(f"Pipeline doesn't exist or inactive : {pipeline_name}")
            return None

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

        self.client.set_pipeline_execution(peh_id, pipeline_name)

        return peh_id

    def update_pipeline_execution(self, status, component=None, issue_comment=None):
        self.logger.debug("peh create_execution() called")

        throw_if_false(self.client.is_pipeline_set(), "Pipeline execution is not yet assigned")
        peh_id = self.client.pipeline_execution_id

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
        local_date_iso = get_local_date()

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

        # self.logger.debug(f"Update: {update_expr} \nNames: {expr_names} \nValues{expr_values}")

        serializer = TypeSerializer()
        self.dynamodb.update_item(
            TableName=self.peh_table,
            Key={"id": {"S": peh_id}},
            UpdateExpression=update_expr,
            ExpressionAttributeNames=expr_names,
            ExpressionAttributeValues=serialize_dynamodb_item(expr_values, serializer),
            ReturnValues="UPDATED_NEW",
        )

        # Add pipeline update for COMPLETED Executions
        if status == PEH_STATUS_COMPLETED:
            self.logger.debug(f"Pipeline: {self.client.pipeline_name}")
            item = deserialize_dynamodb_item(
                self.dynamodb.get_item(
                    TableName=self.pipelines_table,
                    Key={"name": {"S": self.client.pipeline_name}},
                    ConsistentRead=True,
                    ProjectionExpression="#n, version",
                    ExpressionAttributeNames={"#n": "name"},
                )["Item"]
            )
            pipeline_version = item["version"]

            expr_names = {
                "#V": "version",
                "#U": "last_updated_timestamp",
                "#P": "last_execution_id",
                "#D": "last_execution_date",
                "#E": "last_execution_timestamp",
                "#S": "last_execution_status",
                "#X": "last_execution_duration_in_seconds",
            }

            expr_values = {
                ":V": pipeline_version,
                ":INC": 1,
                ":S": status,
                ":P": self.client.pipeline_execution_id,
                ":D": local_date_iso,
                ":E": utc_time_iso,
                ":U": utc_time_iso,
                ":X": Decimal(str(duration_sec)),
            }
            update_expr = "SET #P = :P, #V = :V + :INC, #S = :S, #D = :D, #X = :X, #E = :E, #U = :U"

            serializer = TypeSerializer()
            self.dynamodb.update_item(
                TableName=self.pipelines_table,
                Key={"name": {"S": self.client.pipeline_name}},
                UpdateExpression=update_expr,
                ExpressionAttributeNames=expr_names,
                ExpressionAttributeValues=serialize_dynamodb_item(expr_values, serializer),
                ReturnValues="UPDATED_NEW",
            )

        return True

    def get_peh_record(self, peh_id):
        # self.logger.debug(f"check_peh_active(): {peh_id}")
        result = self.dynamodb.get_item(TableName=self.peh_table, Key={"id": {"S": peh_id}}, ConsistentRead=True)
        # self.logger.debug(f"check_peh_active(): {result}")

        if "Item" in result:
            return deserialize_dynamodb_item(result["Item"])
        else:
            return None

    # Check if pipeline exists and active
    def check_pipeline(self, pipeline_name: str) -> bool:
        self.logger.debug(f"check_pipeline: {pipeline_name}")
        if pipeline_name not in self.pipelines.keys():  # Pipeline not found in cache
            # Go to DDB and add new pipeline to cache
            self.logger.debug(f"check_pipeline - get from DDB: {pipeline_name}")
            result = self.dynamodb.get_item(
                TableName=self.pipelines_table,
                Key={"name": {"S": pipeline_name}},
                ConsistentRead=True,
                ProjectionExpression="#n, #s",
                ExpressionAttributeNames={"#n": "name", "#s": "status"},
            )
            self.logger.debug("result:" + str(result))
            if "Item" in result:  # Pipeline found, check status
                status = deserialize_dynamodb_item(result["Item"])["status"]
                self.pipelines[pipeline_name] = status == PIPELINE_STATUS_ACTIVE
            else:  # Pipeline not found
                self.pipelines[pipeline_name] = False

        self.logger.debug(f"Pipeline cache: {self.pipelines}")
        return self.pipelines[pipeline_name]

    def retrieve_pipeline_execution(self, peh_id: str):
        throw_none_or_empty(peh_id, "Pipeline is not specified")

        item = self.get_peh_record(peh_id)
        if item is None:
            raise ValueError("Pipeline execution is not found")

        if not item["active"]:
            raise ValueError("Pipeline execution is inactive")

        self.client.set_pipeline_execution(peh_id, item["pipeline"])
