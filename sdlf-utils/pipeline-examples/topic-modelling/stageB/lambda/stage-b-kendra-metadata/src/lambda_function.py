import boto3
import io
from io import StringIO
import pandas as pd
from datetime import datetime
import json

from datalake_library.commons import init_logger
from datalake_library import octagon
from datalake_library.octagon import Artifact, EventReasonEnum, peh
from datalake_library.configuration.resource_configs import S3Configuration, KMSConfiguration
from datalake_library.interfaces.s3_interface import S3Interface

logger = init_logger(__name__)
s3_interface = S3Interface()
s3client = boto3.client('s3')

def lambda_handler(event, context):
    """Write Metadata JSON Files for Data Source

    Arguments:
        event {dict} -- Dictionary with details on Bucket and Keys
        context {dict} -- Dictionary with details on Lambda context

    Returns:
        {dict} -- Dictionary with Processed Bucket and Keys Path
    """
    try:
        logger.info('Fetching event data from previous step')
        team = event['body']['team']
        stage = event['body']['pipeline_stage']
        dataset = event['body']['dataset']
        bucket = event['body']['bucket']
        
        
        # This Stage will Add Metadata Directory
        # (NOTE: We can use metadata to filter queries in Amazon Kendra):
        
        # Add a Metadata Directory for a s3 location to write json files 
        directory_key = "pre-stage/{}/{}/datasource_metadata/".format(team, dataset)
        s3client.put_object(Bucket=bucket, Key=directory_key)
        
        # Get KMS Key to Encrypt Data
        kms_key = KMSConfiguration(team).get_kms_arn
        
        # Read in our compiled metadata and topic data in a DataFrame
        key = "post-stage/{}/{}/compile_topics_data.csv".format(team, dataset)
        obj = s3client.get_object(Bucket = bucket, Key = key)
        metadata = pd.read_csv(io.BytesIO(obj['Body'].read()), encoding='utf8')
        
        
        # Add A Dictionary to Pass JSON Strucutre Parameters for Each 
        # Lambda Invocation (one for ever 10,000 rows so no timeouts)
        rows = metadata["abstract"].count()
        invocations = int((rows/10000) + 1)
        jobs = {}
        jobList = []
        for i in range(0, invocations):
            # Set Start and End Rows for each Lambda
            start = i * 10000
            
            if (i+1) == invocations:
                end = rows
            else:
                end = (i + 1) * 10000
            
            # Send a Payload with the s3 path to write and the start/end row count
            payload = {
                "start": str(start),
                "end": str(end),
                "key": key,
                "bucket": bucket,
                "directory_key":directory_key,
                "team": team,
                "dataset": dataset
            }
            jobList.append(payload)
            
        jobs["jobList"] = jobList
        
        logger.info('Initializing Octagon client')
        component = context.function_name.split('-')[-2].title()
        octagon_client = (
            octagon.OctagonClient()
            .with_run_lambda(True)
            .with_configuration_instance(event['body']['env'])
            .build()
        )
        peh.PipelineExecutionHistoryAPI(octagon_client).retrieve_pipeline_execution(
            event['body']['job']['peh_id'])


        octagon_client.update_pipeline_execution(
            status="{} {} Processing".format(stage, component), component=component)
            
    except Exception as e:
        logger.error("Fatal error", exc_info=True)
        octagon_client.end_pipeline_execution_failed(component=component,
                                                     issue_comment="{} {} Error: {}".format(stage, component, repr(e)))
        raise e
    return jobs