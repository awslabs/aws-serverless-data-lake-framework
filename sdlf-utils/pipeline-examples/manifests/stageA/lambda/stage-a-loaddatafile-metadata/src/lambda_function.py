from datalake_library.commons import init_logger
from datalake_library.configuration.resource_configs import DynamoConfiguration, S3Configuration, KMSConfiguration
from datalake_library.interfaces.dynamo_interface import DynamoInterface
from datalake_library.interfaces.s3_interface import S3Interface
from datalake_library import octagon
from datalake_library.octagon import Artifact, EventReasonEnum, peh

logger = init_logger(__name__)
import json
import re
import datetime as dt
import time


def lambda_handler(event, context):
    """ Load Datafile metadata in manifests control table
        Check if manifest file is available within the threshold
    
    Arguments:
        event {dict} -- Dictionary with details on previous processing step
        context {dict} -- Dictionary with details on Lambda context

    Returns:
        {dict} -- Dictionary with outcome of the process
    """
    s3_interface = S3Interface()
    stage_bucket = S3Configuration().stage_bucket

    dynamo_config = DynamoConfiguration()
    dynamo_interface = DynamoInterface(dynamo_config)
    current_time = dt.datetime.utcnow()
    current_timestamp = current_time.timestamp()


    try:
        logger.info("Fetching event data from previous step")
        team = event['body']['team']
        pipeline = event['body']['pipeline']
        stage = event['body']['pipeline_stage']
        dataset = event['body']['dataset']
        peh_id = event['body']['peh_id']
        env = event['body']['env']
        bucket = event['body']['bucket']
        input_file_key = event['body']['key']
        input_file_name = input_file_key.split("/")[-1]
        manifest_file_pattern = event['body']['manifest_details']['regex_pattern']
        manifest_timeout = int(event['body']['manifest_details']['manifest_timeout'])
        
        if 'manifest_interval' in event['body']:
            manifest_interval = event['body']['manifest_interval']
        else:
            manifest_interval = current_timestamp


        logger.info('Initializing Octagon client')
        component = context.function_name.split('-')[-2].title()
        octagon_client = (
            octagon.OctagonClient()
            .with_run_lambda(True)
            .with_configuration_instance(env)
            .build()
        )
        peh.PipelineExecutionHistoryAPI(
            octagon_client).retrieve_pipeline_execution(peh_id)

        octagon_client.update_pipeline_execution(status="{} {} Processing".format(stage, component),
                                                 component=component)
        
        ### List S3 Objects for the manifest file in the manifest prefix
        ### For this to work the manifest should have been loaded into DynamoDB

        manifest_key = "pre-stage/{}/manifests/{}/".format(team, dataset)
        processed_manifest_keys = s3_interface.list_objects(
            stage_bucket, manifest_key)
        
        matched_keys =[]
        items = []
        
        if not processed_manifest_keys:
            logger.info("Manifest File has not been loaded, sleeping for 5 mins")
            time.sleep(300)
            manifest_file_loaded="False"

        else:
            for manifest_file_key in processed_manifest_keys:
                manifest_file_name = manifest_file_key.split("/")[-1]
                match = re.match(manifest_file_pattern, manifest_file_name)
                if match:
                    matched_keys.append(manifest_file_name)
                
                ### Query Manifests Control table
                for keys in matched_keys:
                    dataset_name=team+"-"+dataset
                    try:
                        items.append(dynamo_interface.get_item_from_manifests_control_table(
                        dataset_name, keys, input_file_name))
                    except KeyError:
                        logger.info("Manifest File has not been loaded, sleeping for 5 mins")
                        manifest_file_loaded="False"
                
                ### Update Manifests Control table

                if not items:
                    logger.info(
                        "Manifest File has not been loaded, sleeping for 5 mins")
                    time.sleep(300)
                    manifest_file_loaded="False"
                else:
                    ddb_key = {
                        'dataset_name': items[0]['dataset_name'], 'datafile_name': items[0]['datafile_name']}
                    STATUS="STARTED"
                    dynamo_interface.update_manifests_control_table_stagea(
                        ddb_key, STATUS)
                    manifest_file_loaded="True"
                    event['body']['manifest_ddb_key'] = ddb_key
        
        ### Check if Manifest threshold has exceeded

        if current_timestamp == manifest_interval:
            current_timestamp = dt.datetime.utcnow().timestamp()

        if int((current_timestamp - manifest_interval)/60) >= manifest_timeout:
            logger.error("Manifest Threshold Breached")
            raise Exception("Manifest Threshold Breached")

        event['body']['manifest_interval'] = manifest_interval
        event['body']['manifest_file_loaded'] = manifest_file_loaded

    except Exception as e:
        logger.error("Fatal error", exc_info=True)
        octagon_client.end_pipeline_execution_failed(component=component,
                                                     issue_comment="{} {} Error: {}".format(stage, component, repr(e)))
        raise e

    return event


