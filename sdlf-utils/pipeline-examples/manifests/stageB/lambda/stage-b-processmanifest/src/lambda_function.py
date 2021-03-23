import os
import shutil
import time
import datetime as dt

from datalake_library.commons import init_logger
from datalake_library.transforms.transform_handler import TransformHandler
from datalake_library import octagon
from datalake_library.octagon import Artifact, EventReasonEnum, peh
from datalake_library.configuration.resource_configs import DynamoConfiguration, S3Configuration, KMSConfiguration
from datalake_library.interfaces.dynamo_interface import DynamoInterface
from datalake_library.interfaces.s3_interface import S3Interface

logger = init_logger(__name__)


def remove_content_tmp():
    # Remove contents of the Lambda /tmp folder (Not released by default)
    for root, dirs, files in os.walk('/tmp'):
        for f in files:
            os.unlink(os.path.join(root, f))
        for d in dirs:
            shutil.rmtree(os.path.join(root, d))

def get_ddb_keys(keys_to_process, bucket, team, dataset):
    ### Returns a list of DynamoDB keys for Querying
    ddb_keys = []
    for key in keys_to_process:
        s3_interface = S3Interface()
        local_path = s3_interface.download_object(bucket, key)
        with open(local_path, "r") as raw_file:
            file_names = [file_name.strip().split("/")[-1]
                          for file_name in raw_file]
            for file in file_names:
                ddb_keys.append({
                    "dataset_name": team+"-"+dataset,
                    "manifest_file_name": key.split("/")[-1], "datafile_name": file
                })
    return ddb_keys



def lambda_handler(event, context):
    """Checks if the file to be processed is  manifest driven 

    Arguments:
        event {dict} -- Dictionary with details on previous processing step
        context {dict} -- Dictionary with details on Lambda context

    Returns:
        {dict} -- Dictionary with Processed Bucket and Key(s)
    """
    try:
        logger.info('Fetching event data from previous step')
        bucket = event['body']['bucket']
        keys_to_process = event['body']['keysToProcess']
        team = event['body']['team']
        pipeline = event['body']['pipeline']
        stage = event['body']['pipeline_stage']
        dataset = event['body']['dataset']
        peh_id = event['body']['peh_id']
        manifest_data_timeout = int(
            event['body']['manifest_details']['manifest_data_timeout'])
        current_time = dt.datetime.utcnow()
        current_timestamp = current_time.timestamp()

        if 'manifest_interval' in event['body']:
            manifest_interval = event['body']['manifest_interval']
        else:
            manifest_interval = current_timestamp

        logger.info('Initializing Octagon client')
        component = context.function_name.split('-')[-2].title()
        octagon_client = (
            octagon.OctagonClient()
            .with_run_lambda(True)
            .with_configuration_instance(event['body']['env'])
            .build()
        )

        peh.PipelineExecutionHistoryAPI(
            octagon_client).retrieve_pipeline_execution(peh_id)
        
        ### Set max_items_process in datasets table so that the statemachine only processes 1 manifest file at a time

        ddb_keys = get_ddb_keys(keys_to_process, bucket, team, dataset)

        dynamo_config = DynamoConfiguration()
        dynamo_interface = DynamoInterface(dynamo_config)

        ### Query Manifest Control Table to get the status
        items = []
        
        logger.info("Querying DynamoDB to check data in manifests control table for Stage A status")
        
        for ddb_key in ddb_keys:
            try:
                items.append(dynamo_interface.get_item_from_manifests_control_table(ddb_key["dataset_name"], ddb_key["manifest_file_name"], ddb_key["datafile_name"]))
            except KeyError:
                logger.error("The manifest file has not been processed in Stage A")
                raise Exception("Manifest File has not been processed in Stage A")

        ### Check stage a status for data files
        logger.info("Checking to see if all the files have been processed in Stage A")

        status_message_list = []
        failed_status_message_list=[]
        wait_message_counter = 0
        failed_message_counter = 0

        for item in items:
            if "stage_a_status" in item:
                stage_a_status = item["stage_a_status"]
            else:
                stage_a_status = "NOT STARTED"
            
            if stage_a_status != "COMPLETED" and stage_a_status != "FAILED":
                status_message_list.append(
                    "Waiting for Data File {}".format(item["datafile_name"].split("-")[-1]))
                wait_message_counter +=1
            
            elif stage_a_status == "FAILED":
                failed_status_message_list.append(
                    "Data Files Failed in Stage A {}".format(item["datafile_name"].split("-")[-1]))
                failed_message_counter +=1

        if failed_message_counter > 0 :
            logger.error("Data File Failure in Stage A, Processing will stop")
            logger.error("The following files have failed in Stage A")
            for message in failed_status_message_list:
                logger.error(message)
            ### Update manifest control table, mark all files as failed in Stage B
            for ddb_key in ddb_keys:
                update_key = dynamo_interface.manifest_keys(ddb_key["dataset_name"], ddb_key["manifest_file_name"],ddb_key["datafile_name"])
                dynamo_interface.update_manifests_control_table_stageb(
                    update_key, "FAILED", None, "Datafile Failed in Stage A")
            raise Exception("Data File Failure in Stage A")

        if wait_message_counter > 0:
            logger.info("Waiting for Data Files to be processed in Stage A")
            for message in status_message_list:
                logger.info(message)
            logger.info ("Will sleep for 5 mins")
            time.sleep(300)
            data_file_wait="True"
            if manifest_interval == current_timestamp:
                current_timestamp = dt.datetime.utcnow().timestamp()
            
            if int((current_timestamp - manifest_interval)/60) >= manifest_data_timeout:
                logger.error("Data File Threshold Breached")
                logger.error("Stage B Processing Will Stop Now")
                data_file_wait="False"
                for message in status_message_list:
                    logger.error(message)
                ### Update manifest control table, mark all files as failed in Stage B
                for ddb_key in ddb_keys:
                    update_key = dynamo_interface.manifest_keys(
                        ddb_key["dataset_name"], ddb_key["manifest_file_name"], ddb_key["datafile_name"])
                    dynamo_interface.update_manifests_control_table_stageb(
                        update_key, "FAILED", None, "Datafile threshold Breached")
                raise Exception("Data File Threshold Breached")
        else:
            logger.info("All files processed in Stage A")
            data_file_wait = "False"
            for ddb_key in ddb_keys:
                update_key = dynamo_interface.manifest_keys(
                    ddb_key["dataset_name"], ddb_key["manifest_file_name"], ddb_key["datafile_name"])
                dynamo_interface.update_manifests_control_table_stageb(
                    update_key, "STARTED")

        event["body"]["manifest_interval"] = manifest_interval
        event["body"]["data_file_wait"] = data_file_wait

        remove_content_tmp()
        octagon_client.update_pipeline_execution(
            status="{} {} Processing".format(stage, component), component=component)
    except Exception as e:
        logger.error("Fatal error", exc_info=True)
        octagon_client.end_pipeline_execution_failed(component=component,
                                                     issue_comment="{} {} Error: {}".format(stage, component, repr(e)))
        remove_content_tmp()
        raise e
    return event
