# -*- coding: utf-8 -*-
# Copyright 2020 Amazon.com, Inc. and its affiliates. All Rights Reserved.
#
# Licensed under the Amazon Software License (the "License").
# You may not use this file except in compliance with the License.
# A copy of the License is located at
#
#   http://aws.amazon.com/asl/
#
# or in the "license" file accompanying this file. This file is distributed
# on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either
# express or implied. See the License for the specific language governing
# permissions and limitations under the License.
#
# Scheduled job to invoke EMR cluster with sqoop to import data
# Lambda Function for Data Lake Import
# Author: Emmanuel Arenas Garcia (emmgrci@amazon.com) 2020-09-15
from botocore.vendored import requests
from botocore.exceptions import ClientError
import json
import os
import logging
import traceback
import sys
import boto3
from boto3.dynamodb.types import TypeDeserializer, TypeSerializer

DYNAMO_SCHEDULE_TABLE = os.getenv('DYNAMO_SCHEDULE_TABLE')
CLOUDWATCH_TARGET = os.getenv('CLOUDWATCH_TARGET')


logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(getattr(logging, os.getenv('LOG_LEVEL', 'INFO')))
logger.info('Loading Lambda Function {}'.format(__name__))

dynamoClient = boto3.resource('dynamodb', region_name='us-east-1')
cloudWatchClient = boto3.client('events')
lambdaClient = boto3.client('lambda')

def from_dynamodb_to_json(item):
    d = TypeDeserializer()
    return {k: d.deserialize(value=v) for k, v in item.items()}

def remove_cloudwatch_rule(job_name):
    try:
        target_name = job_name + '_Target'
        rule_response = cloudWatchClient.remove_targets(
            Rule=job_name,
            Ids=[
                target_name,
            ])
        logger.debug(rule_response)
        rule_response = cloudWatchClient.delete_rule(
            Name=job_name)
        logger.debug(rule_response)
    except Exception as e:
        exception_type, exception_value, exception_traceback = sys.exc_info()
        traceback_string = traceback.format_exception(exception_type, exception_value, exception_traceback)
        err_msg = json.dumps({
            "errorType": exception_type.__name__,
            "errorMessage": str(exception_value),
            "stackTrace": traceback_string,
            "msg_exception": "Cloudwatch Event Exception: " + str(e)
        })
        logger.error(err_msg)
        return


def put_cloudwatch_rule(job_name, crond_expression, workflow_status, lambda_params):
    target_name = job_name + '_Target'
    try:
        periodicity = lambda_params.get('periodicity','DAILY')
        if periodicity == "ONCE":
            response = lambdaClient.invoke(FunctionName=CLOUDWATCH_TARGET,
                                           InvocationType='RequestResponse',
                                           Payload=json.dumps(lambda_params))
            result = json.loads(response.get('Payload').read())
            return "Step Functions fired with response message " + str(result)
        else:
            rule_response = cloudWatchClient.put_rule(
                Name=job_name,
                ScheduleExpression=crond_expression,
                State=workflow_status
            )
            logger.debug(rule_response)
            try:
                lambdaClient.add_permission(
                        FunctionName=CLOUDWATCH_TARGET,
                        StatementId='allow_cloudwatch',
                        Action='lambda:InvokeFunction',
                        Principal='events.amazonaws.com',
                        SourceArn=rule_response['RuleArn'].split('/')[0]+'/*')
            except:
                logger.info('Permission already exists ')
            cloudWatchClient.put_targets(
                Rule=job_name,
                Targets=[
                    {
                        'Id': target_name,
                        'Arn': CLOUDWATCH_TARGET,
                        'Input': json.dumps(lambda_params)
                    }
                ]
            )

    except Exception as e:
        exception_type, exception_value, exception_traceback = sys.exc_info()
        traceback_string = traceback.format_exception(exception_type, exception_value, exception_traceback)
        err_msg = json.dumps({
            "errorType": exception_type.__name__,
            "errorMessage": str(exception_value),
            "stackTrace": traceback_string,
            "msg_exception": "Cloudwatch Event Exception: " + str(e)
        })
        logger.error(err_msg)
        return


def lambda_handler(event, context):
    records = event['Records']
    logger.info(records)
    for item in records:
        event = item['eventName']
        logger.debug(event)
        job_name = item['dynamodb']['Keys'].get('job_name', {}).get('S')
        if str(event) == 'REMOVE':
            logger.info("Deleting rule")
            remove_cloudwatch_rule(job_name)
            return
        else:
            job_status = item['dynamodb']['NewImage'].get('job_status', {}).get('S', 'DISABLED')
            crond_expression = item['dynamodb']['NewImage'].get('crond_expression', {}).get('S', 'crond(0 0 * * ? *)')
            lambda_params = {'job_name':job_name}

            if str(event) == 'INSERT':
                logger.info("Creating rule")
                put_cloudwatch_rule(job_name, crond_expression, job_status, lambda_params)
            elif str(event) == 'MODIFY':
                logger.info("Updating rule")
                logger.info("Deleting previous rule")
                remove_cloudwatch_rule(job_name)
                logger.info("Creating new rule")
                put_cloudwatch_rule(job_name, crond_expression, job_status, lambda_params)
            else:
                logger.error("Unknown option")
