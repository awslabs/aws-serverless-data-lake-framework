#######################################################
# Blueprint example of a custom transformation
# where a number of text files are dowloaded from
# Stage bucket and then submitted to a Comprehend Job
#######################################################
# License: Apache 2.0
#######################################################
# Author: antonkuk
#######################################################

#######################################################
# Import section
# sdlf-pipLibrary repository can be leveraged
# to add external libraries as a layer
#######################################################
import datetime as dt
import boto3

from datalake_library.commons import init_logger
from datalake_library.configuration.resource_configs import KMSConfiguration

logger = init_logger(__name__)

# Create a client for the AWS Analytical service to use
client = boto3.client("comprehend")
s3_client = boto3.client("s3")


def datetimeconverter(o):
    if isinstance(o, dt.datetime):
        return o.__str__()


class CustomTransform():
    def __init__(self):
        logger.info("Sentiment Analysis Blueprint Heavy Transform initiated")

    def transform_object(self, bucket, keys, team, dataset):

        # # First Lets Delete Sentiment Model Output Post-Stage Sentiment_Data Folder S3
        # # We only want one Sentiment Model at all times as the one source of truth

        # List Objects in Zipped Sentiment Output
        prefix = "post-stage/{}/{}/sentiments".format(team, dataset)
        response = s3_client.list_objects_v2(Bucket=bucket, Prefix=prefix)

        # Delete Objects in Sentiments Folder S3 (if exists)
        if("Contents" in response.keys()):
            for obj in response["Contents"]:
                s3_client.delete_object(Bucket=bucket, Key=obj["Key"])

        # Get KMS Key to Encrypt our Sentiment Model Output
        kms_key = KMSConfiguration(team).get_kms_arn

        # Setting our Sentiment Model Parameters
        # s3_input: Location of Review Files in s3 pre-stage
        # s3_output: Location to Upload Zipped Sentiment Model Output
        key = keys[0].rsplit("/", 1)[0]
        s3_input = "s3://{}/pre-stage/{}/{}/reviews".format(
            bucket, team, dataset)
        s3_output = "s3://{}/post-stage/{}/{}/sentiments".format(
            bucket, team, dataset)
        aws_account_id = bucket.split("-")[6]  # Get AWS account id from bucket name
        job_name = "PaperclipReviewsSentimentAnalysis"
        data_access_role = "arn:aws:iam::{}:role/state-machine/sdlf-{}-ml-process-b".format(
            aws_account_id, team)

        # Finally let's call our Sentiment Analyis Job to Start
        response = client.start_sentiment_detection_job(
            InputDataConfig={
                "S3Uri": s3_input,
                "InputFormat": "ONE_DOC_PER_FILE"
            },
            OutputDataConfig={
                "KmsKeyId": kms_key,
                "S3Uri": s3_output

            },
            VolumeKmsKeyId=kms_key,
            DataAccessRoleArn=data_access_role,
            JobName=job_name,
            LanguageCode="en",
        )

        # Get our Job Details (including jobStatus so we can later check if Completed)
        job_details = {
            "jobName": job_name,
            "jobRunId": response["JobId"],
            "jobStatus": response["JobStatus"]
        }

        #######################################################
        # IMPORTANT
        # This function must return a dictionary object with at least a reference to:
        # 1) processedKeysPath (i.e. S3 path where topic model outputs data)
        # 2) jobDetails (i.e. a Dictionary holding information about the job
        # e.g. jobName and jobId for Topic model
        # A jobStatus key MUST be present in jobDetails as it's used to determine the status of the job)
        # Example: {processedKeysPath' = 'post-stage/engineering/paperclips/sentiments',
        # 'jobDetails': {'jobName': 'PaperclipReviewsSentimentAnalysis', 'jobId': 'jr-2ds438nfinev34',
        # 'jobStatus': 'SUBMITTED'}}
        #######################################################

        processed_keys = "post-stage/{}/{}/sentiments".format(team, dataset)

        response = {
            "processedKeysPath": processed_keys,
            "jobDetails": job_details
        }

        return response

    def check_job_status(self, bucket, keys, processed_keys_path, job_details):

        # Check on the status of our job to check if completed or still running
        job_repsonse = client.describe_sentiment_detection_job(
            JobId=job_details["jobRunId"])
        job_details["jobStatus"] = job_repsonse["SentimentDetectionJobProperties"]["JobStatus"]
        job_details["outputDataConfig"] = job_repsonse["SentimentDetectionJobProperties"]["OutputDataConfig"]

        # #######################################################
        # # IMPORTANT
        # # This function must return a dictionary object with at least a reference to:
        # # 1) processedKeysPath (i.e. S3 path where job outputs data without the "s3://{bucket}")
        # # 2) jobDetails (i.e. a Dictionary holding information about the job
        # # e.g. jobName and jobId for Sentiments model
        # # A jobStatus key MUST be present in jobDetails as it's used to determine the status of the job)
        # # Example: {processedKeysPath' = 'post-stage/legislators',
        # # 'jobDetails': {'jobName': 'PaperclipReviewsSentimentAnalysis', 'jobId': 'jr-2ds438nfinev34', 'jobStatus': 'IN_PROGRESS'}}
        # #######################################################
        response = {
            "processedKeysPath": processed_keys_path,
            "jobDetails": job_details
        }

        return response
