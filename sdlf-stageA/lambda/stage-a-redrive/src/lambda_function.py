import os

from datalake_library.commons import init_logger
from datalake_library.configuration.resource_configs import SQSConfiguration
from datalake_library.interfaces.sqs_interface import SQSInterface

logger = init_logger(__name__)


def lambda_handler(event, context):
    try:
        sqs_config = SQSConfiguration(os.environ["TEAM"], os.environ["PIPELINE"], os.environ["STAGE"])
        dlq_interface = SQSInterface(sqs_config.get_stage_dlq_name)
        messages = dlq_interface.receive_messages(1)
        if not messages:
            logger.info("No messages found in {}".format(sqs_config.get_stage_dlq_name))
            return

        logger.info("Received {} messages".format(len(messages)))
        queue_interface = SQSInterface(sqs_config.get_stage_queue_name)
        for message in messages:
            queue_interface.send_message_to_fifo_queue(message.body, "redrive")
            message.delete()
            logger.info("Delete message succeeded")
    except Exception as e:
        logger.error("Fatal error", exc_info=True)
        raise e
    return
