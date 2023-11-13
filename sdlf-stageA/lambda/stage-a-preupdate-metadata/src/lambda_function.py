import os

from datalake_library import octagon
from datalake_library.commons import init_logger
from datalake_library.configuration.resource_configs import DynamoConfiguration
from datalake_library.interfaces.dynamo_interface import DynamoInterface

logger = init_logger(__name__)


def get_lambda_transform_details(team, dataset, pipeline, stage):
    dynamo_config = DynamoConfiguration()
    dynamo_interface = DynamoInterface(dynamo_config)
    transform_info = dynamo_interface.get_transform_table_item(f"{team}-{dataset}")
    lambda_arn = os.getenv("STAGE_TRANSFORM_LAMBDA")
    logger.info(f"Pipeline is {pipeline}, stage is {stage}")
    if pipeline in transform_info.get("pipeline", {}):
        if stage in transform_info["pipeline"][pipeline]:
            logger.info(f"Details from DynamoDB: {transform_info['pipeline'][pipeline][stage]}")
            lambda_arn = transform_info["pipeline"][pipeline][stage].get("lambda_arn", lambda_arn)
    #######################################################
    # We assume a Lambda function has already been created based on
    # customer needs.
    #######################################################

    return {"lambda_arn": lambda_arn}


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
        team = event["team"]
        pipeline = event["pipeline"]
        stage = event["pipeline_stage"]
        dataset = event["dataset"]

        logger.info("Initializing Octagon client")
        component = context.function_name.split("-")[-2].title()
        octagon_client = octagon.OctagonClient().with_run_lambda(True).with_configuration_instance(event["env"]).build()
        event["peh_id"] = octagon_client.start_pipeline_execution(
            pipeline_name="{}-{}-{}".format(team, pipeline, stage),
            dataset_name="{}-{}".format(team, dataset),
            comment=event,
        )
        # Add business metadata (e.g. event['project'] = 'xyz')

        logger.info("Initializing DynamoDB config and Interface")
        dynamo_config = DynamoConfiguration()
        dynamo_interface = DynamoInterface(dynamo_config)

        logger.info("Storing metadata to DynamoDB")
        dynamo_interface.update_object_metadata_catalog(event)

        logger.info("Passing arguments to the next function of the state machine")
        octagon_client.update_pipeline_execution(
            status="{} {} Processing".format(stage, component), component=component
        )

        event["lambda"] = get_lambda_transform_details(team, dataset, pipeline, stage)  # custom user code called
    except Exception as e:
        logger.error("Fatal error", exc_info=True)
        octagon_client.end_pipeline_execution_failed(
            component=component,
            issue_comment="{} {} Error: {}".format(stage, component, repr(e)),
        )
        raise e
    return {"statusCode": 200, "body": event}
