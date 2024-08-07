import json
import os

from datalake_library.commons import init_logger
from datalake_library.configuration.resource_configs import SQSConfiguration
from datalake_library.interfaces.sqs_interface import SQSInterface

logger = init_logger(__name__)
team = os.environ["TEAM"]
dataset = os.environ["DATASET"]
pipeline = os.environ["PIPELINE"]
pipeline_stage = os.environ["PIPELINE_STAGE"]
org = os.environ["ORG"]
domain = os.environ["DOMAIN"]
env = os.environ["ENV"]


def lambda_handler(event, context):
    try:
        if isinstance(event, str):
            event = json.loads(event)

        sqs_config = SQSConfiguration(team, pipeline, pipeline_stage)
        sqs_interface = SQSInterface(sqs_config.get_stage_dlq_name)

        logger.info("Execution Failed. Sending original payload to DLQ")
        sqs_interface.send_message_to_fifo_queue(json.dumps(event), "failed")
    except Exception as e:
        logger.error("Fatal error", exc_info=True)
        raise e
