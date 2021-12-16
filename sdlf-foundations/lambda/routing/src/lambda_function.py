import os
import json
from datetime import datetime
import logging
import uuid
from urllib.parse import unquote_plus

import boto3
from boto3.dynamodb.conditions import Key, Attr
from botocore.exceptions import ClientError
from botocore.config import Config

session_config = Config(user_agent_extra="awssdlf/1.0.0")

logger = logging.getLogger()
logger.setLevel(logging.INFO)
sqs = boto3.resource('sqs', config=session_config)
dynamodb = boto3.resource("dynamodb", config=session_config)
dataset_table = dynamodb.Table('octagon-Datasets-{}'.format(os.environ['ENV']))


def parse_s3_event(s3_event):
    return {
        'bucket': s3_event['s3']['bucket']['name'],
        'key': unquote_plus(s3_event['s3']['object']['key']),
        'size': s3_event['s3']['object']['size'],
        'last_modified_date': s3_event['eventTime'].split('.')[0]+'+00:00',
        'timestamp': int(round(datetime.utcnow().timestamp()*1000, 0)),
        'stage': 'raw'
    }


def get_item(table, team, dataset):
    try:
        response = table.get_item(
            Key={
                'name': '{}-{}'.format(team, dataset)
            }
        )
    except ClientError as e:
        print(e.response['Error']['Message'])
    else:
        item = response['Item']
        return item['pipeline']


def lambda_handler(event, context):
    try:
        logger.info('Received {} messages'.format(len(event['Records'])))
        for record in event['Records']:
            logger.info('Parsing S3 Event')
            message = parse_s3_event(json.loads(record['body']))

            if os.environ['NUM_BUCKETS'] == '1':
                team = message['key'].split('/')[1]
                dataset = message['key'].split('/')[2]
            else:
                team = message['key'].split('/')[0]
                dataset = message['key'].split('/')[1]
            message['team'] = team
            message['dataset'] = dataset
            pipeline = get_item(dataset_table, team, dataset)
            message['pipeline'] = pipeline
            message['org'] = os.environ['ORG']
            message['app'] = os.environ['APP']
            message['env'] = os.environ['ENV']
            message['pipeline_stage'] = 'StageA'

            logger.info(
                'Sending event to {}-{} pipeline queue for processing'.format(team, pipeline))
            queue = sqs.get_queue_by_name(QueueName='sdlf-{}-{}-queue-a.fifo'.format(
                team,
                pipeline
            ))
            queue.send_message(MessageBody=json.dumps(
                message), MessageGroupId='{}-{}'.format(team, dataset),
                MessageDeduplicationId=str(uuid.uuid1()))
    except Exception as e:
        logger.error("Fatal error", exc_info=True)
        raise e
    return
