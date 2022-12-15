import json
import os

from datalake_library.commons import init_logger
from datalake_library.configuration.resource_configs import SQSConfiguration, StateMachineConfiguration
from datalake_library.interfaces.sqs_interface import SQSInterface
from datalake_library.interfaces.states_interface import StatesInterface

logger = init_logger(__name__)


def lambda_handler(event, context):
    try:
        team = os.environ['TEAM']
        pipeline = os.environ['PIPELINE']
        dataset = event['dataset']
        stage = os.environ['STAGE']
        state_config = StateMachineConfiguration(team, pipeline, stage)
        sqs_config = SQSConfiguration(team, dataset, stage)
        dlq_interface = SQSInterface(sqs_config.get_stage_dlq_name)

        messages = dlq_interface.receive_messages(1)
        if not messages:
            logger.info('No messages found in {}'.format(
                sqs_config.get_stage_dlq_name))
            return

        logger.info('Received {} messages'.format(len(messages)))
        for message in messages:
            logger.info('Starting State Machine Execution')
            if isinstance(message.body, str):
                response = json.loads(message.body)
            StatesInterface().run_state_machine(
                state_config.get_stage_state_machine_arn, response)
            message.delete()
            logger.info('Delete message succeeded')
    except Exception as e:
        logger.error("Fatal error", exc_info=True)
        raise e
    return
