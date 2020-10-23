import os
import datetime as dt

import boto3
from boto3.dynamodb.conditions import Key, Attr
from botocore.exceptions import ClientError

from ..commons import init_logger


class DynamoInterface:
    def __init__(self, configuration, log_level=None, dynamodb_resource=None):
        self.log_level = log_level or os.getenv('LOG_LEVEL', 'INFO')
        self._logger = init_logger(__name__, self.log_level)
        self.dynamodb_resource = dynamodb_resource or boto3.resource(
            'dynamodb')

        self._config = configuration

        self.object_metadata_table = None
        self.transform_mapping_table = None

        self._get_object_metadata_table()
        self._get_transform_mapping_table()

    def _get_object_metadata_table(self):
        if not self.object_metadata_table:
            self.object_metadata_table = self.dynamodb_resource.Table(
                self._config.object_metadata_table)
        return self.object_metadata_table

    def _get_transform_mapping_table(self):
        if not self.transform_mapping_table:
            self.transform_mapping_table = self.dynamodb_resource.Table(
                self._config.transform_mapping_table)
        return self.transform_mapping_table

    @staticmethod
    def build_id(bucket, key):
        return 's3://{}/{}'.format(bucket, key)

    def get_item(self, table, key):
        try:
            item = table.get_item(Key=key, ConsistentRead=True)['Item']
        except ClientError:
            msg = 'Error getting item from {} table'.format(table)
            self._logger.exception(msg)
            raise
        return item

    def put_item(self, table, item):
        try:
            table.put_item(Item=item)
        except ClientError:
            msg = 'Error putting item {} into {} table'.format(item, table)
            self._logger.exception(msg)
            raise

    def get_transform_table_item(self, dataset):
        return self.get_item(self.transform_mapping_table, {'name': dataset})

    def update_object_metadata_catalog(self, item):
        item['id'] = self.build_id(item['bucket'], item['key'])
        item['timestamp'] = int(
            round(dt.datetime.utcnow().timestamp()*1000, 0))
        return self.put_item_in_object_metadata_table(item)

    def put_item_in_object_metadata_table(self, item):
        return self.put_item(self.object_metadata_table, item)

    def update_object(self, bucket, key, attribute_updates):
        try:
            self.object_metadata_table.update_item(
                Key={'id': self.build_id(bucket, key)},
                AttributeUpdates=attribute_updates
            )
        except ClientError:
            msg = 'Error updating object object s3://{}/{}'.format(bucket, key)
            self._logger.exception(msg)
            raise

    def remove_object_attribute(self, bucket, key, attribute):
        try:
            self.object_metadata_table.update_item(
                Key={'id': self.build_id(bucket, key)},
                UpdateExpression='REMOVE {}'.format(attribute)
            )
        except ClientError:
            msg = 'Error removing attribute {} for object s3://{}/{}'.format(
                attribute, bucket, key)
            self._logger.exception(msg)
            raise

    def query_object_metadata_index(self, index, key_expression, key_value, filter_expression, filter_value, max_items):
        try:
            items = []
            response = self.object_metadata_table.query(
                IndexName=index,
                KeyConditionExpression=Key(key_expression).eq(key_value),
                FilterExpression=Attr(filter_expression).eq(filter_value)
            )
            if response['Items']:
                items.extend(response['Items'])
            while 'LastEvaluatedKey' in response:
                response = self.object_metadata_table.query(
                    IndexName=index,
                    KeyConditionExpression=Key(key_expression).eq(key_value),
                    FilterExpression=Attr(filter_expression).eq(filter_value),
                    ExclusiveStartKey=response['LastEvaluatedKey']
                )
                if response['Items']:
                    items.extend(response['Items'])
                if len(items) > max_items:
                    items = items[:max_items]
                    break
        except ClientError:
            msg = 'Error querying object metadata {} index'.format(index)
            self._logger.exception(msg)
            raise
        return items
