import json
import logging
import os
from datetime import UTC, datetime
from urllib.parse import unquote_plus

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

session_config = Config(user_agent_extra="awssdlf/2.9.0")

logger = logging.getLogger()
logger.setLevel(logging.INFO)
dynamodb = boto3.client("dynamodb", config=session_config)
catalog_table = os.getenv("OBJECTMETADATA_TABLE")


def parse_s3_event(s3_event):
    return {
        "bucket": {"S": s3_event["detail"]["bucket"]["name"]},
        "key": {"S": unquote_plus(s3_event["detail"]["object"]["key"])},
        "size": {"N": str(s3_event["detail"]["object"]["size"])},
        "last_modified_date": {"S": s3_event["time"]},
        "timestamp": {"N": str(int(round(datetime.now(UTC).timestamp() * 1000, 0)))},
    }


def put_item(table, item, key):
    try:
        response = dynamodb.put_item(
            TableName=table,
            Item=item,
            ConditionExpression=f"attribute_not_exists({key})",
        )
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            logger.info(e.response["Error"]["Message"])
        else:
            raise
    else:
        return response


def delete_item(table, key):
    try:
        response = dynamodb.delete_item(TableName=table, Key=key)
    except ClientError as e:
        logger.error("Fatal error", exc_info=True)
        raise e
    else:
        return response


def lambda_handler(event, context):
    try:
        logger.info(f"Received {len(event['Records'])} messages")
        for record in event["Records"]:
            logger.info("Parsing S3 Event")
            message = json.loads(record["body"])
            operation = message["detail-type"]
            bucket = message["detail"]["bucket"]["name"]
            key = unquote_plus(message["detail"]["object"]["key"])
            id = f"s3://{bucket}/{key}"

            logger.info(f"Performing Dynamo {operation} operation")
            if operation in ["Object Deleted"]:
                delete_item(catalog_table, {"id": id})
            else:
                item = parse_s3_event(message)
                item["id"] = {"S": id}
                item["stage"] = {"S": bucket.split("-")[-1]}
                put_item(catalog_table, item, "id")
    except Exception as e:
        logger.error("Fatal error", exc_info=True)
        raise e
