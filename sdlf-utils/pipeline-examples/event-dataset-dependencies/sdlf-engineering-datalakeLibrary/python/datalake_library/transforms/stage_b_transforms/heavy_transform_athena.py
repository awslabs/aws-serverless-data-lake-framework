#######################################################
# Blueprint example of a custom transformation
# where a JSON file is dowloaded from RAW to /tmp
# then parsed before being re-uploaded to STAGE
#######################################################
# License: Apache 2.0
#######################################################
# Author: emmgrci@amazon.com
# Emmanuel Arenas Garcia
#######################################################

#######################################################
# Import section
# common-pipLibrary repository can be leveraged
# to add external libraries as a layer if need be
#######################################################
import json
import boto3
import time
import sys
import logging
import traceback
from datetime import date, datetime
from dateutil.relativedelta import relativedelta
from datetime import timedelta
#######################################################
# Use S3 Interface to interact with S3 objects
# For example to download/upload them
#######################################################
from datalake_library.commons import init_logger
from datalake_library.configuration.resource_configs import S3Configuration, KMSConfiguration
from datalake_library.interfaces.s3_interface import S3Interface

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3_interface = S3Interface()
# IMPORTANT: Stage bucket where transformed data must be uploaded
stage_bucket = S3Configuration().stage_bucket
# artifacts bucket where .sql file is stored
artifacts_bucket = S3Configuration().artifacts_bucket
athena_client = boto3.client('athena')
glue_client = boto3.client('glue')


