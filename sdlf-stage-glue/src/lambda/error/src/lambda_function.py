import json
import os

from datalake_library.commons import init_logger
from datalake_library.interfaces.sqs_interface import SQSInterface
from datalake_library.sdlf import SQSConfiguration

logger = init_logger(__name__)
deployment_instance = os.environ["DEPLOYMENT_INSTANCE"]


def lambda_handler(event, context):
    try:
        if isinstance(event, str):
            event = json.loads(event)

        sqs_config = SQSConfiguration(instance=deployment_instance)
        sqs_interface = SQSInterface(sqs_config.stage_dlq)

        logger.info("Execution Failed. Sending original payload to DLQ")
        sqs_interface.send_message_to_fifo_queue(json.dumps(event), "failed")
    except Exception as e:
        logger.error("Fatal error", exc_info=True)
        raise e
