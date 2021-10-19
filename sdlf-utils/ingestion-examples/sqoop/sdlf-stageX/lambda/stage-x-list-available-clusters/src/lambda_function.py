import os
import json
import boto3
import logging
from datetime import date, timedelta, datetime

logger = logging.getLogger()
logger.setLevel(logging.INFO)
emr_client = boto3.client('emr')

def lambda_handler(event, context):
    try:
        logger.info(f'E = {event}')
        message = event
        cluster_name = event.get('clusterName',f'sdlf-{event["team"]}-{event["pipeline"]}-{event["pipeline_stage"]}')
        message['clusterName'] = cluster_name
        today = date.today()
        yesterday = today - timedelta(days = 1)
        response= emr_client.list_clusters(
            CreatedAfter=datetime(yesterday.year, yesterday.month, yesterday.day),
            ClusterStates=[
            'STARTING','BOOTSTRAPPING','RUNNING','WAITING'])
        clusters  = response['Clusters']
        for cluster in clusters:
            if cluster['Name'] == cluster_name:
                cluster_id = cluster['Id']
                message['clusterId'] = cluster_id
        logger.info(f'Message to send {message}')
    except Exception as e:
        logger.error("Fatal error", exc_info=True)
        raise e
    return message
