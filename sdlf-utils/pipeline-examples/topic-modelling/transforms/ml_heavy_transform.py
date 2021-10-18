#######################################################
# Blueprint example of a custom transformation
# where a number of CSV files are dowloaded from
# Stage bucket and then submitted to a Glue Job
#######################################################
# License: Apache 2.0
#######################################################
# Author: noahpaig
#######################################################

#######################################################
# Import section
# sdlf-pipLibrary repository can be leveraged
# to add external libraries as a layer
#######################################################
import json
import datetime as dt
import boto3

from datalake_library.commons import init_logger
from datalake_library.configuration.resource_configs import KMSConfiguration

logger = init_logger(__name__)

# Create a client for the AWS Analytical service to use
client = boto3.client('comprehend')
s3_client = boto3.client('s3')


def datetimeconverter(o):
    if isinstance(o, dt.datetime):
        return o.__str__()


class CustomTransform():
    def __init__(self):
        logger.info("Topic Modeling Blueprint Heavy Transform initiated")

    def transform_object(self, bucket, keys, team, dataset):

        # # First Lets Delete Topic Model Output Post-Stage Topic_Data Folder S3
        # # We only want one Topic Model at all times as the one source of truth

        # List Objects in Zipped Topic Output
        prefix = "post-stage/{}/{}/topics".format(team, dataset)
        response = s3_client.list_objects_v2(Bucket=bucket, Prefix=prefix)

        # Delete Objects in Topics Folder S3 (if exists)
        if("Contents" in response.keys()):
            for obj in response['Contents']:
                s3_client.delete_object(Bucket=bucket, Key=obj['Key'])

        # Get KMS Key to Encrypt our Topic Model Output
        kms_key = KMSConfiguration(team).get_kms_arn

        # Setting our Topic Model Parameters
        # s3_input: Location of Abstract Txt Files in s3 pre-stage
        # s3_ouput: Location to Upload Zipped Topic Model Output
        key = keys[0].rsplit('/', 1)[0]
        s3_input = 's3://{}/pre-stage/{}/{}/abstract_documents'.format(
            bucket, team, dataset)
        s3_output = 's3://{}/post-stage/{}/{}/topics'.format(
            bucket, team, dataset)
        aws_account_id = bucket.split("-")[-2]
        job_name = 'MedicalResearchTopics'
        number_topics = 20
        data_access_role = 'arn:aws:iam::{}:role/state-machine/sdlf-{}-ml-process-b'.format(
            aws_account_id, team)

        # Finally let's call our Topic Detection Job to Start
        response = client.start_topics_detection_job(
            InputDataConfig={
                'S3Uri': s3_input,
                'InputFormat': 'ONE_DOC_PER_FILE'
            },
            OutputDataConfig={
                "KmsKeyId": kms_key,
                'S3Uri': s3_output

            },
            VolumeKmsKeyId=kms_key,
            DataAccessRoleArn=data_access_role,
            JobName=job_name,
            NumberOfTopics=number_topics
        )

        # Get our Job Details (including jobStatus so we can later check if Completed)
        job_details = {
            "jobName": job_name,
            "jobRunId": response['JobId'],
            "jobStatus": response['JobStatus']
        }

        #######################################################
        # IMPORTANT
        # This function must return a dictionary object with at least a reference to:
        # 1) processedKeysPath (i.e. S3 path where topic model outputs data)
        # 2) jobDetails (i.e. a Dictionary holding information about the job
        # e.g. jobName and jobId for Topic model
        # A jobStatus key MUST be present in jobDetails as it's used to determine the status of the job)
        # Example: {processedKeysPath' = 'post-stage/engineering/medicalresearch/topics',
        # 'jobDetails': {'jobName': 'MedicalResearchTopics', 'jobId': 'jr-2ds438nfinev34', 'jobStatus': 'SUBMITTED'}}
        #######################################################

        processed_keys = 'post-stage/{}/{}/topic_data'.format(team, dataset)

        response = {
            'processedKeysPath': processed_keys,
            'jobDetails': job_details
        }

        return response

    def check_job_status(self, bucket, keys, processed_keys_path, job_details):

        # Check on the status of our job to check if completed or still running
        job_repsonse = client.describe_topics_detection_job(
            JobId=job_details["jobRunId"])
        job_details["jobStatus"] = job_repsonse["TopicsDetectionJobProperties"]["JobStatus"]

        # #######################################################
        # # IMPORTANT
        # # This function must return a dictionary object with at least a reference to:
        # # 1) processedKeysPath (i.e. S3 path where job outputs data without the "s3://{bucket}")
        # # 2) jobDetails (i.e. a Dictionary holding information about the job
        # # e.g. jobName and jobId for Topic model
        # # A jobStatus key MUST be present in jobDetails as it's used to determine the status of the job)
        # # Example: {processedKeysPath' = 'post-stage/legislators',
        # # 'jobDetails': {'jobName': 'MedicalResearchTopics', 'jobId': 'jr-2ds438nfinev34', 'jobStatus': 'IN_PROGRESS'}}
        # #######################################################
        response = {
            'processedKeysPath': processed_keys_path,
            'jobDetails': job_details
        }

        return response
