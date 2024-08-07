import json
import logging
import os

import boto3
from boto3.dynamodb.types import TypeSerializer

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.client("dynamodb")
ssm_endpoint_url = "https://ssm." + os.getenv("AWS_REGION") + ".amazonaws.com"
ssm = boto3.client("ssm", endpoint_url=ssm_endpoint_url)


def delete_dynamodb_dataset_entry(table_name, team_name, dataset_name):
    response = dynamodb.delete_item(
        TableName=table_name,
        Key={"name": {"S": f"{team_name}-{dataset_name}"}},
    )
    return response


def create_dynamodb_dataset_entry(table_name, team_name, dataset_name, pipeline_details):
    pipeline_details_dynamodb_json = TypeSerializer().serialize(pipeline_details)
    logger.info("PIPELINE DETAILS DYNAMODB JSON: %s", pipeline_details_dynamodb_json)
    response = dynamodb.update_item(
        TableName=table_name,
        Key={"name": {"S": f"{team_name}-{dataset_name}"}},
        ExpressionAttributeNames={
            "#P": "pipeline",
            "#V": "version",
        },
        ExpressionAttributeValues={
            ":p": pipeline_details_dynamodb_json,
            ":v": {"N": "1"},
        },
        UpdateExpression="SET #P = :p, #V = :v",
        ReturnValues="UPDATED_NEW",
    )
    return response


def lambda_handler(event, context):
    try:
        environment = os.getenv("ENVIRONMENT")
        team_name = os.getenv("TEAM_NAME")
        table = f"octagon-Datasets-{environment}"

        paginator = ssm.get_paginator("get_parameters_by_path")
        datasets_pages = paginator.paginate(Path=f"/SDLF/Datasets/{team_name}")

        for datasets_page in datasets_pages:
            for dataset in datasets_page["Parameters"]:
                dataset_name = dataset["Name"].split("/")[-1]
                logger.info("DATASET SSM CONTENT: %s", dataset["Value"])
                dataset_pipeline_details = json.loads(dataset["Value"])
                create_dynamodb_dataset_entry(table, team_name, dataset_name, dataset_pipeline_details)
                logger.info(f"{team_name}-{dataset_name} DynamoDB Dataset entry created")

        logger.info("INFO: Entries for datasets that no longer exist are not removed from DynamoDB")
    except Exception as e:
        message = "Function exception: " + str(e)
        logger.error(message, exc_info=True)
        raise

    return "Success"
