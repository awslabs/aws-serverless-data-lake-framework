import json
import os

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
            object_key = event_body["object"]["key"].split("/")
            team = object_key[0]
            dataset = object_key[1]
            pipeline = os.environ["PIPELINE"]
            pipeline_stage = os.environ["PIPELINE_STAGE"]
            org = os.environ["ORG"]
            domain = os.environ["DOMAIN"]
            env = os.environ["ENV"]

            event_with_pipeline_details = {
                **event_body["object"],
                "bucket": event_body["bucket"]["name"],
                "team": team,
                "dataset": dataset,
                "pipeline": pipeline,
                "pipeline_stage": pipeline_stage,
                "org": org,
                "domain": domain,
                "env": env,
            }

            state_config = StateMachineConfiguration(team, pipeline, pipeline_stage)
            StatesInterface().run_state_machine(
                state_config.get_stage_state_machine_arn, json.dumps(event_with_pipeline_details)
            )
    except Exception as e:
        logger.error("Fatal error", exc_info=True)
        raise e
