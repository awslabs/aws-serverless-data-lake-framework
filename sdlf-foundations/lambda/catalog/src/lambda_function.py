import json
import logging
import os
from datetime import datetime
from urllib.parse import unquote_plus

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)
sqs = boto3.resource("sqs")
dynamodb = boto3.resource("dynamodb")
catalog_table = dynamodb.Table(f"octagon-ObjectMetadata-{os.environ['ENV']}")


def parse_s3_event(s3_event):
    return {
        "bucket": s3_event["s3"]["bucket"]["name"],
        "key": unquote_plus(s3_event["s3"]["object"]["key"]),
        "size": s3_event["s3"]["object"]["size"],
        "last_modified_date": s3_event["eventTime"].split(".")[0] + "+00:00",
        "timestamp": int(round(datetime.utcnow().timestamp() * 1000, 0)),
    }


def put_item(table, item, key):
    try:
        response = table.put_item(
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
        response = table.delete_item(Key=key)
    except ClientError as e:
        logger.error("Fatal error", exc_info=True)
        raise e
    else:
        return response


def lambda_handler(event, context):
    try:
        logger.info("Received {} messages".format(len(event["Records"])))
        for record in event["Records"]:
            logger.info("Parsing S3 Event")
            # Handling S3 Multipart Upload
            message = json.loads(record["body"])["Records"][0] if "eventName" not in event else record
            operation = message["eventName"].split(":")[-1]

            logger.info(f"Performing Dynamo {operation} operation")
            if operation in ["Delete", "DeleteMarkerCreated"]:
                id = "s3://{}/{}".format(message["s3"]["bucket"]["name"], unquote_plus(message["s3"]["object"]["key"]))
                delete_item(catalog_table, {"id": id})
            else:
                item = parse_s3_event(message)
                item["id"] = f"s3://{item['bucket']}/{item['key']}"
                if os.environ["NUM_BUCKETS"] == "1":
                    item["stage"] = item["key"].split("/")[0]
                else:
                    item["stage"] = item["bucket"].split("-")[-1]
                put_item(catalog_table, item, "id")

                if item["stage"] == "raw":
                    logger.info("Sending event to routing queue to process")
                    queue = sqs.get_queue_by_name(QueueName=os.environ["ROUTING_QUEUE"])
                    queue.send_message(MessageBody=json.dumps(message))
    except Exception as e:
        logger.error("Fatal error", exc_info=True)
        raise e
    return
