import json

from datalake_library.commons import init_logger
from datalake_library.configuration.resource_configs import StateMachineConfiguration
from datalake_library.interfaces.states_interface import StatesInterface

logger = init_logger(__name__)


def lambda_handler(event, context):
    try:
        logger.info("Received {} messages".format(len(event["Records"])))
        for record in event["Records"]:
            logger.info("Starting State Machine Execution")
            event_body = json.loads(record["body"])
            state_config = StateMachineConfiguration(
                event_body["team"], event_body["pipeline"], event_body["pipeline_stage"]
            )
            StatesInterface().run_state_machine(state_config.get_stage_state_machine_arn, record["body"])
    except Exception as e:
        logger.error("Fatal error", exc_info=True)
        raise e
    return
