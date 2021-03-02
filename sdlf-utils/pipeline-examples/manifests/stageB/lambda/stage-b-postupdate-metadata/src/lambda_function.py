from datalake_library.commons import init_logger
from datalake_library.configuration.resource_configs import DynamoConfiguration, SQSConfiguration, S3Configuration, KMSConfiguration
from datalake_library.interfaces.dynamo_interface import DynamoInterface
from datalake_library.interfaces.s3_interface import S3Interface
from datalake_library.interfaces.sqs_interface import SQSInterface
from datalake_library import octagon
from datalake_library.octagon import Artifact, EventReasonEnum, peh

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
    """Updates the S3 objects metadata catalog

    Arguments:
        event {dict} -- Dictionary with details on Bucket and Keys
        context {dict} -- Dictionary with details on Lambda context

    Returns:
        {dict} -- Dictionary with response
    """
    try:
        logger.info('Fetching event data from previous step')
        bucket = event['body']['bucket']
        processed_keys_path = event['body']['job']['processedKeysPath']
        processed_keys = S3Interface().list_objects(bucket, processed_keys_path)
        team = event['body']['team']
        pipeline = event['body']['pipeline']
        stage = event['body']['pipeline_stage']
        dataset = event['body']['dataset']
        peh_id = event['body']['job']['peh_id']
        keys_to_process = event['body']['keysToProcess']
        s3_path = "post-stage/{}/manifests/{}/{}".format(
            team, dataset, keys_to_process[0].split("/")[-1])

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

        logger.info('Initializing DynamoDB config and Interface')
        dynamo_config = DynamoConfiguration()
        dynamo_interface = DynamoInterface(dynamo_config)

        logger.info('Storing metadata to DynamoDB')
        for key in processed_keys:
            object_metadata = {
                'bucket': bucket,
                'key': key,
                'size': S3Interface().get_size(bucket, key),
                'last_modified_date': S3Interface().get_last_modified(bucket, key),
                'org': event['body']['org'],
                'app': event['body']['app'],
                'env': event['body']['env'],
                'team': team,
                'pipeline': pipeline,
                'dataset': dataset,
                'stage': 'stage',
                'pipeline_stage': stage,
                'peh_id': peh_id
            }
            dynamo_interface.update_object_metadata_catalog(object_metadata)
        
        logger.info("Updating manifests control table")
        items = get_manifest_data(bucket, team, dataset, keys_to_process[0])
        ddb_keys = get_ddb_keys(items)

        for ddb_key in ddb_keys:
            dynamo_interface.update_manifests_control_table_stageb(
                ddb_key, "COMPLETED")
        

        logger.info("Move manifest file to post stage")
        kms_key = KMSConfiguration(team).get_kms_arn
        s3_interface = S3Interface()
        s3_interface.copy_object(
            bucket, keys_to_process[0], bucket, s3_path, kms_key=kms_key)
        
        logger.info("Removing manifest file from pre-stage")

        s3_interface.delete_objects(bucket, keys_to_process[0])



        # Only uncomment if a queue for the next stage exists
        # logger.info('Sending messages to next SQS queue if it exists')
        # sqs_config = SQSConfiguration(team, dataset, ''.join([stage[:-1], chr(ord(stage[-1]) + 1)]))
        # sqs_interface = SQSInterface(sqs_config.get_stage_queue_name)
        # sqs_interface.send_batch_messages_to_fifo_queue(processed_keys, 10, '{}-{}'.format(team, dataset))

        octagon_client.update_pipeline_execution(
            status="{} {} Processing".format(stage, component), component=component)
        octagon_client.end_pipeline_execution_success()
    except Exception as e:
        logger.error("Fatal error", exc_info=True)
        octagon_client.end_pipeline_execution_failed(component=component,
                                                     issue_comment="{} {} Error: {}".format(stage, component, repr(e)))
        for ddb_key in ddb_keys:
            dynamo_interface.update_manifests_control_table_stageb(
                ddb_key, "FAILED",None, "Failed in Post Update")
        raise e
    return 200
