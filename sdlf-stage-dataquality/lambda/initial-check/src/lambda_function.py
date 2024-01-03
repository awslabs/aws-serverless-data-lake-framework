import datetime as dt
import json
import logging
import time
import os

import boto3

from datalake_library import octagon
from datalake_library.commons import init_logger
from datalake_library.configuration.resource_configs import DynamoConfiguration
from datalake_library.interfaces.dynamo_interface import DynamoInterface

logger = init_logger(__name__)

dynamodb = boto3.client("dynamodb")
ssm_endpoint_url = "https://ssm." + os.getenv("AWS_REGION") + ".amazonaws.com"
ssm = boto3.client("ssm", endpoint_url=ssm_endpoint_url)
glue_endpoint_url = "https://glue." + os.getenv("AWS_REGION") + ".amazonaws.com"
glue = boto3.client("glue", endpoint_url=glue_endpoint_url)


def get_dataquality_enabled_tables(team, dataset, env, tables):
    schemas_table = f"octagon-DataSchemas-{env}"
    dataquality_tables = []
    for table in tables:
        table_item = dynamodb.get_item(TableName=schemas_table, Key={"name": f"{team}-{dataset}-{table}"})
        logger.info(table_item)
        if "Item" not in table_item:
            # In case replication Lambda is in the process of writing the item
            time.sleep(180)
            table_item = dynamodb.get_item(TableName=schemas_table, Key={"name": f"{team}-{dataset}-{table}"})

        if table_item["Item"]["data_quality_enabled"] == "Y":
            dataquality_tables.append(table)

    return dataquality_tables

def get_glue_transform_details(bucket, team, dataset, env, pipeline, stage, glue_tables):
    dynamo_config = DynamoConfiguration()
    dynamo_interface = DynamoInterface(dynamo_config)

    transform_info = dynamo_interface.get_transform_table_item(f"{team}-{dataset}")
    suggestions_table = f"octagon-DataQualitySuggestions-{env}"

    suggestions_job_name = f"sdlf-{team}-{dataset}-data-quality-suggestions"
    verification_job_name = f"sdlf-{team}-{dataset}-data-quality-verification"
    glue_database = ssm.get_parameter(Name=f"/SDLF/Glue/{team}/{dataset}/DataCatalog")["Parameter"]["Value"]
    glue_capacity = {"WorkerType": "G.1X", "NumberOfWorkers": 10}
    glue_suggestions_arguments = glue_verification_arguments = {
        "--team": team,
        "--dataset": dataset,
        "--glueDatabase": glue_database,
        "--glueTables": "",
    }

    suggestions_tables = []
    verification_tables = []
    for table in glue_tables:
        suggestions_item = dynamodb.query(TableName=suggestions_table, IndexName="table-index", KeyConditionExpression=Key("table_hash_key").eq(f"{team}-{dataset}-{table}"))["Items"]
        if suggestions_item:
            verification_tables.append(table)
        else:
            suggestions_tables.append(table)

    if suggestions_tables:
        glue_suggestions_arguments["--glueTables"] = ",".join(suggestions_tables)

    if verification_tables:
        glue_verification_arguments["--glueTables"] = ",".join(verification_tables)

    logger.info(f"Pipeline is {pipeline}, stage is {stage}")
    if pipeline in transform_info.get("pipeline", {}):
        if stage in transform_info["pipeline"][pipeline]:
            logger.info(f"Details from DynamoDB: {transform_info['pipeline'][pipeline][stage]}")
            suggestions_job_name = transform_info["pipeline"][pipeline][stage].get("suggestions_job_name", suggestions_job_name)
            verification_job_name = transform_info["pipeline"][pipeline][stage].get("verification_job_name", verification_job_name)
            glue_capacity = transform_info["pipeline"][pipeline][stage].get("glue_capacity", glue_capacity)
            glue_suggestions_arguments |= transform_info["pipeline"][pipeline][stage].get("glue_extra_arguments", {})
            glue_verification_arguments |= transform_info["pipeline"][pipeline][stage].get("glue_extra_arguments", {})

    return {"suggestions_job_name": suggestions_job_name, "verification_job_name": verification_job_name,
            "suggestions_arguments": glue_suggestions_arguments,
            "verification_arguments": glue_verification_arguments,
            **glue_capacity}


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
        tables = event["body"]["job"]["jobDetails"]["tables"]
        env = event["body"]["env"]

        # Checking if Data Quality is enabled on tables
        logger.info("Querying data quality enabled tables")
        dataquality_tables = get_dataquality_enabled_tables(team, dataset, env, tables)
        logger.info(dataquality_tables)
        event["body"]["glue"] = get_glue_transform_details(bucket, team, dataset, env, pipeline, stage)
        event["body"]["glue"]["crawler_name"] = "-".join(["sdlf", team, dataset, "post-stage-crawler"])
        logger.info(event["body"]["glue"])

    except Exception as e:
        logger.error("Fatal error", exc_info=True)
        raise e
    return event