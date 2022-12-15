#######################################################
# Blueprint example of a custom transformation
# where a number of CSV files are dowloaded from
# Stage bucket and then submitted to a Glue Job
#######################################################
# License: Apache 2.0
#######################################################
# Author: jaidi
#######################################################

import datetime as dt

#######################################################
# Import section
# common-pipLibrary repository can be leveraged
# to add external libraries as a layer
#######################################################
import json

import boto3
from datalake_library.commons import init_logger

logger = init_logger(__name__)

# Create a client for the AWS Analytical service to use
client = boto3.client("glue")


def datetimeconverter(o):
    if isinstance(o, dt.datetime):
        return o.__str__()


class CustomTransform:
    def __init__(self):
        logger.info("Glue Job Blueprint Heavy Transform initiated")

    def transform_object(self, bucket, keys, team, dataset):
        #######################################################
        # We assume a Glue Job has already been created based on
        # customer needs. This function makes an API call to start it
        #######################################################
        job_name = "sdlf-{}-{}-glue-job".format(team, dataset)  # Name of the Glue Job

        tables = []
        for key in keys:
            tables.append(key.split("/")[-1].split("_")[0])

        # S3 Path where Glue Job outputs processed keys
        # IMPORTANT: Build the output s3_path without the s3://stage-bucket/
        processed_keys_path = "post-stage/{}/{}".format(team, dataset)
        # Submitting a new Glue Job
        job_response = client.start_job_run(
            JobName=job_name,
            Arguments={
                # Specify any arguments needed based on bucket and keys (e.g. input/output S3 locations)
                "--JOB_NAME": "sdlf-{}-{}-glue-job".format(team, dataset),
                "--SOURCE_LOCATION": "s3://{}/{}".format(bucket, keys[0].rsplit("/", 1)[0]),
                "--OUTPUT_LOCATION": "s3://{}/{}".format(bucket, processed_keys_path),
                "--job-bookmark-option": "job-bookmark-enable",
            },
            MaxCapacity=2.0,
        )
        # Collecting details about Glue Job after submission (e.g. jobRunId for Glue)
        json_data = json.loads(json.dumps(job_response, default=datetimeconverter))
        job_details = {
            "jobName": job_name,
            "jobRunId": json_data.get("JobRunId"),
            "jobStatus": "STARTED",
            "tables": list(set(tables)),
        }

        #######################################################
        # IMPORTANT
        # This function must return a dictionary object with at least a reference to:
        # 1) processedKeysPath (i.e. S3 path where job outputs data without the s3://stage-bucket/ prefix)
        # 2) jobDetails (i.e. a Dictionary holding information about the job
        # e.g. jobName and jobId for Glue or clusterId and stepId for EMR
        # A jobStatus key MUST be present in jobDetails as it's used to determine the status of the job)
        # Example: {processedKeysPath' = 'post-stage/engineering/legislators',
        # 'jobDetails': {'jobName': 'sdlf-engineering-legislators-glue-job', 'jobId': 'jr-2ds438nfinev34', 'jobStatus': 'STARTED'}}
        #######################################################
        response = {"processedKeysPath": processed_keys_path, "jobDetails": job_details}

        return response

    def check_job_status(self, bucket, keys, processed_keys_path, job_details):
        # This function checks the status of the currently running job
        job_response = client.get_job_run(JobName=job_details["jobName"], RunId=job_details["jobRunId"])
        json_data = json.loads(json.dumps(job_response, default=datetimeconverter))
        # IMPORTANT update the status of the job based on the job_response (e.g RUNNING, SUCCEEDED, FAILED)
        job_details["jobStatus"] = json_data.get("JobRun").get("JobRunState")

        #######################################################
        # IMPORTANT
        # This function must return a dictionary object with at least a reference to:
        # 1) processedKeysPath (i.e. S3 path where job outputs data without the s3://stage-bucket/ prefix)
        # 2) jobDetails (i.e. a Dictionary holding information about the job
        # e.g. jobName and jobId for Glue or clusterId and stepId for EMR
        # A jobStatus key MUST be present in jobDetails as it's used to determine the status of the job)
        # Example: {processedKeysPath' = 'post-stage/legislators',
        # 'jobDetails': {'jobName': 'sdlf-engineering-legislators-glue-job', 'jobId': 'jr-2ds438nfinev34', 'jobStatus': 'RUNNING'}}
        #######################################################
        response = {"processedKeysPath": processed_keys_path, "jobDetails": job_details}

        return response
