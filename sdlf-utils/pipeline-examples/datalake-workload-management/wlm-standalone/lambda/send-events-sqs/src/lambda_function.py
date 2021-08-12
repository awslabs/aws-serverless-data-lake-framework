import json, boto3, datetime
import logging
import os
import urllib.parse
from botocore.exceptions import ClientError
import uuid
import random

logger = logging.getLogger()
logger.setLevel(logging.INFO)

sns = boto3.client('sns')
s3_resource = boto3.resource('s3')
dynamodb_resource = boto3.resource('dynamodb')
ddb = os.environ['ddb']
pipeline_table = dynamodb_resource.Table(ddb)
sqs_resource = boto3.resource('sqs')

HIGH = os.environ['HIGH']
LOW = os.environ['LOW']




           
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
            
def list_s3_obj(src_bucket_object, prefix, exclusion):
    list_objects = []
    for obj in src_bucket_object.objects.filter(Prefix=prefix):
        if("$folder$" not in obj.key and obj.key != prefix and ".trigger" not in obj.key):
            if(exclusion == 0):
                list_objects.append(obj.key)
            if(exclusion ==1):
                key = obj.key
                key = "/".join(key.split("/")[0:-1])
                list_objects.append(key)
    
    if(exclusion ==1):
        return list(set(list_objects))
           
    return list_objects
 
def json_serial(obj):
    """JSON serializer for objects not serializable by default"""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    raise TypeError("Type %s not serializable" % type(obj))
  
def lambda_handler(event, context):
    try:
        logger.info("lambda got event: {}".format(event))
        component = context.function_name
        logger.info("{} lambda Started".format(component))

        high_message_queue = sqs_resource.get_queue_by_name(QueueName=HIGH,)
        low_message_queue = sqs_resource.get_queue_by_name(QueueName=LOW,)
        
        event_body = json.loads(event["Records"][0]["body"])
        s3_path = event_body["Records"][0]["s3"]["object"]["key"]
        s3_path = urllib.parse.unquote_plus(s3_path, encoding='utf-8')
        src_bucket = event_body["Records"][0]["s3"]["bucket"]["name"]
       
        src_bucket_obj = s3_resource.Bucket(src_bucket)
        s3_prefix = ("/".join(s3_path.split("/")[:-1]))
        
        logger.info("src_bucket={}".format(src_bucket))
        logger.info("s3_prefix={}".format(s3_prefix))
        
        list_obj = list_s3_obj(src_bucket_obj,s3_prefix,1)
        logger.info("list_obj={}".format(list_obj))
   
        for key in list_obj:
            logger.info("key:{}".format(key))
            key_list = key.split("/")
            source = key_list[1]
            schema =key_list[2]
            dataset = key_list[4]
           
            list_obj_data = list_s3_obj(src_bucket_obj, key+"/", 0)
            logger.info("list_obj_data={}".format(list_obj_data))
            
            pipeline_name=f"{source.upper()}-{dataset.upper()}"
            logger.info("pipeline_name={}".format(pipeline_name))


            type_event = ['success','failure']
            
            sfn_event = {
                'statusCode': 200,
                'body': {
                    "bucket": src_bucket,
                    "keysToProcess": list_obj_data,
                    "dataset": dataset,
                    "source": source,
                    "schema_name": schema,
                    "batch_id": str(uuid.uuid1()),
                    "systemtimestamp": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3],
                    "type": random.choice(type_event)
                }
            }
            
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
        
        logger.info("{} lambda Completed".format(component))
                
        return {
            'statusCode': 200
        }

    except Exception as e:
        raise e
        