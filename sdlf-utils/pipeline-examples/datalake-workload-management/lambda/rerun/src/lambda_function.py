import json, boto3, datetime
import logging
import os
import urllib.parse
from botocore.exceptions import ClientError
import uuid

logger = logging.getLogger()
logger.setLevel(logging.INFO)


HIGH = os.environ['HIGH']
LOW = os.environ['LOW']
ddb = os.environ['ddb'] 

dynamodb_resource = boto3.resource('dynamodb')
pipeline_table = dynamodb_resource.Table(ddb)
sqs_resource = boto3.resource('sqs')
           
def get_item(table, key):
    try:
        item = table.get_item(Key={"name":key}, ConsistentRead=True)['Item']
    except ClientError:
        msg = 'Error getting item from {} table'.format(table)
        logger.exception(msg)
        raise
    return item

def send_message_to_fifo_queue(queue_name, message, group_id):
    try:
        queue_name.send_message(MessageBody=json.dumps(message, indent=4), MessageGroupId=group_id, MessageDeduplicationId=str(uuid.uuid1()))
    except ClientError as e:
        logger.error("Received error: %s", e, exc_info=True)
        raise e
             
def lambda_handler(event, context):
    try:
        high_message_queue = sqs_resource.get_queue_by_name(QueueName=HIGH,)
        low_message_queue = sqs_resource.get_queue_by_name(QueueName=LOW,)
        sfn_event = event
        
        source = sfn_event["body"]["source"]
        dataset = sfn_event["body"]["dataset"]

        pipeline_name=f"{source.upper()}-{dataset.upper()}"

        logger.info("pipeline_table={}".format(pipeline_table))
        logger.info(f"pipeline_name={pipeline_name}")
        
        items = get_item(pipeline_table, pipeline_name)
        
        logger.info("ddb_items={}".format(items))
        
        priority = items["priority"]
        
        logger.info("priority={}".format(priority))
        
        if(priority == "HIGH"):
            queue_name=high_message_queue
        else:
            queue_name=low_message_queue
            
        logger.info("queue_name={}".format(queue_name))
            
        send_message_to_fifo_queue(queue_name, sfn_event, source)
        
        logger.info(f"sfn_event:{sfn_event}")
        
        logger.info("lambda Completed")
                
        return {
            'statusCode': 200
        }

    except Exception as e:
        raise e
        