import logging
import os

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)
dlq_name = os.environ['DLQ']
queue_name = os.environ['QUEUE']
sqs = boto3.resource('sqs')


def lambda_handler(event, context):
    try:
        dlq_queue = sqs.get_queue_by_name(QueueName=dlq_name)
        queue = sqs.get_queue_by_name(QueueName=queue_name)

        messages = dlq_queue.receive_messages(
            MaxNumberOfMessages=1, WaitTimeSeconds=1)
        if len(messages) == 0 or messages is None:
            logger.info('No messages found in {}'.format(dlq_name))
            return

        logger.info('Received {} messages'.format(len(messages)))
        for message in messages:
            queue.send_message(MessageBody=message.body)
            message.delete()
            logger.info('Delete message succeeded')
    except Exception as e:
        logger.error("Fatal error", exc_info=True)
        raise e
    return