class CustomTransform():
    def __init__(self):
        logger.info("Athena Heavy Transform initiated")

    def transform_object(self, bucket, body, team, dataset):
        # def athena_status(query_execution):

        # retuns table path, or table path with partition name
        # example if table has no partition
        # full_table_path = pre-stage/datateam/dataset/TBL_42K_MDL
        # if table has partition:
        # full_table_path = pre-stage/datateam/dataset/TBL_42K_MDL/dt=partitionvalue

        def get_table_info(database, table):
            glue_response = glue_client.get_table(
                DatabaseName=database,
                Name=table)
            logger.debug('Glue get_table response: {}'.format(glue_response))
            table_location = glue_response['Table']['StorageDescriptor']['Location']
            table_columns = glue_response['Table']['StorageDescriptor']['Columns']
            table_bucket = table_location.split('/')[2]
            # table_partition = ''
            table_path = table_location.split(table_bucket + "/")[1]
            return table_bucket, table_path, table_columns

        try:
            logger.debug(f'body: {body}')
            # table_name = body['model']
            table_name = body['dest_table']['name']
            db = body['dest_db']
            behaviour = body.get('behaviour', 'append')
            dest_part_name = body['dest_table'].get('part_name', None)
            dest_part_value = body['dest_table'].get('part_value', None)
            date_substitutions = body.get('date_substitutions',[])
            logger.info(table_name)
            # partition_value = ''
            job_name = f'sdlf-{team}-{dataset}-{table_name}'  # Name of the Athena query without .sql
            # sql_file_create_key = 'artifacts/athena_queries/sdlf-datateam-dataset-dev_funnel_dataset-create.sql'
            # sql_file_insert_key = 'artifacts/athena_queries/sdlf-datateam-dataset-dev_funnel_dataset-insert.sql'
            target_table_bucket, target_table_path, target_table_columns = get_table_info(db, table_name)
            if dest_part_name and dest_part_value:
                target_table_full_path = f'{target_table_path}/{dest_part_name}={dest_part_value}'
                target_table_path = target_table_full_path
            if behaviour == 'overwrite':
                keys_to_delete = s3_interface.list_objects(target_table_bucket, target_table_path)
                logger.info(f'Files to delete: {keys_to_delete}')
                if keys_to_delete:
                    s3_interface.delete_objects(target_table_bucket, target_table_path)
            steps = body['steps']
            num_of_steps = len(steps)
            job_details = {
                'steps': steps,
                'num_of_steps': num_of_steps,
                'current_step': 0,
                'jobStatus': 'STARTING_NEXT_QUERY'
            }
            response = {
                'processedKeysPath': target_table_path,
                'jobDetails': job_details
            }
            return response

        except Exception as exp:
            exception_type, exception_value, exception_traceback = sys.exc_info()
            traceback_string = traceback.format_exception(exception_type, exception_value, exception_traceback)
            err_msg = json.dumps({
                "errorType": exception_type.__name__,
                "errorMessage": str(exception_value),
                "stackTrace": traceback_string
            })
            logger.error(err_msg)

    def check_job_status(self, bucket, body, processed_keys_path, job_details):
        # Runs athena query on the specified database
        # Returns query execution ID
        def run_athena_query(query_string, db_string, athena_workgroup):
            query_execution_id = athena_client.start_query_execution(
                QueryString=query_string,
                QueryExecutionContext={
                    'Database': db_string
                },
                WorkGroup=athena_workgroup
                # !!!!!!! Create this workgroup and assign it the s3 athena bucket
                #######################################################
                # workgroup 'OutputLocation': 's3://client-datalake-<env>-us-east-1-123456789000-athena-results/'
                #
            )
            return query_execution_id

        def athena_status(query_execution_id):
            state = 'QUEUED'
            while state == 'QUEUED':
                query_response = athena_client.get_query_execution(
                    QueryExecutionId=query_execution_id['QueryExecutionId'])
                logger.info(f'Executing - query id: {query_execution_id}')
                if 'QueryExecution' in query_response and \
                        'Status' in query_response['QueryExecution'] and \
                        'State' in query_response['QueryExecution']['Status']:
                    state = query_response['QueryExecution']['Status']['State']
                    error = ''
                    if state == 'FAILED':
                        error = query_response['QueryExecution']['Status']['StateChangeReason']
                        return state, error
                    elif state != 'QUEUED':
                        return state, error
                time.sleep(5)

        def get_athena_results(query_execution_id):
            query_results = athena_client.get_query_results(
                QueryExecutionId=query_execution_id['QueryExecutionId'],
                MaxResults=100
            )
            logger.info(query_results)
            return query_results

        num_of_steps = job_details['num_of_steps']
        current_step = job_details['current_step']
        team = body['team']
        date_substitutions = body.get('date_substitutions', [])
        pipeline = body['pipeline']
        table_name = body['dest_table']['name']
        dest_part_value =body['dest_table'].get('part_value', None)
        db = body['dest_db']
        steps = job_details['steps']
        status = job_details.get('jobStatus', "STARTING_NEXT_QUERY")
        step = steps[current_step]
        sql = step.get('sql','')
        sql_file = step.get('sql_file','')
        database = step['db']
        info = step['info']
        current_step += 1
        query = ''

        if status == "STARTING_NEXT_QUERY":
            ssmcli = boto3.client('ssm')
            ssmresponse = ssmcli.get_parameter(
                Name='/SDLF/Misc/pEnv'
            )
            db_env = ssmresponse['Parameter']['Value']
            ssmresponse = ssmcli.get_parameter(
                Name=f'/SDLF/ATHENA/{team}/{pipeline}/WorkgroupName'
            )
            workgroup = ssmresponse['Parameter']['Value']
            if sql != '':
                query = sql
            elif sql_file != '':
                sql_file = f'artifacts/athena_queries/{team}/{sql_file}'
                query = s3_interface.read_object(artifacts_bucket, sql_file).getvalue()
                query = query.replace('$ENV', db_env)
                query = query.replace('$dt', dest_part_value)
            else:
                logger.error('No sql or file provided')
            if dest_part_value and date_substitutions:
                for substitution in date_substitutions:
                    query = query.replace(substitution['token'],(datetime.strptime(dest_part_value,'%Y%m%d')
                                          - relativedelta(**substitution['relativedelta_attributes'])).strftime(substitution['format']))
            logger.info(f'Athena Light Transform step {current_step}/{num_of_steps} [{info}] STARTED')
            logger.info(f'Executing query: {query}')
            query_id = run_athena_query(query, database, workgroup)
            job_details['query_id'] = query_id
            status, error_log = athena_status(query_id)
        elif status in ['RUNNING', 'QUEUED']:
            query_id = job_details['query_id']
            status, error_log = athena_status(query_id)

        if status == 'FAILED':
            logger.error(f'Athena heavy Transform step {current_step}/{num_of_steps} [{info}] FAILED')
            logger.error(f'Athena error: {error_log}')
        elif status == 'SUCCEEDED':
            # processed_keys = s3_interface.list_objects(stage_bucket, target_table_full_path)
            query_result = get_athena_results(query_id)
            logger.info(f'Athena heavy Transform step {current_step}/{num_of_steps} [{info}] SUCCEEDED')
            logger.info(f'Query result :{query_result}')
            job_details['current_step'] = current_step
            if current_step == num_of_steps:
                status = 'SUCCEEDED'
            else:
                status = 'STARTING_NEXT_QUERY'

        job_details['jobStatus'] = status
        response = {
            'processedKeysPath': processed_keys_path,
            'jobDetails': job_details
        }

        #######################################################
        # IMPORTANT
        # This function must return a dictionary object with at least a reference to:
        # 1) processedKeysPath (i.e. S3 path where job outputs data without the s3://stage-bucket/ prefix)
        # 2) jobDetails (i.e. a Dictionary holding information about the job
        # e.g. jobName and jobId for Glue or clusterId and stepId for EMR
        # A jobStatus key MUST be present in jobDetails as it's used to determine the status of the job)
        # Example: {processedKeysPath' = 'post-stage/legislators',
        # 'jobDetails':
        # {'jobName': 'sdlf-engineering-e_perm-glue-job', 'jobId': 'jr-2ds438nfinev34', 'jobStatus': 'RUNNING'}}
        #######################################################

        return response
