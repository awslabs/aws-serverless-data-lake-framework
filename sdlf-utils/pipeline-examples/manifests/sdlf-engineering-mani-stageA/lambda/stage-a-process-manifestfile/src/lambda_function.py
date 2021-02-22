from datalake_library.commons import init_logger
from datalake_library.configuration.resource_configs import DynamoConfiguration, S3Configuration, KMSConfiguration
from datalake_library.interfaces.dynamo_interface import DynamoInterface
from datalake_library.interfaces.s3_interface import S3Interface
from datalake_library import octagon
from datalake_library.octagon import Artifact, EventReasonEnum, peh

logger = init_logger(__name__)
import json

def lambda_handler(event, context):
    """ Process the manifest file and loads into DynamoDB
    
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


    try:
        logger.info("Fetching event data from previous step")
        team = event['body']['team']
        pipeline = event['body']['pipeline']
        stage = event['body']['pipeline_stage']
        dataset = event['body']['dataset']
        peh_id = event['body']['peh_id']
        env = event['body']['env']
        bucket = event['body']['bucket']
        manifest_file_key = event['body']['key']
        manifest_file_name = manifest_file_key.split("/")[-1]
        


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

        ### Download the manifest file to local

        local_path = s3_interface.download_object(bucket, manifest_file_key)
        
        ### Process the manifest file

        with open(local_path,"r") as raw_file:
            file_names = [file_name.strip().split("/")[-1] for file_name in raw_file]

        ### Load data into manifests control table

        for file in file_names:
            item = {"dataset_name": team+"-"+dataset+"-" +
                    manifest_file_name, "datafile_name": manifest_file_name+"-"+file}
            dynamo_interface.put_item_in_manifests_control_table(item)

        ### Set s3 path for Copy
        s3_path = 'pre-stage/{}/manifests/{}/{}'.format(team,
                                              dataset, manifest_file_name)
        kms_key = KMSConfiguration(team).get_kms_arn

        ### Copy Manifest File to team/manifest/dataset location 
        
        s3_interface.copy_object(
            bucket, manifest_file_key, stage_bucket, s3_path, kms_key=kms_key)

        octagon_client.update_pipeline_execution(status="{} {} Processing".format(stage, component),
                                                 component=component)

        processed_keys = [s3_path]


    except Exception as e:
        logger.error("Fatal error", exc_info=True)
        octagon_client.end_pipeline_execution_failed(component=component,
                                                     issue_comment="{} {} Error: {}".format(stage, component, repr(e)))
        raise e

    return processed_keys


