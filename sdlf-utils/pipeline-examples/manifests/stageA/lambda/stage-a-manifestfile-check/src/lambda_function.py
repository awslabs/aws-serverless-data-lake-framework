from datalake_library.commons import init_logger
from datalake_library.configuration.resource_configs import DynamoConfiguration, SQSConfiguration, S3Configuration
from datalake_library.interfaces.dynamo_interface import DynamoInterface
from datalake_library.interfaces.sqs_interface import SQSInterface
from datalake_library.interfaces.s3_interface import S3Interface
from datalake_library import octagon
from datalake_library.octagon import Artifact, EventReasonEnum, peh

logger = init_logger(__name__)
import json
import re

def lambda_handler(event, context):
    """ Checks if a dataset is driven by manifest file
    
    Arguments:
        event {dict} -- Dictionary with details on previous processing step
        context {dict} -- Dictionary with details on Lambda context

    Returns:
        {dict} -- Dictionary with outcome of the process
    """

    try:
        logger.info("Fetching event data from previous step")
        team = event['body']['team']
        pipeline = event['body']['pipeline']
        stage = event['body']['pipeline_stage']
        dataset = event['body']['dataset']
        peh_id = event['body']['peh_id']
        env = event['body']['env']
        manifest_flag = event['body']['manifest_enabled']
        manifest_file_pattern = event['body']['manifest_details']['regex_pattern']
        manifest_file_timeout = event['body']['manifest_details']['manifest_timeout']
        manifest_datafile_timeout = event['body']['manifest_details']['manifest_data_timeout']
        input_file_name = event['body']['key'].split('/')[-1]

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

        ### Check if the file being processes is the manifest file

        match = re.match(manifest_file_pattern, input_file_name)

        if match:
            is_manifest_file = "True"
        else:
            is_manifest_file = "False"
        
        event['body']['is_manifest_file'] = is_manifest_file

        octagon_client.update_pipeline_execution(status="{} {} Processing".format(stage, component),
                                                 component=component)


    except Exception as e:
        logger.error("Fatal error", exc_info=True)
        octagon_client.end_pipeline_execution_failed(component=component,
                                                     issue_comment="{} {} Error: {}".format(stage, component, repr(e)))
        raise e

    return event


