import os
import json
import time
import boto3

from datalake_library.commons import init_logger
from datalake_library.configuration.resource_configs import DynamoConfiguration, SQSConfiguration,\
    StateMachineConfiguration, S3Configuration
from datalake_library.interfaces.dynamo_interface import DynamoInterface
from datalake_library.interfaces.sqs_interface import SQSInterface
from datalake_library.interfaces.states_interface import StatesInterface

logger = init_logger(__name__)


def lambda_handler(event, context):
    """Checks if any items need processing and triggers state machine
    Arguments:
        event {dict} -- Dictionary with no relevant details
        context {dict} -- Dictionary with details on Lambda context
    """

    # TODO Implement Redrive Logic (through message_group_id)
    try:
        logger.info('Received recent messages: {} '.format(event))
        for record in event['Records']:
            record_body = json.loads(record['body'])
            team = record_body['team']
            pipeline = record_body['pipeline']
            stage = record_body['pipeline_stage']
            dataset = record_body['dataset']
            org = record_body['org']
            app = record_body['app']
            env = record_body['env']
            dest_table = record_body['dest_table']['name']
            stage_bucket = S3Configuration().stage_bucket
            record_body['bucket'] = stage_bucket
            record_body['keysToProcess'] = record_body['prev_stage_processed_keys']

            response = {
                'statusCode': 200,
                'body': record_body
                }
            precision = 3
            seconds = f'{time.time():.{precision}f}'
            state_machine_name = f'{dataset}-{dest_table}-{seconds}'
            logger.info('Starting State Machine Execution')
            state_config = StateMachineConfiguration(team, pipeline, stage)
            StatesInterface().run_state_machine(
                state_config.get_stage_state_machine_arn, response, state_machine_name)
    except Exception as e:
        # # If failure send to DLQ
        # if keys_to_process:
        #     dlq_interface = SQSInterface(sqs_config.get_stage_dlq_name)
        #     dlq_interface.send_message_to_fifo_queue(
        #         json.dumps(response), 'failed')
        logger.error("Fatal error", exc_info=True)
        raise e
    return
