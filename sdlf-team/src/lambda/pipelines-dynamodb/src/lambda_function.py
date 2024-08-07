import logging
import os

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.client("dynamodb")
ssm_endpoint_url = "https://ssm." + os.getenv("AWS_REGION") + ".amazonaws.com"
ssm = boto3.client("ssm", endpoint_url=ssm_endpoint_url)


def delete_dynamodb_pipeline_entry(table_name, team_name, pipeline_name, stage_name):
    response = dynamodb.delete_item(
        TableName=table_name,
        Key={"name": {"S": f"{team_name}-{pipeline_name}-{stage_name}"}},
    )
    return response


def create_dynamodb_pipeline_entry(table_name, team_name, pipeline_name, stage_name):
    response = dynamodb.update_item(
        TableName=table_name,
        Key={"name": {"S": f"{team_name}-{pipeline_name}-{stage_name}"}},
        ExpressionAttributeNames={
            "#T": "type",
            "#S": "status",
            "#P": "pipeline",
            "#V": "version",
        },
        ExpressionAttributeValues={
            ":t": {
                "S": "TRANSFORMATION",
            },
            ":s": {"S": "ACTIVE"},
            ":p": {"M": {"max_items_process": {"N": "100"}, "min_items_process": {"N": "1"}}},
            ":v": {"N": "1"},
        },
        UpdateExpression="SET #T = :t, #S = :s, #P = :p, #V = :v",
        ReturnValues="UPDATED_NEW",
    )
    return response


def lambda_handler(event, context):
    try:
        environment = os.getenv("ENVIRONMENT")
        team_name = os.getenv("TEAM_NAME")
        table = f"octagon-Pipelines-{environment}"

        paginator = ssm.get_paginator("get_parameters_by_path")
        stages_pages = paginator.paginate(
            Path=f"/SDLF/Pipelines/{team_name}",
            Recursive=True,
        )
        for stages_page in stages_pages:
            for stage in stages_page["Parameters"]:
                pipeline_name = stage["Name"].split("/")[-2]
                stage_name = stage["Name"].split("/")[-1]
                create_dynamodb_pipeline_entry(table, team_name, pipeline_name, stage_name)
                logger.info(f"{team_name}-{pipeline_name}-{stage_name} DynamoDB Pipeline entry created")

        logger.info("INFO: Entries for stages that no longer exist are *not* removed from DynamoDB")
    except Exception as e:
        message = "Function exception: " + str(e)
        logger.error(message, exc_info=True)
        raise

    return "Success"
