import math
import os
import uuid

import boto3
from botocore.exceptions import ClientError

from ..commons import init_logger


class SQSInterface:
    def __init__(self, queue_name, log_level=None, sqs_resource=None):
        self.log_level = log_level or os.getenv('LOG_LEVEL', 'INFO')
        self._logger = init_logger(__name__, self.log_level)
        self._sqs_resource = sqs_resource or boto3.resource('sqs')

        self._message_queue = self._sqs_resource.get_queue_by_name(
            QueueName=queue_name)

    def receive_messages(self, max_num_messages=1):
        return self._message_queue.receive_messages(MaxNumberOfMessages=max_num_messages, WaitTimeSeconds=1)

    def receive_min_max_messages(self, min_items_process, max_items_process):
        """Gets max_items_process messages from an SQS queue.
        :param min_items_process: Minimum number of items to process.
        :param max_items_process: Maximum number of items to process.
        :return messages obtained
        """
        messages = []
        num_messages_queue = int(
            self._message_queue.attributes['ApproximateNumberOfMessages'])

        # If not enough items to process, break with no messages
        if (num_messages_queue == 0) or (min_items_process > num_messages_queue):
            self._logger.info("Not enough messages - exiting")
            return messages

        # Only pull batch sizes of max_batch_size
        if num_messages_queue > max_items_process:
            num_messages_queue = max_items_process
        max_batch_size = 10
        batch_sizes = [max_batch_size] * \
            math.floor(num_messages_queue/max_batch_size)
        if num_messages_queue % max_batch_size > 0:
            batch_sizes += [num_messages_queue % max_batch_size]

        for batch_size in batch_sizes:
            resp_msg = self._message_queue.receive_messages(
                MaxNumberOfMessages=batch_size)
            try:
                messages.extend(message.body for message in resp_msg)
                for msg in resp_msg:
                    msg.delete()
            except KeyError:
                break
        return messages

    def send_message_to_fifo_queue(self, message, group_id):
        try:
            self._message_queue.send_message(
                MessageBody=message, MessageGroupId=group_id, MessageDeduplicationId=str(uuid.uuid1()))
        except ClientError as e:
            self._logger.error("Received error: %s", e, exc_info=True)
            raise e

    def send_batch_messages_to_fifo_queue(self, messages, batch_size, group_id):
        try:
            chunks = [messages[x:x + batch_size]
                      for x in range(0, len(messages), batch_size)]
            for chunk in chunks:
                entries = []
                for x in chunk:
                    entry = {
                        'Id': str(uuid.uuid1()),
                        'MessageBody': str(x),
                        'MessageGroupId': group_id,
                        'MessageDeduplicationId': str(uuid.uuid1())
                    }
                    entries.append(entry)
                self._message_queue.send_messages(Entries=entries)
        except ClientError as e:
            self._logger.error("Received error: %s", e, exc_info=True)
            raise e
