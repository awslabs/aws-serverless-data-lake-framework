import datetime as dt
import os
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import ClientError

from ..commons import init_logger


class DynamoInterface:
    def __init__(self, configuration, log_level=None, dynamodb_resource=None):
        self.log_level = log_level or os.getenv("LOG_LEVEL", "INFO")
        self._logger = init_logger(__name__, self.log_level)
        self.dynamodb_resource = dynamodb_resource or boto3.resource("dynamodb")

        self._config = configuration

        self.object_metadata_table = None
        self.transform_mapping_table = None
        self.manifests_control_table = None

        self._get_object_metadata_table()
        self._get_transform_mapping_table()
        self._get_manifests_control_table()

    def _get_object_metadata_table(self):
        if not self.object_metadata_table:
            self.object_metadata_table = self.dynamodb_resource.Table(self._config.object_metadata_table)
        return self.object_metadata_table

    def _get_transform_mapping_table(self):
        if not self.transform_mapping_table:
            self.transform_mapping_table = self.dynamodb_resource.Table(self._config.transform_mapping_table)
        return self.transform_mapping_table

    def _get_manifests_control_table(self):
        if not self.manifests_control_table:
            self.manifests_control_table = self.dynamodb_resource.Table(self._config.manifests_control_table)
        return self.manifests_control_table

    @staticmethod
    def build_id(bucket, key):
        return "s3://{}/{}".format(bucket, key)

    @staticmethod
    def manifest_keys(dataset_name, manifest_file_name, data_file_name):
        ds_name = dataset_name + "-" + manifest_file_name
        df_name = manifest_file_name + "-" + data_file_name
        return {"dataset_name": ds_name, "datafile_name": df_name}

    def get_item(self, table, key):
        try:
            item = table.get_item(Key=key, ConsistentRead=True)["Item"]
        except ClientError:
            msg = "Error getting item from {} table".format(table)
            self._logger.exception(msg)
            raise
        return item

    def put_item(self, table, item):
        try:
            table.put_item(Item=item)
        except ClientError:
            msg = "Error putting item {} into {} table".format(item, table)
            self._logger.exception(msg)
            raise

    def get_transform_table_item(self, dataset):
        return self.get_item(self.transform_mapping_table, {"name": dataset})

    def update_object_metadata_catalog(self, item):
        item["id"] = self.build_id(item["bucket"], item["key"])
        item["timestamp"] = int(round(dt.datetime.utcnow().timestamp() * 1000, 0))
        return self.put_item_in_object_metadata_table(item)

    def put_item_in_object_metadata_table(self, item):
        return self.put_item(self.object_metadata_table, item)

    def update_object(self, bucket, key, attribute_updates):
        try:
            self.object_metadata_table.update_item(
                Key={"id": self.build_id(bucket, key)}, AttributeUpdates=attribute_updates
            )
        except ClientError:
            msg = "Error updating object object s3://{}/{}".format(bucket, key)
            self._logger.exception(msg)
            raise

    def remove_object_attribute(self, bucket, key, attribute):
        try:
            self.object_metadata_table.update_item(
                Key={"id": self.build_id(bucket, key)}, UpdateExpression="REMOVE {}".format(attribute)
            )
        except ClientError:
            msg = "Error removing attribute {} for object s3://{}/{}".format(attribute, bucket, key)
            self._logger.exception(msg)
            raise

    def query_object_metadata_index(self, index, key_expression, key_value, filter_expression, filter_value, max_items):
        try:
            items = []
            response = self.object_metadata_table.query(
                IndexName=index,
                KeyConditionExpression=Key(key_expression).eq(key_value),
                FilterExpression=Attr(filter_expression).eq(filter_value),
            )
            if response["Items"]:
                items.extend(response["Items"])
            while "LastEvaluatedKey" in response:
                response = self.object_metadata_table.query(
                    IndexName=index,
                    KeyConditionExpression=Key(key_expression).eq(key_value),
                    FilterExpression=Attr(filter_expression).eq(filter_value),
                    ExclusiveStartKey=response["LastEvaluatedKey"],
                )
                if response["Items"]:
                    items.extend(response["Items"])
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

    def update_manifests_control_table(self, key, update_expr, expr_values, expr_names):
        return self.manifests_control_table.update_item(
            Key=key,
            UpdateExpression=update_expr,
            ExpressionAttributeValues=expr_values,
            ExpressionAttributeNames=expr_names,
            ReturnValues="UPDATED_NEW",
        )

    def update_manifests_control_table_stagea(self, ddb_key, status, s3_key=None):
        if status == "STARTED":
            starttime_time = dt.datetime.utcnow()
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

            return self.update_manifests_control_table(ddb_key, update_expr, expr_values, expr_names)

        elif status == "PROCESSING":
            expr_names = {
                "#S": "stage_a_status",
            }

            expr_values = {":S": status}

            update_expr = "SET #S = :S"

            return self.update_manifests_control_table(ddb_key, update_expr, expr_values, expr_names)

        elif status == "COMPLETED":
            endtime_time = dt.datetime.utcnow()
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

            return self.update_manifests_control_table(ddb_key, update_expr, expr_values, expr_names)

        elif status == "FAILED":
            endtime_time = dt.datetime.utcnow()
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

            return self.update_manifests_control_table(ddb_key, update_expr, expr_values, expr_names)

    def update_manifests_control_table_stageb(self, ddb_key, status, s3_key=None, comment=None):
        if status == "STARTED":
            starttime_time = dt.datetime.utcnow()
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

            return self.update_manifests_control_table(ddb_key, update_expr, expr_values, expr_names)

        elif status == "COMPLETED":
            endtime_time = dt.datetime.utcnow()
            endtime = str(endtime_time)
            endtimestamp = int(endtime_time.timestamp())
            expr_names = {
                "#S": "stage_b_status",
                "#ET": "stage_b_endtime",
                "#ETS": "stage_b_endtimestamp",
            }

            expr_values = {":S": status, ":ET": endtime, ":ETS": str(endtimestamp)}

            update_expr = "SET #S = :S, #ET = :ET , #ETS = :ETS"

            return self.update_manifests_control_table(ddb_key, update_expr, expr_values, expr_names)

        elif status == "FAILED":
            endtime_time = dt.datetime.utcnow()
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

            return self.update_manifests_control_table(ddb_key, update_expr, expr_values, expr_names)

        elif status == "PROCESSING":
            expr_names = {
                "#S": "stage_b_status",
            }

            expr_values = {
                ":S": status,
            }

            update_expr = "SET #S = :S"

            return self.update_manifests_control_table(ddb_key, update_expr, expr_values, expr_names)
