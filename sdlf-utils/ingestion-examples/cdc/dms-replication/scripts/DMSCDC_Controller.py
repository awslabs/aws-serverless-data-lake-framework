import sys
import json
from urllib.parse import urlparse
import urllib
import datetime
import boto3
import time
from awsglue.utils import getResolvedOptions
import logging

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

ddbconn = boto3.client('dynamodb')
glue = boto3.client('glue')
s3conn = boto3.client('s3')


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
    'org',
    'app',
    'env',
    'team',
    'dataset'])
org = default_args['org']
app = default_args['app']
env = default_args['env']
team = default_args['team']
dataset = default_args['dataset']

# Optional Parameters
try:
    prefix = getResolvedOptions(sys.argv, ['prefix'])['prefix']
except:
    prefix = ""
try:
    out_prefix = getResolvedOptions(sys.argv, ['out_prefix'])['out_prefix']
except:
    out_prefix = ""

# Required Parameters
args = getResolvedOptions(sys.argv, [
    'bucket',
    'out_bucket'])

bucket = args['bucket']
out_bucket = args['out_bucket']
out_path = out_bucket + '/' + out_prefix

# get the list of table folders
s3_input = 's3://'+bucket+'/'+prefix
url = urlparse(s3_input)
folders = s3conn.list_objects(
    Bucket=bucket, Prefix=prefix, Delimiter='/').get('CommonPrefixes')

index = 0
max = len(folders)


# get folder metadata
for folder in folders:
    full_folder = folder['Prefix']
    folder = full_folder[len(prefix):]
    path = bucket + '/' + full_folder
    item = {
        'path': {'S': path},
        'bucket': {'S': bucket},
        'prefix': {'S': prefix},
        'folder': {'S': folder},
        'PrimaryKey': {'S': 'null'},
        'PartitionKey': {'S': 'null'},
        'LastFullLoadDate': {'S': '1900-01-01 00:00:00'},
        'LastIncrementalFile': {'S': path + '0.parquet'},
        'ActiveFlag': {'S': 'false'}}

    # CreateTable if not already present
    try:
        response1 = ddbconn.describe_table(TableName='DMSCDC_Controller')
    except Exception as e:
        ddbconn.create_table(
            TableName='DMSCDC_Controller',
            KeySchema=[{'AttributeName': 'path', 'KeyType': 'HASH'}],
            AttributeDefinitions=[
                {'AttributeName': 'path', 'AttributeType': 'S'}],
            BillingMode='PAY_PER_REQUEST')
        ddb_waiter = ddbconn.get_waiter('table_exists')
        ddb_waiter.wait(TableName='DMSCDC_Controller')

    # Put Item if not already present
    try:
        response = ddbconn.get_item(
            TableName='DMSCDC_Controller',
            Key={'path': {'S': path}})
        if 'Item' in response:
            item = response['Item']
        else:
            ddbconn.put_item(
                TableName='DMSCDC_Controller',
                Item=item)
    except:
        ddbconn.put_item(
            TableName='DMSCDC_Controller',
            Item=item)

    partitionKey = item['PartitionKey']['S']
    lastFullLoadDate = item['LastFullLoadDate']['S']
    lastIncrementalFile = item['LastIncrementalFile']['S']
    activeFlag = item['ActiveFlag']['S']
    primaryKey = item['PrimaryKey']['S']

    logger.info(json.dumps(item))
    logger.info('Bucket: '+bucket+' Path: ' + full_folder)

    loadInitial = False

    # determine if need to run initial --> Run Initial --> Update DDB
    initialfiles = s3conn.list_objects(
        Bucket=bucket, Prefix=full_folder+'LOAD').get('Contents')
    if activeFlag == 'true':
        if initialfiles is not None:
            s3FileTS = initialfiles[0]['LastModified'].replace(tzinfo=None)
            ddbFileTS = datetime.datetime.strptime(
                lastFullLoadDate, '%Y-%m-%d %H:%M:%S')
            if s3FileTS > ddbFileTS:
                message = 'Starting to process Initial file.'
                loadInitial = True
                lastFullLoadDate = datetime.datetime.strftime(
                    s3FileTS, '%Y-%m-%d %H:%M:%S')
            else:
                message = 'Intial files already processed.'
        else:
            message = 'No initial files to process.'
    else:
        message = 'Load is not active.  Update dynamoDB.'
    print(message)

    # Call Initial Glue Job for this source
    if loadInitial:
        response = glue.start_job_run(
            JobName='{}-{}-{}-{}-{}-dms-cdc-load-initial'.format(
                org, app, env, team, dataset),
            Arguments={
                '--bucket': bucket,
                '--prefix': prefix,
                '--folder': folder,
                '--out_path': out_path,
                '--partitionKey': partitionKey})

        # Wait for execution complete, timeout in 60*30=1800 secs, if successful, update ddb
        if testGlueJob(response['JobRunId'], 60, 30, '{}-{}-{}-{}-{}-dms-cdc-load-initial'.format(org, app, env, team, dataset)) != 1:
            message = 'Error during Controller execution - Check Load Initial logs'
            raise ValueError(message)
        else:
            ddbconn.update_item(
                TableName='DMSCDC_Controller',
                Key={"path": {"S": path}},
                AttributeUpdates={"LastFullLoadDate": {"Value": {"S": lastFullLoadDate}}})

    loadIncremental = False
    newIncrementalFile = path + '0.parquet'

    # determine if need to run incremental --> Run incremental --> Update DDB
    if activeFlag == 'true':
        # Get the latest incremental file
        incrementalFiles = s3conn.list_objects(
            Bucket=bucket, Prefix=full_folder+'2', Marker=lastIncrementalFile.split('/', 1)[1]).get('Contents')
        if incrementalFiles is not None:
            filecount = len(incrementalFiles)
            newIncrementalFile = bucket + '/' + \
                incrementalFiles[filecount-1]['Key']
            if newIncrementalFile != lastIncrementalFile:
                loadIncremental = True
                message = "Starting to process incremental files"
            else:
                message = "Incremental files already processed."
        else:
            message = "No incremental files to process."
    else:
        message = "Load is not active.  Update dynamoDB."
    print(message)

    # Call Incremental Glue Job for this source
    if loadIncremental:
        response = glue.start_job_run(
            JobName='{}-{}-{}-{}-{}-dms-cdc-load-incremental'.format(
                org, app, env, team, dataset),
            Arguments={
                '--bucket': bucket,
                '--prefix': prefix,
                '--folder': folder,
                '--out_path': out_path,
                '--partitionKey': partitionKey,
                '--lastIncrementalFile': lastIncrementalFile,
                '--newIncrementalFile': newIncrementalFile,
                '--primaryKey': primaryKey,
                '--env': env
            })

        # Wait for execution complete, timeout in 60*30=1800 secs, if successful, update ddb
        if testGlueJob(response['JobRunId'], 60, 30, '{}-{}-{}-{}-{}-dms-cdc-load-incremental'.format(org, app, env, team, dataset)) != 1:
            message = 'Error during Controller execution - Check Load Incremental logs'
            raise ValueError(message)
        else:
            ddbconn.update_item(
                TableName='DMSCDC_Controller',
                Key={"path": {"S": path}},
                AttributeUpdates={"LastIncrementalFile": {"Value": {"S": newIncrementalFile}}})
