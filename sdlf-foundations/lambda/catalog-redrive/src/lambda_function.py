import logging
import os

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)
dlq_name = os.environ["DLQ"]
queue_name = os.environ["QUEUE"]
sqs_endpoint_url = "https://sqs." + os.getenv("AWS_REGION") + ".amazonaws.com"
sqs = boto3.client("sqs", endpoint_url=sqs_endpoint_url)


def lambda_handler(event, context):
    try:
        dlq_queue_url = sqs.get_queue_url(QueueName=dlq_name)["QueueUrl"]
        queue_url = sqs.get_queue_url(QueueName=queue_name)["QueueUrl"]

        messages = sqs.receive_message(QueueUrl=dlq_queue_url, MaxNumberOfMessages=1, WaitTimeSeconds=1)["Messages"]
        if len(messages) == 0 or messages is None:
            logger.info("No messages found in {}".format(dlq_name))
            return

        logger.info("Received {} messages".format(len(messages)))
        for message in messages:
            sqs.send_message(QueueUrl=queue_url, MessageBody=message["Body"])
            sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=message["ReceiptHandle"])
            logger.info("Delete message succeeded")
    except Exception as e:
        logger.error("Fatal error", exc_info=True)
        raise e
    return
