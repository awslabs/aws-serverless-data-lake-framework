import datetime as dt
import logging
import os
from types import TracebackType
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Type

import boto3
from boto3.dynamodb.conditions import Attr, Key
from boto3.dynamodb.types import TypeSerializer
from botocore.client import Config
from botocore.exceptions import ClientError

from ..commons import deserialize_dynamodb_item, init_logger, serialize_dynamodb_item

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.client import DynamoDBClient
    from mypy_boto3_dynamodb.type_defs import (
        AttributeValueTypeDef,
        WriteRequestTypeDef,
    )

logger = logging.getLogger(__name__)


class DynamoInterface:
    def __init__(self, configuration, log_level=None, dynamodb_client=None):
        self.log_level = log_level or os.getenv("LOG_LEVEL", "INFO")
        self._logger = init_logger(__name__, self.log_level)
        session_config = Config(user_agent="awssdlf/2.9.0")
        self.dynamodb_client = dynamodb_client or boto3.client("dynamodb", config=session_config)

        self._config = configuration

        self.object_metadata_table = None
        self.manifests_control_table = None

        self._get_object_metadata_table()
        self._get_manifests_control_table()

    def _get_object_metadata_table(self):
        if not self.object_metadata_table:
            self.object_metadata_table = self._config.object_metadata_table
        return self.object_metadata_table

    def _get_manifests_control_table(self):
        if not self.manifests_control_table:
            self.manifests_control_table = self._config.manifests_control_table
        return self.manifests_control_table

    @staticmethod
    def build_id(bucket, key):
        return f"s3://{bucket}/{key}"

    @staticmethod
    def manifest_keys(dataset_name, manifest_file_name, data_file_name):
        ds_name = dataset_name + "-" + manifest_file_name
        df_name = manifest_file_name + "-" + data_file_name
        return {"dataset_name": ds_name, "datafile_name": df_name}

    def get_item(self, table, key):
        try:
            serializer = TypeSerializer()
            item = deserialize_dynamodb_item(
                self.dynamodb_client.get_item(
                    TableName=table, Key=serialize_dynamodb_item(key, serializer), ConsistentRead=True
                )["Item"]
            )
        except ClientError:
            msg = "Error getting item from {} table".format(table)
            self._logger.exception(msg)
            raise
        return item

    def put_item(self, table, item):
        try:
            serializer = TypeSerializer()
            self.dynamodb_client.put_item(TableName=table, Item=serialize_dynamodb_item(item, serializer))
        except ClientError:
            msg = "Error putting item {} into {} table".format(item, table)
            self._logger.exception(msg)
            raise

    def update_object_metadata_catalog(self, item):
        item["id"] = self.build_id(item["bucket"], item["key"])
        item["timestamp"] = int(round(dt.datetime.now(dt.UTC).timestamp() * 1000, 0))
        return self.put_item_in_object_metadata_table(item)

    def put_item_in_object_metadata_table(self, item):
        return self.put_item(self.object_metadata_table, item)

    def batch_update_object_metadata_catalog(self, items):
        for item in items:
            item["id"] = self.build_id(item["bucket"], item["key"])
            item["timestamp"] = int(round(dt.datetime.now(dt.UTC).timestamp() * 1000, 0))

        return self.batch_put_item_in_object_metadata_table(items)

    def batch_put_item_in_object_metadata_table(self, items):
        serializer = TypeSerializer()
        with _TableBatchWriter(self.object_metadata_table, self.dynamodb_client) as writer:
            for item in items:
                writer.put_item(serialize_dynamodb_item(item, serializer))

    def update_object(self, bucket, key, update_expr, expr_names, expr_values):
        try:
            serializer = TypeSerializer()
            self.dynamodb_client.update_item(
                TableName=self.object_metadata_table,
                Key={"id": {"S": self.build_id(bucket, key)}},
                UpdateExpression=update_expr,
                ExpressionAttributeNames=expr_names,
                ExpressionAttributeValues=serialize_dynamodb_item(expr_values, serializer),
                ReturnValues="UPDATED_NEW",
            )
        except ClientError:
            msg = "Error updating object object s3://{}/{}".format(bucket, key)
            self._logger.exception(msg)
            raise

    def remove_object_attribute(self, bucket, key, attribute):
        try:
            self.dynamodb_client.update_item(
                TableName=self.object_metadata_table,
                Key={"id": {"S": self.build_id(bucket, key)}},
                UpdateExpression="REMOVE {}".format(attribute),
            )
        except ClientError:
            msg = "Error removing attribute {} for object s3://{}/{}".format(attribute, bucket, key)
            self._logger.exception(msg)
            raise

    def query_object_metadata_index(self, index, key_expression, key_value, filter_expression, filter_value, max_items):
        try:
            items = []
            response = self.dynamodb_client.query(
                TableName=self.object_metadata_table,
                IndexName=index,
                KeyConditionExpression=Key(key_expression).eq(key_value),
                FilterExpression=Attr(filter_expression).eq(filter_value),
            )
            if response["Items"]:
                items.extend([deserialize_dynamodb_item(item) for item in response["Items"]])
            while "LastEvaluatedKey" in response:
                response = self.dynamodb_client.query(
                    TableName=self.object_metadata_table,
                    IndexName=index,
                    KeyConditionExpression=Key(key_expression).eq(key_value),
                    FilterExpression=Attr(filter_expression).eq(filter_value),
                    ExclusiveStartKey=response["LastEvaluatedKey"],
                )
                if response["Items"]:
                    items.extend([deserialize_dynamodb_item(item) for item in response["Items"]])
                if len(items) > max_items:
                    items = items[:max_items]
                    break
        except ClientError:
            msg = "Error querying object metadata {} index".format(index)
            self._logger.exception(msg)
            raise
        return items

    def put_item_in_manifests_control_table(self, item):
        return self.put_item(self.manifests_control_table, item)

    def get_item_from_manifests_control_table(self, dataset_name, manifest_file_name, data_file_name):
        return self.get_item(
            self.manifests_control_table, self.manifest_keys(dataset_name, manifest_file_name, data_file_name)
        )

    def update_manifests_control_table(self, key, update_expr, expr_names, expr_values):
        serializer = TypeSerializer()
        return self.dynamodb_client.update_item(
            TableName=self.manifests_control_table,
            Key=key,
            UpdateExpression=update_expr,
            ExpressionAttributeNames=expr_names,
            ExpressionAttributeValues=serialize_dynamodb_item(expr_values, serializer),
            ReturnValues="UPDATED_NEW",
        )

    def update_manifests_control_table_stagea(self, ddb_key, status, s3_key=None):
        if status == "STARTED":
            starttime_time = dt.datetime.now(dt.UTC)
            starttime = str(starttime_time)
            starttimestamp = int(starttime_time.timestamp())
            expr_names = {
                "#S": "stage_a_status",
                "#ST": "stage_a_starttime",
                "#STS": "stage_a_starttimestamp",
            }

            expr_values = {
                ":S": status,
                ":ST": starttime,
                ":STS": str(starttimestamp),
            }

            update_expr = "SET #S = :S, #ST = :ST , #STS = :STS"

            return self.update_manifests_control_table(ddb_key, update_expr, expr_names, expr_values)

        elif status == "PROCESSING":
            expr_names = {
                "#S": "stage_a_status",
            }

            expr_values = {":S": status}

            update_expr = "SET #S = :S"

            return self.update_manifests_control_table(ddb_key, update_expr, expr_names, expr_values)

        elif status == "COMPLETED":
            endtime_time = dt.datetime.now(dt.UTC)
            endtime = str(endtime_time)
            endtimestamp = int(endtime_time.timestamp())
            s3_prefix = s3_key
            expr_names = {
                "#S": "stage_a_status",
                "#ET": "stage_a_endtime",
                "#ETS": "stage_a_endtimestamp",
                "#S3K": "s3_key",
            }

            expr_values = {":S": status, ":ET": endtime, ":ETS": str(endtimestamp), ":S3K": str(s3_prefix)}

            update_expr = "SET #S = :S, #ET = :ET , #ETS = :ETS, #S3K = :S3K"

            return self.update_manifests_control_table(ddb_key, update_expr, expr_names, expr_values)

        elif status == "FAILED":
            endtime_time = dt.datetime.now(dt.UTC)
            endtime = str(endtime_time)
            endtimestamp = int(endtime_time.timestamp())
            expr_names = {
                "#S": "stage_a_status",
                "#ET": "stage_a_endtime",
                "#ETS": "stage_a_endtimestamp",
            }

            expr_values = {
                ":S": status,
                ":ET": endtime,
                ":ETS": str(endtimestamp),
            }

            update_expr = "SET #S = :S, #ET = :ET , #ETS = :ETS"

            return self.update_manifests_control_table(ddb_key, update_expr, expr_names, expr_values)

    def update_manifests_control_table_stageb(self, ddb_key, status, s3_key=None, comment=None):
        if status == "STARTED":
            starttime_time = dt.datetime.now(dt.UTC)
            starttime = str(starttime_time)
            starttimestamp = int(starttime_time.timestamp())
            expr_names = {
                "#S": "stage_b_status",
                "#ST": "stage_b_starttime",
                "#STS": "stage_b_starttimestamp",
            }

            expr_values = {
                ":S": status,
                ":ST": starttime,
                ":STS": str(starttimestamp),
            }

            update_expr = "SET #S = :S, #ST = :ST , #STS = :STS"

            return self.update_manifests_control_table(ddb_key, update_expr, expr_names, expr_values)

        elif status == "COMPLETED":
            endtime_time = dt.datetime.now(dt.UTC)
            endtime = str(endtime_time)
            endtimestamp = int(endtime_time.timestamp())
            expr_names = {
                "#S": "stage_b_status",
                "#ET": "stage_b_endtime",
                "#ETS": "stage_b_endtimestamp",
            }

            expr_values = {":S": status, ":ET": endtime, ":ETS": str(endtimestamp)}

            update_expr = "SET #S = :S, #ET = :ET , #ETS = :ETS"

            return self.update_manifests_control_table(ddb_key, update_expr, expr_names, expr_values)

        elif status == "FAILED":
            endtime_time = dt.datetime.now(dt.UTC)
            endtime = str(endtime_time)
            endtimestamp = int(endtime_time.timestamp())
            expr_names = {
                "#S": "stage_b_status",
                "#ET": "stage_b_endtime",
                "#ETS": "stage_b_endtimestamp",
                "#C": "comment",
            }

            expr_values = {
                ":S": status,
                ":ET": endtime,
                ":ETS": str(endtimestamp),
                ":C": comment,
            }

            update_expr = "SET #S = :S, #ET = :ET , #ETS = :ETS, #C = :C"

            return self.update_manifests_control_table(ddb_key, update_expr, expr_names, expr_values)

        elif status == "PROCESSING":
            expr_names = {
                "#S": "stage_b_status",
            }

            expr_values = {
                ":S": status,
            }

            update_expr = "SET #S = :S"

            return self.update_manifests_control_table(ddb_key, update_expr, expr_names, expr_values)

    def clean_table(dynamodb, table_name, pk_name, sk_name=""):
        logger.debug(f"Clean dynamodb table {table_name}, PK: {pk_name}, SK: {sk_name}")
        table = dynamodb.Table(table_name)
        while True:
            result = table.scan()
            if result["Count"] == 0:
                logger.debug(f"Clean dynamodb table {table_name}... DONE")
                return

            with table.batch_writer() as batch:
                for item in result["Items"]:
                    if not sk_name:
                        batch.delete_item(Key={pk_name: item[pk_name]})
                    else:
                        batch.delete_item(Key={pk_name: item[pk_name], sk_name: item[sk_name]})


