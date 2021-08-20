import json, boto3, datetime
import os
import urllib.parse
from botocore.exceptions import ClientError
import uuid
from datalake_library.commons import init_logger
from datalake_library.configuration.resource_configs import DynamoConfiguration, SQSConfiguration, S3Configuration
from datalake_library.interfaces.dynamo_interface import DynamoInterface
from datalake_library.interfaces.sqs_interface import SQSInterface
from datalake_library.interfaces.s3_interface import S3Interface
from datalake_library import octagon
from datalake_library.octagon import Artifact, EventReasonEnum, peh

logger = init_logger(__name__)

             
def lambda_handler(event, context):
    try:
        logger.info('Fetching event data from previous step')
        processed_keys = event['body']['keysToProcess']
        team = event['body']['team']
        pipeline = event['body']['pipeline']
        stage = event['body']['pipeline_stage']
        dataset = event['body']['dataset']
        bucket = event['body']['bucket']

        logger.info('Initializing DynamoDB config and Interface')
        dynamo_config = DynamoConfiguration()
        dynamo_interface = DynamoInterface(dynamo_config)

        wlm_ddb_table = dynamo_interface.wlm_control_table
        item = dynamo_interface.get_item(wlm_ddb_table, {"name":"{}-{}-{}".format(team, dataset,processed_keys[0].split("/")[-2])})
        priority = item.get('priority', None)
        print(priority)
        
        print(''.join(
            [stage[:-1], chr(ord(stage[-1]))]))
        logger.info('Sending messages to right priority SQS queue')
        sqs_config = SQSConfiguration(team, dataset, ''.join(
            [stage[:-1], chr(ord(stage[-1]))]), priority) #Workload management changes
        sqs_interface = SQSInterface(sqs_config.get_stage_queue_name_wlm) #Workload management changes
        sqs_interface.send_message_to_fifo_queue(json.dumps(event), '{}-{}'.format(team, dataset))

        
        logger.info("lambda Completed")
                
        return {
            'statusCode': 200
        }

    except Exception as e:
        raise e
        