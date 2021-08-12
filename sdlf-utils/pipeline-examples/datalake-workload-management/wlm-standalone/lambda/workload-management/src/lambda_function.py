import json, boto3, datetime
import math
import logging
import os
import urllib.parse
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb_resource = boto3.resource('dynamodb')
ddb = os.environ['ddb']
pipeline_table = dynamodb_resource.Table(ddb)
states_client = boto3.client('stepfunctions')
sns = boto3.client('sns')
s3_resource = boto3.resource('s3')
sqs_resource = boto3.resource('sqs')

STEPFUNCTION = os.environ['STEPFUNCTION']
HIGH = os.environ['HIGH']
LOW = os.environ['LOW']





def receive_max_messages(messages, message_queue, num_messages_queue):
    
    if(num_messages_queue<10): # Make max size as number of message since its less than 10
        max_batch_size = num_messages_queue
    else:
        max_batch_size = 10
        
    logger.info(f"max_batch_size: {max_batch_size}")
        
    batch_sizes = [max_batch_size] * \
        math.floor(num_messages_queue/max_batch_size)
    
    
    if num_messages_queue % max_batch_size > 0:
        batch_sizes += [num_messages_queue % max_batch_size]
    
    logger.info(f"batch_sizes: {batch_sizes}")

    for batch_size in batch_sizes:
        resp_msg = message_queue.receive_messages(
            MaxNumberOfMessages=batch_size)
        try:
            messages.extend(message.body for message in resp_msg)
            for msg in resp_msg:
                msg.delete()
        except KeyError:
            break
    return messages






def json_serial(obj):
    """JSON serializer for objects not serializable by default"""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    raise TypeError("Type %s not serializable" % type(obj))
    
def lambda_handler(event, context):
    try:
        high_message_queue = sqs_resource.get_queue_by_name(QueueName=HIGH,)
        low_message_queue = sqs_resource.get_queue_by_name(QueueName=LOW,)
        max_sfn_executions = 10
        
        #SFN processing code 
        #---------------------------------
        response = states_client.list_executions(
                stateMachineArn=STEPFUNCTION,
                statusFilter='RUNNING',
                maxResults=50,
            )
            
        executions = response["executions"]
        current_sfn_exeuction = len(executions)
        logger.info(f"current_sfn_exeuctions:{current_sfn_exeuction}")
        
        if(current_sfn_exeuction < max_sfn_executions):
            sfn_available_slots = max_sfn_executions - current_sfn_exeuction
            logger.info(f"sfn_available_slots:{sfn_available_slots}")
        else:
            logger.info("No step function slot empty ----- exiting")
            return
        #-----------------------------------
        #-----------------------------------
        
        messages = []
        #Dynamically manging workload from different priority queues
        #------------------------------------
        for message_queue in [high_message_queue, low_message_queue]:  #high=10 #low=30 sfn slots=40
            num_messages_queue = int(
            message_queue.attributes['ApproximateNumberOfMessages'])
            logger.info(f"Number of messages in {message_queue}:{num_messages_queue}")
            if(num_messages_queue == 0):
                logger.info(f"Not enough messages in {message_queue}, trying next prority queue")
            else:
                if(num_messages_queue >= sfn_available_slots): #Example  40>20 12>8 for high priority sqs
                    num_messages_queue = sfn_available_slots
                    
                messages = receive_max_messages(messages, message_queue, num_messages_queue)
                logger.info(f"messages:{messages}")
                sfn_available_slots = sfn_available_slots - num_messages_queue
                logger.info(f"sfn_available_slots:{sfn_available_slots}")
            if(sfn_available_slots==0):
                break
        #-------------------------------------
        #-------------------------------------
        
        
        #Running step function for processed messages
        #--------------------------------------
        if(len(messages)>0):
            for message in messages:
                states_client.start_execution(
                    stateMachineArn=STEPFUNCTION,
                    input=json.dumps(json.loads(message), default=json_serial))
            logger.info(f"{len(messages)} messages sent to step function ")
        else:
            logger.info(f"Not enough messages in any queue --- exiting")
        #----------------------------------------
            
            
    except Exception as e:
        raise e
