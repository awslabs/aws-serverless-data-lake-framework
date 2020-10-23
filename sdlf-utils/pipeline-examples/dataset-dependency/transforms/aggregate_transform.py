import json
import datetime as dt

import boto3

from datalake_library.commons import init_logger

logger = init_logger(__name__)

client = boto3.client('glue')


def datetimeconverter(o):
    if isinstance(o, dt.datetime):
        return o.__str__()


class CustomTransform():
    def __init__(self):
        logger.info("Job Mocker")

    def transform_object(self, bucket, keys, team, dataset):
        job_details = {
            "jobName": "test",
            "jobRunId": "test",
            "jobStatus": "STARTED"
        }

        response = {
            "processedKeysPath": "",
            "jobDetails": job_details
        }

        return response

    def check_job_status(self, bucket, keys, processed_keys_path, job_details):
        job_details = {
            "jobName": "test",
            "jobRunId": "test",
            "jobStatus": "SUCCEEDED"
        }

        response = {
            "processedKeysPath": processed_keys_path,
            "jobDetails": job_details
        }

        return response
