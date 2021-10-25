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
import os
import json
import logging
import boto3
import time
from datalake_library.commons import init_logger
from datalake_library.configuration.resource_configs import StateMachineConfiguration
from datalake_library.interfaces.states_interface import StatesInterface

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def lambda_handler(event, context):
    try:
        message = event
        message['job_name'] = event.get('job_name','Empty')
        message['org'] = os.environ['ORG']
        message['app'] = os.environ['APP']
        message['env'] = os.environ['ENV']
        message['team'] = os.environ['TEAM']
        message['pipeline'] = os.environ['PIPELINE']
        message['pipeline_stage'] = 'StageX'
        state_config = StateMachineConfiguration(message['team'],
                                                 message['pipeline'],
                                                 message['pipeline_stage'])
        logger.info(f'Message to send: {message}')
        precision = 3
        seconds = f'{time.time():.{precision}f}'
        state_machine_name = f"{message['job_name']}-{seconds}"
        StatesInterface().run_state_machine(
            state_config.get_stage_state_machine_arn, message, state_machine_name)
    except Exception as e:
        logger.error("Fatal error", exc_info=True)
        raise e
    return
