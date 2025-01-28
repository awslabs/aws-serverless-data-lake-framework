import math
import os
import uuid

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from ..commons import init_logger


class SQSInterface:
    def __init__(self, queue_name, log_level=None, sqs_client=None):
        self.log_level = log_level or os.getenv("LOG_LEVEL", "INFO")
        self._logger = init_logger(__name__, self.log_level)
        sqs_endpoint_url = "https://sqs." + os.getenv("AWS_REGION") + ".amazonaws.com"
        session_config = Config(user_agent="awssdlf/2.9.0")
        self._sqs_client = sqs_client or boto3.client("sqs", endpoint_url=sqs_endpoint_url, config=session_config)

        self._message_queue = self._sqs_client.get_queue_url(QueueName=queue_name)["QueueUrl"]

    def receive_messages(self, max_num_messages=1):
        messages = self._sqs_client.receive_message(
            QueueUrl=self._message_queue, MaxNumberOfMessages=max_num_messages, WaitTimeSeconds=1
        )["Messages"]
        for message in messages:
            self._sqs_client.delete_message(QueueUrl=self._message_queue, ReceiptHandle=message["ReceiptHandle"])
        return messages

    def receive_min_max_messages(self, min_items_process, max_items_process):
        """Gets max_items_process messages from an SQS queue.
        :param min_items_process: Minimum number of items to process.
        :param max_items_process: Maximum number of items to process.
        :return messages obtained
        """
        messages = []
        num_messages_queue = int(
            self._sqs_client.get_queue_attributes(
                QueueUrl=self._message_queue, AttributeNames=["ApproximateNumberOfMessages"]
            )["Attributes"]["ApproximateNumberOfMessages"]
        )

        # If not enough items to process, break with no messages
        if (num_messages_queue == 0) or (min_items_process > num_messages_queue):
            self._logger.info("Not enough messages - exiting")
            return messages

        # Only pull batch sizes of max_batch_size
        num_messages_queue = min(num_messages_queue, max_items_process)
        max_batch_size = 10
        batch_sizes = [max_batch_size] * math.floor(num_messages_queue / max_batch_size)
        if num_messages_queue % max_batch_size > 0:
            batch_sizes += [num_messages_queue % max_batch_size]

        for batch_size in batch_sizes:
            resp_msg = self.receive_messages(max_num_messages=batch_size)
            try:
                messages.extend(message["Body"] for message in resp_msg)
            except KeyError:
                break
        return messages

    def send_message_to_fifo_queue(self, message, group_id):
        try:
            self._sqs_client.send_message(
                QueueUrl=self._message_queue,
                MessageBody=message,
                MessageGroupId=group_id,
                MessageDeduplicationId=str(uuid.uuid1()),
            )
        except ClientError as e:
            self._logger.error("Received error: %s", e, exc_info=True)
            raise e

    def send_batch_messages_to_fifo_queue(self, messages, batch_size, group_id):
        try:
            chunks = [messages[x : x + batch_size] for x in range(0, len(messages), batch_size)]
            for chunk in chunks:
                entries = []
                for x in chunk:
                    entry = {
                        "Id": str(uuid.uuid1()),
                        "MessageBody": str(x),
                        "MessageGroupId": group_id,
                        "MessageDeduplicationId": str(uuid.uuid1()),
                    }
                    entries.append(entry)
                self._sqs_client.send_message_batch(QueueUrl=self._message_queue, Entries=entries)
        except ClientError as e:
            self._logger.error("Received error: %s", e, exc_info=True)
            raise e
