#######################################################
# Blueprint example of a custom transformation
# where a number of CSV files are dowloaded from
# Stage bucket and then submitted to a Glue Job
#######################################################
# License: Apache 2.0
#######################################################
# Author: moumnajhi
#######################################################

#######################################################
# Import section
# common-pipLibrary repository can be leveraged
# to add external libraries as a layer
#######################################################
import json
import datetime as dt

import boto3

from datalake_library.commons import init_logger
from datalake_library.configuration.resource_configs import DynamoConfiguration, S3Configuration, KMSConfiguration
from datalake_library.interfaces.dynamo_interface import DynamoInterface
from datalake_library.interfaces.s3_interface import S3Interface

logger = init_logger(__name__)

# Create a client for the AWS Analytical service to use
client = boto3.client('glue')


def datetimeconverter(o):
    if isinstance(o, dt.datetime):
        return o.__str__()

def get_manifest_data(bucket,team, dataset,manifest_key):
    """ Returns a list of items from manifests control table """
    dynamo_config = DynamoConfiguration()
    dynamo_interface = DynamoInterface(dynamo_config)
    s3_interface = S3Interface()
    local_path = s3_interface.download_object(bucket, manifest_key)
    ddb_keys=[]
    items=[]
    with open(local_path, "r") as raw_file:
        file_names = [file_name.strip().split("/")[-1]
                      for file_name in raw_file]
        for file in file_names:
            ddb_keys.append({
                "dataset_name": team+"-"+dataset,
                "manifest_file_name": manifest_key.split("/")[-1], "datafile_name": file
            })
    for ddb_key in ddb_keys:
        try:
            items.append(dynamo_interface.get_item_from_manifests_control_table(
                ddb_key["dataset_name"], ddb_key["manifest_file_name"], ddb_key["datafile_name"]))
        except KeyError:
            logger.error("The manifest file has not been processed in Stage A")    
            raise Exception("Manifest File has not been processed in Stage A")
    
    return items

def get_s3_keys(items):
    s3_items = items
    s3_keys=[]
    for item in s3_items:
        s3_keys.append(item["s3_key"])
    return s3_keys

def get_ddb_keys(items):
    ddb_keys = []
    for item in items:
        ddb_key={'dataset_name':item['dataset_name'],'datafile_name':item['datafile_name']}
        ddb_keys.append(ddb_key)
    return ddb_keys



class CustomTransform():
    def __init__(self):
        logger.info("Glue Job Blueprint Heavy Transform initiated")

    def transform_object(self, bucket, keys, team, dataset):
        #######################################################
        # We assume a Glue Job has already been created based on
        # customer needs. This function makes an API call to start it
        #######################################################
        job_name = 'sdlf-{}-{}-glue-job'.format(team, dataset)  # Name of the Glue Job

        ### Create the list of s3 keys to be processed by the glue job
        ### keys will contain a single file for manifest processing
        
        items = get_manifest_data(bucket, team, dataset,keys[0])

        s3_keys = get_s3_keys(items)

        files = []
        file_names=""
        for key in s3_keys:
            files.append(
                key.split('/')[-1]
            )
            if file_names is not None:
                file_names=file_names+"|"+key
            else:
                file_names=key

        ### Update Manifests Control Table
        ddb_keys = get_ddb_keys(items)

        dynamo_config = DynamoConfiguration()
        dynamo_interface = DynamoInterface(dynamo_config)

        for ddb_key in ddb_keys:
            dynamo_interface.update_manifests_control_table_stageb(ddb_key,"PROCESSING")
        


        # S3 Path where Glue Job outputs processed keys
        # IMPORTANT: Build the output s3_path without the s3://stage-bucket/
        processed_keys_path = 'post-stage/{}/{}'.format(team, dataset)
        # Submitting a new Glue Job
        job_response = client.start_job_run(
            JobName=job_name,
            Arguments={
                # Specify any arguments needed based on bucket and keys (e.g. input/output S3 locations)
                '--JOB_NAME': 'sdlf-{}-{}-glue-job'.format(team, dataset),
                '--SOURCE_LOCATION': 's3://{}/'.format(bucket),
                '--OUTPUT_LOCATION': 's3://{}/{}'.format(bucket, processed_keys_path),
                '--FILE_NAMES': file_names,
                '--job-bookmark-option': 'job-bookmark-enable'
            },
            MaxCapacity=2.0
        )
        # Collecting details about Glue Job after submission (e.g. jobRunId for Glue)
        json_data = json.loads(json.dumps(
            job_response, default=datetimeconverter))
        job_details = {
            "jobName": job_name,
            "jobRunId": json_data.get('JobRunId'),
            "jobStatus": 'STARTED',
            "files": list(set(files))
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
        response = {
            'processedKeysPath': processed_keys_path,
            'jobDetails': job_details
        }

        return response

    def check_job_status(self, bucket, keys, processed_keys_path, job_details):
        # This function checks the status of the currently running job
        job_response = client.get_job_run(
            JobName=job_details['jobName'], RunId=job_details['jobRunId'])
        json_data = json.loads(json.dumps(
            job_response, default=datetimeconverter))
        # IMPORTANT update the status of the job based on the job_response (e.g RUNNING, SUCCEEDED, FAILED)
        job_details['jobStatus'] = json_data.get('JobRun').get('JobRunState')

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
        response = {
            'processedKeysPath': processed_keys_path,
            'jobDetails': job_details
        }

        return response
