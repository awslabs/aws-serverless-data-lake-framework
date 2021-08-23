from datalake_library.commons import init_logger
from datalake_library.transforms.transform_handler import TransformHandler
from datalake_library import octagon
from datalake_library.octagon import Artifact, EventReasonEnum, peh
from datalake_library.configuration.resource_configs import DynamoConfiguration, S3Configuration
from datalake_library.interfaces.dynamo_interface import DynamoInterface
from datalake_library.interfaces.s3_interface import S3Interface

logger = init_logger(__name__)


def get_manifest_data(bucket, team, dataset, manifest_key):
    """ Returns a list of items from manifests control table """
    dynamo_config = DynamoConfiguration()
    dynamo_interface = DynamoInterface(dynamo_config)
    s3_interface = S3Interface()
    local_path = s3_interface.download_object(bucket, manifest_key)
    ddb_keys = []
    items = []
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


def get_ddb_keys(items):
    ddb_keys = []
    for item in items:
        ddb_key = {'dataset_name': item['dataset_name'],
                   'datafile_name': item['datafile_name']}
        ddb_keys.append(ddb_key)
    return ddb_keys

def lambda_handler(event, context):
    """Calls custom job waiter developed by user

    Arguments:
        event {dict} -- Dictionary with details on previous processing step
        context {dict} -- Dictionary with details on Lambda context

    Returns:
        {dict} -- Dictionary with Processed Bucket, Key(s) and Job Details
    """
    try:
        logger.info('Fetching event data from previous step')
        bucket = event['body']['bucket']
        keys_to_process = event['body']['keysToProcess']
        team = event['body']['team']
        stage = event['body']['pipeline_stage']
        dataset = event['body']['dataset']
        job_details = event['body']['job']['jobDetails']
        processed_keys_path = event['body']['job']['processedKeysPath']

        logger.info('Initializing Octagon client')
        component = context.function_name.split('-')[-2].title()
        octagon_client = (
            octagon.OctagonClient()
            .with_run_lambda(True)
            .with_configuration_instance(event['body']['env'])
            .build()
        )
        logger.info('Querying manifests control table ')

        items = get_manifest_data(bucket, team, dataset, keys_to_process[0])

        ddb_keys = get_ddb_keys(items)

        dynamo_config = DynamoConfiguration()
        dynamo_interface = DynamoInterface(dynamo_config)
        

        logger.info('Checking Job Status with user custom code')
        transform_handler = TransformHandler().stage_transform(team, dataset, stage)
        response = transform_handler().check_job_status(bucket, keys_to_process,
                                                        processed_keys_path, job_details)  # custom user code called
        response['peh_id'] = event['body']['job']['peh_id']

        if event['body']['job']['jobDetails']['jobStatus'] == 'FAILED':
            peh.PipelineExecutionHistoryAPI(
                octagon_client).retrieve_pipeline_execution(response['peh_id'])
            octagon_client.end_pipeline_execution_failed(component=component,
                                                         issue_comment="{} {} Error: Check Job Logs".format(stage, component))
            for ddb_key in ddb_keys:
                dynamo_interface.update_manifests_control_table_stageb(ddb_key, "FAILED",None,"Glue Job Failed, Check Logs")

    except Exception as e:
        logger.error("Fatal error", exc_info=True)
        peh.PipelineExecutionHistoryAPI(octagon_client).retrieve_pipeline_execution(
            event['body']['job']['peh_id'])
        octagon_client.end_pipeline_execution_failed(component=component,
                                                     issue_comment="{} {} Error: {}".format(stage, component, repr(e)))
        for ddb_key in ddb_keys:
            dynamo_interface.update_manifests_control_table_stageb(
                ddb_key, "FAILED", None, "Glue Job Failed, Check Logs")
        raise e
    return response
