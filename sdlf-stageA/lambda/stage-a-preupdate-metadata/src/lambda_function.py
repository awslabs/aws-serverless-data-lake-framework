import json

from datalake_library import octagon
from datalake_library.commons import init_logger
from datalake_library.configuration.resource_configs import DynamoConfiguration
from datalake_library.interfaces.dynamo_interface import DynamoInterface

logger = init_logger(__name__)


def lambda_handler(event, context):
    """Updates the objects metadata catalog

    Arguments:
        event {dict} -- Dictionary with details on S3 event
        context {dict} -- Dictionary with details on Lambda context

    Returns:
        {dict} -- Dictionary with Processed Bucket and Key
    """
    try:
        logger.info("Fetching event data from previous step")
        object_metadata = json.loads(event)
        stage = object_metadata["pipeline_stage"]

        logger.info("Initializing Octagon client")
        component = context.function_name.split("-")[-2].title()
        octagon_client = (
            octagon.OctagonClient().with_run_lambda(True).with_configuration_instance(object_metadata["env"]).build()
        )
        object_metadata["peh_id"] = octagon_client.start_pipeline_execution(
            pipeline_name="{}-{}-stage-{}".format(
                object_metadata["team"], object_metadata["pipeline"], stage[-1].lower()
            ),
            dataset_name="{}-{}".format(object_metadata["team"], object_metadata["dataset"]),
            comment=event,
        )
        # Add business metadata (e.g. object_metadata['project'] = 'xyz')

        logger.info("Initializing DynamoDB config and Interface")
        dynamo_config = DynamoConfiguration()
        dynamo_interface = DynamoInterface(dynamo_config)

        logger.info("Storing metadata to DynamoDB")
        dynamo_interface.update_object_metadata_catalog(object_metadata)

        logger.info("Passing arguments to the next function of the state machine")
        octagon_client.update_pipeline_execution(
            status="{} {} Processing".format(stage, component), component=component
        )
    except Exception as e:
        logger.error("Fatal error", exc_info=True)
        octagon_client.end_pipeline_execution_failed(
            component=component, issue_comment="{} {} Error: {}".format(stage, component, repr(e))
        )
        raise e
    return {"statusCode": 200, "body": object_metadata}
