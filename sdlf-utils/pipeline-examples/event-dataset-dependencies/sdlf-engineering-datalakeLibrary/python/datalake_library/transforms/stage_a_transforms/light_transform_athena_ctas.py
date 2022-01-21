#######################################################
# Custom transformation using athena
# where a JSON file is downloaded from RAW to /tmp
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
import string
import random
#######################################################
# Use S3 Interface to interact with S3 objects
# For example to download/upload them
#######################################################
from datalake_library.commons import init_logger
from datalake_library.configuration.resource_configs import S3Configuration, KMSConfiguration
from datalake_library.interfaces.s3_interface import S3Interface

s3_interface = S3Interface()
# IMPORTANT: Stage bucket where transformed data must be uploaded
stage_bucket = S3Configuration().stage_bucket
athena_client = boto3.client('athena')
glue_client = boto3.client('glue')
logger = logging.getLogger()
logger.setLevel(logging.DEBUG)

class CustomTransform():
    def __init__(self):
        logger.info("Athena Light Transform initiated")

    def transform_object(self, bucket, body, team, dataset):

        # returns table path, or table path with partition name
        # example if table has no partition
        # full_table_path = pre-stage/team/dataset/TABLE_NAME
        # if table has partition:
        # full_table_path = pre-stage/team/dataset/TABLE_NAME/dt=partitionvalue
        # Requires  LF: describe all tables in prestage_db
        def get_table_info(database, table):
            logger.info(f'DB: {database} Tbl: {table}')
            glue_response = glue_client.get_table(
                DatabaseName=database,
                Name=table)
            logger.debug('Glue get_table response: {}'.format(glue_response))
            table_location = glue_response['Table']['StorageDescriptor']['Location']
            table_columns = glue_response['Table']['StorageDescriptor']['Columns']
            table_bucket = table_location.split('/')[2]
            table_path = table_location.split(table_bucket + "/")[1]
            return table_bucket, table_path, table_columns

        # this method takes an s3 key with the format
        # 'team/dataset/table_name/partition=XXXXXX/file_name'
        # or without partition
        # 'team/dataset/table_name/file_name'
        # and returns table_name, partition (empty if no partition)

        def table_data_from_s3_key():
            full_input_file = f's3://{bucket}/{key}'
            table_partitions = []
            num_folders = key.count('/')  # counts number of folders
            database = key.split('/')[1]
            table_name = key.split('/')[2]  # take third folder
            path_partitions = key.split(table_name + '/')[1]
            table_partitions_path = ''
            if num_folders > 3: # if it has partitions
                table_partitions_path = path_partitions.rsplit('/', 1)[0]
                for partition_num in range(3, num_folders):
                    partition_folder = key.split('/')[partition_num]
                    name = partition_folder.split('=')[0]
                    value = partition_folder.split('=')[1]
                    part_dictionary = {"name": name, "value": value}
                    table_partitions.append(part_dictionary)
            return full_input_file, table_name, table_partitions, table_partitions_path, database

        try:
            # obtenemos el ambiente para armar el nombre de la base de datos
            ############################################
            # INITIAL VARIABLE DEFINITION / EXTRACTION #
            ############################################
            # GET DB PREFIX
            key = body['key']
            pipeline = body['pipeline']
            ssmcli = boto3.client('ssm')
            ssmresponse = ssmcli.get_parameter(
                Name='/SDLF/Misc/pEnv'
            )
            db_env = ssmresponse['Parameter']['Value']
            ssmresponse = ssmcli.get_parameter(
                Name=f'/SDLF/ATHENA/{team}/{pipeline}/WorkgroupName'
            )
            workgroup = ssmresponse['Parameter']['Value']

            input_file, source_table, partitions, partitions_path, database = table_data_from_s3_key()

            # Determinamos el nombre de la BD, se espera que sea <nombredelaBD>_<env> ej: raw_datbase_dev
            source_db = f'{team}_{database}_raw_{db_env}'
            target_db = f'{team}_{database}_{db_env}'

            # we assume that source and target tables have the same name
            target_table = source_table
            target_table_format = 'ORC'

            # get the info of the target table
            target_table_bucket, target_table_path, target_table_columns = get_table_info(target_db, target_table)
            target_table_full_path = target_table_path + ("/" + partitions_path if partitions_path else '')

            # delete previously ingested prestage files (reprocessing)
            s3_interface.delete_objects(target_table_bucket, target_table_full_path + '/')

            ctas_path = f's3://{target_table_bucket}/{target_table_full_path}'
            non_partition_columns = ''
            primitive_types = [
                'boolean', 'byte', 'short', 'int', 'long', 'float', 'double', 'string',
                'varchar', 'date', 'timestamp'
            ]
            first_primitive_column = ''
            for column in target_table_columns:
                non_partition_columns += f"{column['Name']}, "
                if first_primitive_column == '' and column['Type'] in primitive_types:
                    first_primitive_column = column['Name']
            non_partition_columns = non_partition_columns.rsplit(', ', 1)[0]
            # Obtain the first column to bucket by it
            bucket_field = first_primitive_column
            partition_filter = ''
            number_of_buckets = 1
            rand_suffix = ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(4))
            if not partitions:
                # CTAS can't be used if a table has the same path
                # It's easier to delete the table, but this process keeps the LF permissions granted on this table
                # Change the target table path (temporary)
                change_location = f"ALTER TABLE {target_db}.{source_table} SET LOCATION '{ctas_path}_{rand_suffix}'"
                # Insert into (CTAS) using the original path
                ctas_query = f'CREATE TABLE {target_db}.{source_table}_{rand_suffix} ' \
                             f' WITH ( ' \
                             f"  format = '{target_table_format}'," \
                             f"  external_location ='{ctas_path}', " \
                             f"  bucketed_by = ARRAY['{bucket_field}'], " \
                             f'  bucket_count = {number_of_buckets} ' \
                             f'     ) ' \
                             f'AS ' \
                             f'SELECT {non_partition_columns} ' \
                             f'FROM {source_db}.{source_table} ' \
                             f"WHERE \"$path\" = \'{input_file}\'"
                # Delete the CTAS table definition (keeps the data)
                drop_temp_table = f'DROP TABLE {target_db}.{source_table}_{rand_suffix} '
                # Return the target table to it's original location
                revert_location = f"ALTER TABLE {target_db}.{source_table} SET LOCATION '{ctas_path}'"
                steps = [{'info': f'CHANGE STAGE TABLE LOCATION',
                          'sql': change_location,
                          'db': target_db},
                         {'info': f'CREATE TEMP STAGE TABLE (CTAS)',
                          'sql': ctas_query,
                          'db': target_db},
                         {'info': f'DROP TEMP STAGE TABLE (CTAS)',
                          'sql': drop_temp_table,
                          'db': target_db},
                         {'info': f'REVERT TO ORIGINAL STAGE TABLE LOCATION',
                          'sql': revert_location,
                          'db': target_db}
                         ]
            else:
                for partition in partitions:
                    partition_filter += f'{partition["name"]}=\'{partition["value"]}\' AND'
                # Remove the last AND
                partition_filter = partition_filter.rsplit(' ', 1)[0]
                partitions_to_add = partition_filter.replace("AND", ",")
                add_partition_to_source = f'ALTER TABLE {source_db}.{source_table} ' \
                                          f'ADD IF NOT EXISTS PARTITION( ' \
                                          f'{partitions_to_add})'
                ctas_query = f'CREATE TABLE {target_db}.{source_table}_{rand_suffix} ' \
                             f' WITH ( ' \
                             f"  format = '{target_table_format}'," \
                             f"  external_location ='{ctas_path}', " \
                             f"  bucketed_by = ARRAY['{bucket_field}'], " \
                             f'  bucket_count = {number_of_buckets} ' \
                             f'     ) ' \
                             f'AS ' \
                             f'SELECT {non_partition_columns} ' \
                             f'FROM {source_db}.{source_table} ' \
                             f"WHERE \"$path\" = \'{input_file}\'"
                drop_table = f'DROP TABLE {target_db}.{source_table}_{rand_suffix}'
                add_partition = f'ALTER TABLE {target_db}.{target_table} ' \
                                f'ADD IF NOT EXISTS PARTITION( ' \
                                f'{partitions_to_add})'
                steps = [{'info': f'ADD PARTITION TO RAW TABLE',
                          'sql': add_partition_to_source,
                          'db': source_db},
                         {'info': f'CREATE STAGE TEMP TABLE',
                          'sql': ctas_query,
                          'db': target_db},
                         {'info': f'DROP STAGE TEMP TABLE',
                          'sql': drop_table,
                          'db': target_db},
                         {'info': f'ADD PARTITION TO STAGE TABLE',
                          'sql': add_partition,
                          'db': target_db}]
            num_of_steps = len(steps)
            job_details = {
                'steps': steps,
                'num_of_steps': num_of_steps,
                'current_step': 0,
                'jobStatus': 'STARTING_NEXT_QUERY',
                'partitions': partitions,
                'db_env': db_env,
                'workgroup': workgroup,
                'target_table_full_path': target_table_full_path,
                'source_db': source_db,
                'source_table': source_table,
                'target_db': target_db,
                'target_table': target_table
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

        try:
            num_of_steps = job_details['num_of_steps']
            current_step = job_details['current_step']
            partitions = job_details['partitions']
            workgroup = job_details['workgroup']
            steps = job_details['steps']
            status = job_details.get('jobStatus', "STARTING_NEXT_QUERY")
            target_table_full_path = job_details['target_table_full_path']
            source_db = job_details['source_db']
            source_table = job_details['source_table']
            target_db = job_details['target_db']
            target_table = job_details['target_table']
            step = steps[current_step]
            sql = step['sql']
            database = step['db']
            info = step['info']
            current_step += 1

            if status == "STARTING_NEXT_QUERY":
                query = sql
                logger.info(f'Athena Light Transform step {current_step}/{num_of_steps} [{info}] STARTED')
                logger.info(f'Executing query: {query}')
                query_id = run_athena_query(query, database, workgroup)
                job_details['query_id'] = query_id
                status, error_log = athena_status(query_id)
            elif status in ['RUNNING', 'QUEUED']:
                query_id = job_details['query_id']
                status, error_log = athena_status(query_id)
            dictionary = dict()
            if status == 'FAILED':
                logger.error(f'Athena heavy Transform step {current_step}/{num_of_steps} [{info}] FAILED')
                logger.error(f'Athena error: {error_log}')
            elif status == 'SUCCEEDED':
                query_result = get_athena_results(query_id)
                logger.info(f'Athena heavy Transform step {current_step}/{num_of_steps} [{info}] SUCCEEDED')
                logger.info(f'Query result :{query_result}')
                job_details['current_step'] = current_step
                if current_step == num_of_steps:
                    status = 'SUCCEEDED'
                    logger.info('Listing s3 created files to send to stageB')
                    processed_keys = s3_interface.list_objects(stage_bucket, target_table_full_path)
                    dictionary['processed_keys'] = processed_keys
                    dictionary['raw_db'] = source_db
                    dictionary['raw_table'] = source_table
                    dictionary['prestage_db'] = target_db
                    dictionary['prestage_table'] = target_table
                    dictionary['partitions'] = partitions
                    logger.info(f'Process finished, returning dict: {dictionary}')
                else:
                    status = 'STARTING_NEXT_QUERY'

            job_details['jobStatus'] = status
            response = {
                'processedKeysPath': processed_keys_path,
                'jobDetails': job_details,
                'processOutput': dictionary
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

        except Exception as exp:
            exception_type, exception_value, exception_traceback = sys.exc_info()
            traceback_string = traceback.format_exception(exception_type, exception_value, exception_traceback)
            err_msg = json.dumps({
                "errorType": exception_type.__name__,
                "errorMessage": str(exception_value),
                "stackTrace": traceback_string
            })
            logger.error(err_msg)
            try:
                if not partitions:
                    revert_step = steps[-1]
                    logger.info(f'An error ocurred, trying to rollback ddl changes')
                    run_athena_query(revert_step['sql'], revert_step['db'], workgroup)
            except Exception as exp:
                exception_type, exception_value, exception_traceback = sys.exc_info()
                traceback_string = traceback.format_exception(exception_type, exception_value, exception_traceback)
                err_msg = json.dumps({
                    "errorType": exception_type.__name__,
                    "errorMessage": str(exception_value),
                    "stackTrace": traceback_string
                })
                logger.error(err_msg)