import json
import time

from datalake_library.commons import init_logger
from datalake_library.configuration.resource_configs import StateMachineConfiguration
from datalake_library.interfaces.states_interface import StatesInterface

logger = init_logger(__name__)


def lambda_handler(event, context):
    try:
        logger.info('Received {} messages'.format(len(event['Records'])))
        for record in event['Records']:
            logger.info('Starting State Machine Execution')
            event_body = json.loads(record['body'])
            key = event_body['key']
            database = key.split('/')[1]
            filename = key.split('/')[-1]
            num_folders = key.count('/')  # counts number of folders
            sqoop_db = ["database1", "database2", "database3"]
            if (database in sqoop_db) and (filename != '_SUCCESS'):
                continue
            state_config = StateMachineConfiguration(event_body['team'],
                                                     event_body['pipeline'],
                                                     event_body['pipeline_stage'])
            # if it has table name at position #2
            if num_folders > 2:
                precision = 3
                seconds = f'{time.time():.{precision}f}'
                table_name = key.split('/')[2]  # take third folder + rand suffix
                dataset = key.split('/')[1]
                state_machine_name = f'{dataset}-{table_name}-{seconds}'
                StatesInterface().run_state_machine(
                    state_config.get_stage_state_machine_arn, record['body'], state_machine_name)
            else:
                StatesInterface().run_state_machine(
                    state_config.get_stage_state_machine_arn, record['body'])
    except Exception as e:
        logger.error("Fatal error", exc_info=True)
        raise e
    return
