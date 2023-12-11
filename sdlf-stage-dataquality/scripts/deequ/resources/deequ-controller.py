import sys
import time
import logging
import ast

import boto3
from boto3.dynamodb.conditions import Key, Attr
from awsglue.utils import getResolvedOptions

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

dynamodb = boto3.resource('dynamodb')
glue = boto3.client('glue')


def get_suggestions(table, key_value):
    response = table.query(
        IndexName='table-index',
        KeyConditionExpression=Key('table_hash_key').eq(key_value)
    )
    return response['Items']


def testGlueJob(jobId, count, sec, jobName):
    i = 0
    while i < count:
        response = glue.get_job_run(JobName=jobName, RunId=jobId)
        status = response['JobRun']['JobRunState']
        if status == 'SUCCEEDED':
            return 1
        elif (status == 'RUNNING' or status == 'STARTING' or status == 'STOPPING'):
            time.sleep(sec)
            i += 1
        else:
            return 0
        if i == count:
            return 0


# Default Parameters
default_args = getResolvedOptions(sys.argv, [
    'env'])
env = default_args['env']

# Required Parameters
args = getResolvedOptions(sys.argv, [
    'team',
    'dataset',
    'glueDatabase',
    'glueTables'])

team = args['team']
dataset = args['dataset']
glue_database = args['glueDatabase']
glue_tables = [x.strip() for x in args['glueTables'].split(',')]

# Determine which tables already had Deequ data quality suggestions set up
profile_job_name = "sdlf-data-quality-profile-runner"
suggestions_job_name = "sdlf-data-quality-suggestion-analysis-verification-runner"
verification_job_name = "sdlf-data-quality-analysis-verification-runner"
suggestions_tables = []
verification_tables = []
suggestions_dynamo = dynamodb.Table(
    'octagon-DataQualitySuggestions-{}'.format(env))
for table in glue_tables:
    suggestions_item = get_suggestions(
        suggestions_dynamo, f"{team}-{dataset}-{table}")
    if suggestions_item:
        verification_tables.append(table)
    else:
        suggestions_tables.append(table)

logger.info('Calling Glue Jobs')
if suggestions_tables:
    suggestions_response = glue.start_job_run(
        JobName=suggestions_job_name,
        Arguments={
            '--team': team,
            '--dataset': dataset,
            '--glueDatabase': glue_database,
            '--glueTables': ','.join(suggestions_tables)
        }
    )
if verification_tables:
    verification_response = glue.start_job_run(
        JobName=verification_job_name,
        Arguments={
            '--team': team,
            '--dataset': dataset,
            '--glueDatabase': glue_database,
            '--glueTables': ','.join(verification_tables)
        }
    )

profile_response = glue.start_job_run(
    JobName=profile_job_name,
    Arguments={
        '--team': team,
        '--dataset': dataset,
        '--glueDatabase': glue_database,
        '--glueTables': ','.join(glue_tables)
    }
)

# Wait for execution to complete, timeout in 60*30=1800 secs
logger.info('Waiting for execution')
message = 'Error during Controller execution - Check logs'
if suggestions_tables:
    if testGlueJob(suggestions_response['JobRunId'], 60, 30, suggestions_job_name) != 1:
        raise ValueError(message)
if verification_tables:
    if testGlueJob(verification_response['JobRunId'], 60, 30, verification_job_name) != 1:
        raise ValueError(message)
if testGlueJob(profile_response['JobRunId'], 60, 30, profile_job_name) != 1:
    raise ValueError(message)