class _TableBatchWriter:
    """Automatically handle batch writes to DynamoDB for a single table."""

    def __init__(
        self,
        table_name: str,
        client: "DynamoDBClient",
        flush_amount: int = 25,
        overwrite_by_pkeys: Optional[List[str]] = None,
        log_level=None,
    ):
        self.log_level = log_level or os.getenv("LOG_LEVEL", "INFO")
        self._logger = init_logger(__name__, self.log_level)
        self._table_name = table_name
        self._client = client
        self._items_buffer: List["WriteRequestTypeDef"] = []
        self._flush_amount = flush_amount
        self._overwrite_by_pkeys = overwrite_by_pkeys

    def put_item(self, item: Dict[str, "AttributeValueTypeDef"]) -> None:
        """
        Add a new put item request to the batch.

        Parameters
        ----------
        item: Dict[str, AttributeValueTypeDef]
            The item to add.
        """
        self._add_request_and_process({"PutRequest": {"Item": item}})

    def delete_item(self, key: Dict[str, "AttributeValueTypeDef"]) -> None:
        """
        Add a new delete request to the batch.

        Parameters
        ----------
        key: Dict[str, AttributeValueTypeDef]
            The key of the item to delete.
        """
        self._add_request_and_process({"DeleteRequest": {"Key": key}})

    def _add_request_and_process(self, request: "WriteRequestTypeDef") -> None:
        if self._overwrite_by_pkeys:
            self._remove_dup_pkeys_request_if_any(request, self._overwrite_by_pkeys)
        self._items_buffer.append(request)
        self._flush_if_needed()

    def _remove_dup_pkeys_request_if_any(self, request: "WriteRequestTypeDef", overwrite_by_pkeys: List[str]) -> None:
        pkey_values_new = self._extract_pkey_values(request, overwrite_by_pkeys)
        for item in self._items_buffer:
            if self._extract_pkey_values(item, overwrite_by_pkeys) == pkey_values_new:
                self._items_buffer.remove(item)
                self._logger.debug(
                    "With overwrite_by_pkeys enabled, skipping request:%s",
                    item,
                )

    def _extract_pkey_values(
        self, request: "WriteRequestTypeDef", overwrite_by_pkeys: List[str]
    ) -> Optional[List[Any]]:
        if request.get("PutRequest"):
            return [request["PutRequest"]["Item"][key] for key in overwrite_by_pkeys]
        elif request.get("DeleteRequest"):
            return [request["DeleteRequest"]["Key"][key] for key in overwrite_by_pkeys]
        return None

    def _flush_if_needed(self) -> None:
        if len(self._items_buffer) >= self._flush_amount:
            self._flush()

    def _flush(self) -> None:
        items_to_send = self._items_buffer[: self._flush_amount]
        self._items_buffer = self._items_buffer[self._flush_amount :]
        response = self._client.batch_write_item(RequestItems={self._table_name: items_to_send})

        unprocessed_items = response["UnprocessedItems"]
        if not unprocessed_items:
            unprocessed_items = {}
        item_list = unprocessed_items.get(self._table_name, [])

        # Any unprocessed_items are immediately added to the
        # next batch we send.
        self._items_buffer.extend(item_list)
        self._logger.debug(
            "Batch write sent %s, unprocessed: %s",
            len(items_to_send),
            len(self._items_buffer),
        )

    def __enter__(self) -> "_TableBatchWriter":
        return self

    def __exit__(
        self,
        exception_type: Optional[Type[BaseException]],
        exception_value: Optional[BaseException],
        traceback: Optional[TracebackType],
    ) -> Optional[bool]:
        # When we exit, we need to keep flushing whatever's left
        # until there's nothing left in our items buffer.
        while self._items_buffer:
            self._flush()

        return None
