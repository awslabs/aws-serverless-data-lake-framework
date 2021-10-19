import os
import json
import boto3
import logging
import random
from time import sleep

logger = logging.getLogger()
logger.setLevel(logging.INFO)
emr_client = boto3.client('emr')
ssm_client = boto3.client('ssm')

def lambda_handler(event, context):
    try:
        # kms_data_key = os.environ['KMS_DATA_KEY']
        # emr_release = os.environ['EMR_RELEASE']
        # emr_ec2_role = os.environ['EMR_EC2_ROLE']
        # emr_role = os.environ['EMR_ROLE']
        # subnet = os.environ['SUBNET_ID']

        message = event  # ['body']
        team = message['team']
        env = message['env']
        pipeline = message['pipeline']
        cluster_id = message['clusterId']
        step_id = message['StepId']
        sleeptime = random.randint(500, 25000)/100
        # sleep to avoid throttling if many steps are submitted and described at the same time
        sleep(sleeptime)
        response = emr_client.describe_step(ClusterId=cluster_id, StepId=step_id)
        logger.info('EMR action: {}'.format(response))
        status = response['Step']['Status']['State']
        logger.info('Status: {}'.format(status))

    except Exception as e:
        logger.error("Fatal error", exc_info=True)
        raise e
    return status
