import os

from datalake_library.commons import init_logger
from datalake_library.sdlf import SQSConfiguration
from datalake_library.interfaces.sqs_interface import SQSInterface

logger = init_logger(__name__)
deployment_instance = os.environ["DEPLOYMENT_INSTANCE"]

def lambda_handler(event, context):
    try:
        sqs_config = SQSConfiguration(instance=deployment_instance)
        dlq_interface = SQSInterface(sqs_config.stage_dlq)
        messages = dlq_interface.receive_messages(1)
        if not messages:
            logger.info("No messages found in {}".format(sqs_config.get_stage_dlq_name))
            return

        logger.info("Received {} messages".format(len(messages)))
        queue_interface = SQSInterface(sqs_config.stage_queue)
        for message in messages:
            queue_interface.send_message_to_fifo_queue(message["Body"], "redrive")
            logger.info("Redrive message succeeded")
    except Exception as e:
        logger.error("Fatal error", exc_info=True)
        raise e
    return
