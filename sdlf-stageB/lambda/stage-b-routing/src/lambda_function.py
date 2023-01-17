import json
import os

from datalake_library.commons import init_logger
from datalake_library.configuration.resource_configs import S3Configuration, SQSConfiguration, StateMachineConfiguration
from datalake_library.interfaces.sqs_interface import SQSInterface
from datalake_library.interfaces.states_interface import StatesInterface

logger = init_logger(__name__)


def fetch_messages(team, pipeline, stage):
    keys_to_process = []

    sqs_config = SQSConfiguration(team, pipeline, stage)
    queue_interface = SQSInterface(sqs_config.get_stage_queue_name)
    min_items_to_process = 1
    max_items_to_process = 100  # TODO implement this at the pipeline level
    logger.info("Querying {}-{}-{} objects waiting for processing".format(team, pipeline, stage))
    keys_to_process = queue_interface.receive_min_max_messages(min_items_to_process, max_items_to_process)

    logger.info("{} Objects ready for processing".format(len(keys_to_process)))
    keys_to_process = list(set(keys_to_process))

    return keys_to_process


def lambda_handler(event, context):
    """Checks if any items need processing and triggers state machine
    Arguments:
        event {dict} -- Dictionary with details on what needs processing
        context {dict} -- Dictionary with details on Lambda context
    """

    # TODO Implement Redrive Logic (through message_group_id)
    try:
        keys_to_process = []
        trigger_type = event.get("trigger_type")  # this is set by the schedule event rule
        if trigger_type:
            records = fetch_messages(event["team"], event["pipeline"], event["pipeline_stage"])
        else:
            records = event["Records"]
        logger.info("Received {} messages".format(len(records)))
        for record in records:
            if trigger_type:
                event_body = json.loads(json.loads(record)["output"])[0]["body"]
            else:
                event_body = json.loads(json.loads(record["body"])["output"])[0]["body"]

            team = event_body["team"]
            pipeline = event_body["pipeline"]
            stage = os.environ["PIPELINE_STAGE"]
            dataset = event_body["dataset"]
            org = event_body["org"]
            app = event_body["app"]
            env = event_body["env"]
            stage_bucket = S3Configuration().stage_bucket
            keys_to_process = event_body["processedKeys"]

            logger.info("{} Objects ready for processing".format(len(keys_to_process)))
            keys_to_process = list(set(keys_to_process))

            response = {
                "statusCode": 200,
                "body": {
                    "bucket": stage_bucket,
                    "keysToProcess": keys_to_process,
                    "team": team,
                    "pipeline": pipeline,
                    "pipeline_stage": stage,
                    "dataset": dataset,
                    "org": org,
                    "app": app,
                    "env": env,
                },
            }
            logger.info("Starting State Machine Execution")
            state_config = StateMachineConfiguration(team, pipeline, stage)
            StatesInterface().run_state_machine(state_config.get_stage_state_machine_arn, response)
    except Exception as e:
        # If failure send to DLQ
        if keys_to_process:
            sqs_config = SQSConfiguration(team, pipeline, stage)
            dlq_interface = SQSInterface(sqs_config.get_stage_dlq_name)
            dlq_interface.send_message_to_fifo_queue(json.dumps(response), "failed")
        logger.error("Fatal error", exc_info=True)
        raise e
    return
