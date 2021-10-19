import os
import json
import boto3
import logging
import re
import decimal
import base64
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)
emr_client = boto3.client('emr')
ssm_client = boto3.client('ssm')
dynamodb = boto3.resource('dynamodb')


def get_secret(secret_params):
    secret_name = secret_params['secret']
    key = secret_params['key']

    session = boto3.session.Session()
    client = session.client(
        service_name='secretsmanager'
    )
    get_secret_value_response = client.get_secret_value(
        SecretId=secret_name
    )

    # Decrypts secret using the associated KMS CMK.
    # Depending on whether the secret is a string or binary, one of these fields will be populated.
    if 'SecretString' in get_secret_value_response:
        secret = get_secret_value_response['SecretString']
        secret = json.loads(secret)
        return secret[key]
    else:
        decoded_binary_secret = base64.b64decode(get_secret_value_response['SecretBinary'])


def replace_decimals(obj):
    if isinstance(obj, list):
        for i in range(len(obj)):
            obj[i] = replace_decimals(obj[i])
        return obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            obj[k] = replace_decimals(v)
        return obj
    elif isinstance(obj, set):
        return set(replace_decimals(i) for i in obj)
    elif isinstance(obj, decimal.Decimal):
        if obj % 1 == 0:
            return int(obj)
        else:
            return float(obj)
    else:
        return obj


def replace_command(job):
    try:
        message = job
        today = datetime.today()
        command = message.get('command', 'command not defined')
        secret_params = message.get('secret_params', None)
        date_substitutions = message.get('date_substitutions', [])
        for substitution in date_substitutions:
            token = substitution['token']
            date_format = substitution.get('format', '%Y%m%d 00:00')
            relativedelta_attributes = replace_decimals(substitution.get('relativedelta_attributes', None))
            calculated_date = today + relativedelta(**relativedelta_attributes)
            command = command.replace(token, calculated_date.strftime(date_format))
            # end_date calculation
        if not date_substitutions:
            end_date = today - timedelta(days=1)
            command = command.replace("$end_date", end_date.strftime("%Y%m%d 23:59"))
            # partition date
            partition_date = today - timedelta(days=1)
            command = command.replace("$partition_date", partition_date.strftime("%Y%m%d"))
        if secret_params is not None:
            params = get_secret(secret_params)
            if command.startswith("sqoop"):
                command = f'{command} {params} --password-file file:///home/hadoop/{secret_params["secret"]}'
            else:
                command = f'{command} {params}'
        message['command'] = command
    except Exception as e:
        logger.error("Fatal error", exc_info=True)
        raise e
    return message


def command_to_args(s):
    def strip_quotes(s):
        if s and (s[0] == '"' or s[0] == "'") and s[0] == s[-1]:
            return s[1:-1]
        return s

    return [strip_quotes(p).replace('\\"', '"').replace("\\'", "'") for p in
            re.findall(r'(?:[^"\s]*"(?:\\.|[^"])*"[^"\s]*)+|(?:[^\'\s]*\'(?:\\.|[^\'])*\'[^\'\s]*)+|[^\s]+', s)]


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
        job_name = message['job_name']
        ssmresponse = ssm_client.get_parameter(
            Name=f'/SDLF/Dynamo/{team}/{pipeline}/SqoopExtraction'
        )
        emr_jobs_table = ssmresponse['Parameter']['Value']
        ddb_table = dynamodb.Table(emr_jobs_table)
        response = ddb_table.get_item(Key={'job_name': job_name})
        logger.info(f'Response {response}')
        if 'Item' in response:
            logger.info(f'Item = {response["Item"]}')
            logger.info(f'Message = {message}')
            replace = replace_command(response["Item"])
            logger.info(f'Replace = {replace}')
            message.update(replace)
            logger.info(f'Message = {message}')
            step_args = command_to_args(message.get('command', 'no command provided'))
            step = {"Name": job_name,
                    'ActionOnFailure': 'CONTINUE',
                    'HadoopJarStep': {
                        'Jar': 'command-runner.jar',
                        'Args': step_args
                    }
                    }

            response = emr_client.add_job_flow_steps(JobFlowId=cluster_id, Steps=[step])
            logger.info('EMR action: {}'.format(response))
            message['StepId'] = response['StepIds'][0]

    except Exception as e:
        logger.error("Fatal error", exc_info=True)
        raise e
    return response['StepIds'][0]
