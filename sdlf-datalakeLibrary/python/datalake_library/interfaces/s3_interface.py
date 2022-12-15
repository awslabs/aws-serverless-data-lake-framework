import json
import os
from datetime import datetime
from io import StringIO
from urllib.parse import unquote_plus

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from ..commons import init_logger
from ..datalake_exceptions import ObjectDeleteFailedException


class S3Interface:
    def __init__(self, log_level=None, s3_client=None, s3_resource=None):
        self.log_level = log_level or os.getenv("LOG_LEVEL", "INFO")
        self._logger = init_logger(__name__, self.log_level)
        self._session_config = Config(user_agent="awssdlf/1.0.0")
        self._s3_client = s3_client or boto3.client("s3", config=self._session_config)
        self._s3_resource = s3_resource or boto3.resource("s3", config=self._session_config)

    def download_object(self, bucket, key):
        self._logger.info("Downloading object: {}/{}".format(bucket, key))
        object_path = "/tmp/" + key.split("/")[-1]
        key = unquote_plus(key)
        try:
            self._s3_resource.Bucket(bucket).download_file(key, object_path)
        except ClientError:
            msg = "Error downloading object: {}/{}".format(bucket, key)
            self._logger.exception(msg)
            raise
        return object_path

    def upload_object(self, object_path, bucket, key, kms_key=None):
        self._logger.info("Uploading object: {}".format(object_path))
        try:
            extra_kwargs = {}
            if kms_key:
                extra_kwargs = {"ServerSideEncryption": "aws:kms", "SSEKMSKeyId": kms_key}
            self._s3_client.upload_file(object_path, bucket, key, ExtraArgs=extra_kwargs)
        except ClientError:
            msg = "Error uploading object: {}/{}".format(bucket, key)
            self._logger.exception(msg)
            raise
        return

    def list_objects(self, bucket, keys_path):
        keys_path = unquote_plus(keys_path)
        self._logger.info("Listing objects in: s3://{}/{}".format(bucket, keys_path))
        keys_path = keys_path + "/" if not keys_path.endswith("/") else keys_path
        keys = []
        for obj in self._s3_resource.Bucket(bucket).objects.filter(Prefix=keys_path):
            if obj.key[-1] != "/":
                keys.append(obj.key)
        return keys

    def read_object(self, bucket, key):
        key = unquote_plus(key)
        self._logger.info("Reading object from {}/{}".format(bucket, key))
        data = StringIO()
        try:
            obj = self._s3_resource.Object(bucket, key)
            for line in obj.get()["Body"].iter_lines():
                data.write("{}\n".format(line.decode("utf-8")))
            data.seek(0)
        except ClientError:
            msg = "Error reading object: {}/{}".format(bucket, key)
            self._logger.exception(msg)
            raise
        return data

    def write_object(self, bucket, key, data_object, kms_key=None):
        self._logger.info("Writing object to {}/{}".format(bucket, key))
        try:
            # always rewind for safety
            data_object.seek(0)
            extra_kwargs = {}
            if kms_key:
                extra_kwargs = {"ServerSideEncryption": "aws:kms", "SSEKMSKeyId": kms_key}
            self._s3_client.put_object(Bucket=bucket, Key=key, Body=data_object.read(), **extra_kwargs)
        except ClientError:
            msg = "Error uploading object: {}/{}".format(bucket, key)
            self._logger.exception(msg)
            raise

    def copy_object(self, source_bucket, source_key, dest_bucket, dest_key=None, kms_key=None):
        source_key = unquote_plus(source_key)
        self._logger.info(
            "Copying object {}/{} to {}/{}".format(
                source_bucket, source_key, dest_bucket, dest_key if dest_key else source_key
            )
        )
        try:
            extra_kwargs = {}
            if kms_key:
                extra_kwargs = {"ServerSideEncryption": "aws:kms", "SSEKMSKeyId": kms_key}
            copy_source = {"Bucket": source_bucket, "Key": source_key}
            self._s3_resource.meta.client.copy(
                copy_source, dest_bucket, dest_key if dest_key else source_key, ExtraArgs=extra_kwargs
            )
        except ClientError:
            msg = "Error copying object: {}/{} to {}/{}".format(
                source_bucket, source_key, dest_bucket, dest_key if dest_key else source_key
            )
            self._logger.exception(msg)
            raise

    def tag_object(self, bucket, key, tag_dict):
        self._logger.info("Tagging s3 object {}/{} with values {}".format(bucket, key, tag_dict))
        try:
            self._s3_client.put_object_tagging(
                Bucket=bucket, Key=key, Tagging={"TagSet": [{"Key": k, "Value": v} for k, v in tag_dict.items()]}
            )
        except ClientError:
            msg = "Error tagging object: {}/{}".format(bucket, key)
            self._logger.exception(msg)
            raise

    def delete_objects(self, bucket, prefix):
        prefix = unquote_plus(prefix)
        self._logger.info("Deleting all objects in bucket {} with prefix {}".format(bucket, prefix))
        object_paginator = self._s3_client.get_paginator("list_objects_v2")
        response_iterator = object_paginator.paginate(Bucket=bucket, Prefix=prefix)
        for response in response_iterator:
            if "Contents" in response:
                objects_to_delete = [{"Key": obj["Key"]} for obj in response["Contents"]]
                delete_response = self._s3_client.delete_objects(Bucket=bucket, Delete={"Objects": objects_to_delete})
                if "Errors" in delete_response:
                    self._logger.info("Object delete failed")
                    delete_errors = delete_response["Errors"]
                    raise ObjectDeleteFailedException(json.dumps(delete_errors))

        self._logger.info("Successfully deleted all objects in bucket {} with prefix {}".format(bucket, prefix))

    def get_size(self, bucket, key):
        return self._s3_client.head_object(Bucket=bucket, Key=key)["ContentLength"]

    def get_last_modified(self, bucket, key):
        last_modified_date = self._s3_client.head_object(Bucket=bucket, Key=key)["LastModified"]
        return last_modified_date.isoformat()
