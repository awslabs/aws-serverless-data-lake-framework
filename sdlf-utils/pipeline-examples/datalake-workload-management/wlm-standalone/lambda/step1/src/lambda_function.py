import json, boto3, datetime
import logging
import os
import urllib.parse
from botocore.exceptions import ClientError
import uuid

logger = logging.getLogger()
logger.setLevel(logging.INFO)

            
def lambda_handler(event, context):
    try:
        
        type_event = event['body']['type']

        if(type_event == 'success'):                
            return {
                'statusCode': 200
            }
        else:
            raise Exception("Failure type encountered, sending message to SNS")


    except Exception as e:
        logger.error(e)
        raise e
        