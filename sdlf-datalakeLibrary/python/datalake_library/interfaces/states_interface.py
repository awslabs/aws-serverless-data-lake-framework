import json
import os
from datetime import date, datetime

import boto3

from ..commons import init_logger


class StatesInterface:

    def __init__(self, log_level=None, states_client=None):
        self.log_level = log_level or os.getenv('LOG_LEVEL', 'INFO')
        self._logger = init_logger(__name__, self.log_level)
        self._states_client = states_client or boto3.client('stepfunctions')

    @staticmethod
    def json_serial(obj):
        """JSON serializer for objects not serializable by default"""
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        raise TypeError("Type %s not serializable" % type(obj))

    def get_all_step_functions(self):
        self._logger.info('obtaining a list of all step functions')
        pages = self._states_client.get_paginator(
            'list_state_machines').paginate()
        step_functions = []
        for result in pages:
            step_functions.extend(result['stateMachines'])
        return step_functions

    def run_state_machine(self, machine_arn, message):
        self._logger.info(
            'running state machine with arn {}'.format(machine_arn))
        return self._states_client.start_execution(
            stateMachineArn=machine_arn,
            input=json.dumps(message, default=self.json_serial)
        )

    def describe_state_execution(self, execution_arn):
        self._logger.info('describing {}'.format(execution_arn))
        response = self._states_client.describe_execution(
            executionArn=execution_arn
        )
        return response['status']
