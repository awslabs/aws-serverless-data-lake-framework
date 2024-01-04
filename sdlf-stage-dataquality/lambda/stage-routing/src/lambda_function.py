import json
import os

from datalake_library.commons import init_logger
from datalake_library.configuration.resource_configs import (
    S3Configuration,
    SQSConfiguration,
    StateMachineConfiguration,
)
from datalake_library.interfaces.sqs_interface import SQSInterface
from datalake_library.interfaces.states_interface import StatesInterface

logger = init_logger(__name__)


def lambda_handler(event, context):
    """Checks if any items need processing and triggers state machine
    Arguments:
        event {dict} -- Dictionary with details on what needs processing
        context {dict} -- Dictionary with details on Lambda context
    """

    try:
        records = event["Records"]
        logger.info(f"Received {len(records)} messages")
        response = {}
        for record in records:
            event_body = json.loads(json.loads(record["body"])["output"])[0]["body"]
            logger.info(event_body)
            team = event_body["team"]
            pipeline = event_body["pipeline"]
            stage = os.environ["PIPELINE_STAGE"]
            dataset = event_body["dataset"]
            org = event_body["org"]
            domain = event_body["domain"]
            env = event_body["env"]
            stage_bucket = S3Configuration().stage_bucket

            response = {
                "statusCode": 200,
                "body": {
                    "bucket": stage_bucket,
                    "team": team,
                    "pipeline": pipeline,
                    "pipeline_stage": stage,
                    "dataset": dataset,
                    "org": org,
                    "domain": domain,
                    "env": env,
                },
            }
        if response:
            logger.info("Starting State Machine Execution")
            state_config = StateMachineConfiguration(team, pipeline, stage)
            StatesInterface().run_state_machine(state_config.get_stage_state_machine_arn, response)
    except Exception as e:
        # If failure send to DLQ
        sqs_config = SQSConfiguration(team, pipeline, stage)
        dlq_interface = SQSInterface(sqs_config.get_stage_dlq_name)
        dlq_interface.send_message_to_fifo_queue(json.dumps(response), "failed")
        logger.error("Fatal error", exc_info=True)
        raise e
