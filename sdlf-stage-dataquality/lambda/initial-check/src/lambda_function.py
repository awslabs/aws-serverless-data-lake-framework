import copy
import os

import boto3
from datalake_library.commons import init_logger
from datalake_library.configuration.resource_configs import DynamoConfiguration
from datalake_library.interfaces.dynamo_interface import DynamoInterface

logger = init_logger(__name__)

dynamodb = boto3.client("dynamodb")
ssm_endpoint_url = "https://ssm." + os.getenv("AWS_REGION") + ".amazonaws.com"
ssm = boto3.client("ssm", endpoint_url=ssm_endpoint_url)
glue_endpoint_url = "https://glue." + os.getenv("AWS_REGION") + ".amazonaws.com"
glue = boto3.client("glue", endpoint_url=glue_endpoint_url)


def get_glue_transform_details(bucket, team, dataset, env, pipeline, stage):
    dynamo_config = DynamoConfiguration()
    dynamo_interface = DynamoInterface(dynamo_config)

    transform_info = dynamo_interface.get_transform_table_item(f"{team}-{dataset}")

    glue_database = ssm.get_parameter(Name=f"/SDLF/Glue/{team}/{dataset}/DataCatalog")["Parameter"]["Value"]
    glue_capacity = {"NumberOfWorkers": 5}
    wait_time = 45

    dataquality_tables = []

    logger.info(f"Pipeline is {pipeline}, stage is {stage}")
    if pipeline in transform_info.get("pipeline", {}):
        if stage in transform_info["pipeline"][pipeline]:
            logger.info(f"Details from DynamoDB: {transform_info['pipeline'][pipeline][stage]}")
            glue_capacity = transform_info["pipeline"][pipeline][stage].get("glue_capacity", glue_capacity)
            wait_time = transform_info["pipeline"][pipeline][stage].get("wait_time", wait_time)
            dataquality_tables = transform_info["pipeline"][pipeline][stage].get(
                "dataquality_tables", dataquality_tables
            )

    return {
        "DatabaseName": glue_database,
        "wait_time": wait_time,
        "dataquality_tables": dataquality_tables,
        **glue_capacity,
    }


def lambda_handler(event, context):
    """Calls custom transform developed by user

    Arguments:
        event {dict} -- Dictionary with details on previous processing step
        context {dict} -- Dictionary with details on Lambda context

    Returns:
        {dict} -- Dictionary with Data Quality Job details
    """
    try:
        logger.info("Fetching event data from previous step")
        bucket = event["body"]["bucket"]
        team = event["body"]["team"]
        pipeline = event["body"]["pipeline"]
        stage = event["body"]["pipeline_stage"]
        dataset = event["body"]["dataset"]
        env = event["body"]["env"]

        # Checking if Data Quality is enabled on tables
        logger.info("Querying data quality enabled tables")
        event["body"]["glue"] = get_glue_transform_details(bucket, team, dataset, env, pipeline, stage)
        event["body"]["glue"]["crawler_name"] = "-".join(["sdlf", team, dataset, "post-stage-crawler"])
        logger.info(event["body"]["glue"])

        map_input = []
        for table in event["body"]["glue"]["dataquality_tables"]:
            map_item = copy.deepcopy(event)
            map_item["body"]["glue"]["TableName"] = table
            map_input.append(map_item)

    except Exception as e:
        logger.error("Fatal error", exc_info=True)
        raise e
    return {"dataquality": map_input}
