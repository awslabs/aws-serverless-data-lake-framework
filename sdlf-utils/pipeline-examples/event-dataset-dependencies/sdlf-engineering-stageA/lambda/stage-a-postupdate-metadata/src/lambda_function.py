import boto3
import json
from datetime import datetime
import decimal
from boto3.dynamodb.conditions import Key, Attr
from dateutil.relativedelta import relativedelta, MO, TU, WE, TH, FR, SA, SU
from datalake_library.commons import init_logger
from datalake_library.configuration.resource_configs import DynamoConfiguration, SQSConfiguration, S3Configuration
from datalake_library.interfaces.dynamo_interface import DynamoInterface
from datalake_library.interfaces.sqs_interface import SQSInterface
from datalake_library.interfaces.s3_interface import S3Interface
from datalake_library import octagon
from datalake_library.octagon import Artifact, EventReasonEnum, peh

logger = init_logger(__name__)
dynamodb = boto3.resource('dynamodb')
glue_client = boto3.client('glue')
sqs = boto3.resource('sqs')
ssmcli = boto3.client('ssm')


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
        return {replace_decimals(i) for i in obj}
    elif isinstance(obj, decimal.Decimal):
        if obj % 1 == 0:
            return int(obj)
        else:
            return float(obj)
    else:
        return obj


def replace_days(dictionary):
    weekday = dictionary.get("weekday", None)
    if weekday:
        week_expr = dictionary["weekday"]
        week_day = week_expr[:2]
        week_int = int(week_expr.split("(")[1].split(")")[0])
        if week_day == "MO":
            dictionary["weekday"] = MO(week_int)
        elif week_day == "TU":
            dictionary["weekday"] = TU(week_int)
        elif week_day == "WE":
            dictionary["weekday"] = WE(week_int)
        elif week_day == "TH":
            dictionary["weekday"] = TH(week_int)
        elif week_day == "FR":
            dictionary["weekday"] = FR(week_int)
        elif week_day == "SA":
            dictionary["weekday"] = SA(week_int)
        elif week_day == "SU":
            dictionary["weekday"] = SU(week_int)
        else:
            logger.error("Wrong day code")
    return dictionary


def lambda_handler(event, context):
    """Updates the S3 objects metadata catalog

    Arguments:
        event {dict} -- Dictionary with details on previous processing step
        context {dict} -- Dictionary with details on Lambda context

    Returns:
        {dict} -- Dictionary with outcome of the process
    """

    try:
        logger.info('Fetching event data from previous step')
        body = event['body']
        processOutput = body['job']['processOutput']
        processed_keys = processOutput['processed_keys']
        team = body['team']
        pipeline = body['pipeline']
        stage = body['pipeline_stage']
        dataset1 = body['dataset']
        peh_id = body['peh_id']
        prestage_db = processOutput.get('prestage_db', None)
        prestage_table = processOutput.get('prestage_table', None)
        logger.info('Initializing Octagon client')
        component = context.function_name.split('-')[-2].title()
        octagon_client = (
            octagon.OctagonClient()
            .with_run_lambda(True)
            .with_configuration_instance(body['env'])
            .build()
        )
        peh.PipelineExecutionHistoryAPI(
            octagon_client).retrieve_pipeline_execution(peh_id)

        logger.info('Initializing DynamoDB config and Interface')
        dynamo_config = DynamoConfiguration()
        dynamo_interface = DynamoInterface(dynamo_config)

        logger.info('Storing metadata to DynamoDB and tagging resulting S3 Objects')
        bucket = S3Configuration().stage_bucket
        for key in processed_keys:
            object_metadata = {
                'bucket': bucket,
                'key': key,
                'size': S3Interface().get_size(bucket, key),
                'last_modified_date': S3Interface().get_last_modified(bucket, key),
                'org': body['org'],
                'app': body['app'],
                'env': body['env'],
                'team': team,
                'pipeline': pipeline,
                'dataset': dataset1,
                'stage': 'stage',
                'pipeline_stage': stage,
                'peh_id': peh_id
            }

            dynamo_interface.update_object_metadata_catalog(object_metadata)

            tag_keys = ['org', 'app', 'env', 'team', 'dataset']
            tag_dict = {key: object_metadata[key] for key in tag_keys}
            S3Interface().tag_object(bucket, key, tag_dict)

        # New dependencies
        if body['job']['jobDetails']['num_of_steps'] > 0:
            ssmresponse = ssmcli.get_parameter(
                Name=f'/SDLF/DDB/{team}/{pipeline}/DependenciesByTable'
            )
            ddb_dependencies_by_table = ssmresponse['Parameter']['Value']
            ddb_table = dynamodb.Table(ddb_dependencies_by_table)
            ssmresponse = ssmcli.get_parameter(
                Name=f'/SDLF/DDB/{team}/{pipeline}/Dependencies'
            )
            ddb_dependencies = ssmresponse['Parameter']['Value']
            consulta = f'{prestage_db.lower()}.{prestage_table.lower()}'
            logger.info(consulta)
            response = ddb_table.get_item(Key={'table_name': consulta})
            logger.info(f'Response {response}')
            if 'Item' in response:
                list_transforms = response['Item']['list_transforms']
                num_of_transforms = len(list_transforms)
                logger.debug(f'Response {response}')
                logger.info(f'This table triggers {num_of_transforms} datasets')
                next_stage = chr(ord(stage[-1]) + 1)
                stage_b_message = {}
                dest = {}
                tbls = []
                for dataset in list_transforms:
                    ddb_steps = dynamodb.Table(ddb_dependencies)
                    logger.info(dataset)
                    response = ddb_steps.get_item(Key={'dataset': dataset})
                    logger.info(f'Response {response}')
                    num_of_transforms = len(list_transforms)
                    item = response['Item']
                    dest_table = item['dataset'].split('.')[1]
                    dest_db = item['dataset'].split('.')[0]
                    date_substitutions = replace_decimals(item.get('date_substitutions',[]))
                    dependencies = item['dependencies']
                    logger.info(f'Dependencies: {dependencies}')
                    partition = item.get('partitionColumn', '')
                    partition_mask = item.get('partitionPythonMask', None)
                    partition_value_formatted = None
                    for table in dependencies:
                        table_name = table['TableName'].split('.')[1]
                        table_db = table['TableName'].split('.')[0]
                        table_partition = table.get('FieldColumn', '')
                        table_partition_format = table.get('DateExpression', None)
                        relativedelta_attributes = replace_decimals(table.get('relativedelta_attributes', None))
                        relativedelta_attributes = replace_days(relativedelta_attributes)
                        logger.info(f'relativedelta_attributes={relativedelta_attributes}')
                        table_partitions = processOutput.get('partitions', [])
                        usage = table.get('Usage', 'validate').lower()
                        if usage == 'validate':
                            if prestage_db.lower() == table_db.lower() and prestage_table.lower() == table_name.lower():
                                logger.info(f'This table does not update/overwrite {dataset} dataset')
                                break
                            else:
                                logger.debug(f'Table {table_db}.{table_name} is not the trigger table')
                        elif prestage_db.lower() == table_db.lower() and prestage_table.lower() == table_name.lower():
                            # dst_tbl_partitions = get_table_partitions(prestage_db,prestage_table)
                            partition_value_formatted = ''
                            # If dest table has partitions and source table has partitions
                            logger.debug(f'Partition: {partition}, table_partitions: {table_partitions}')
                            if table_partitions and table_partition_format is not None:
                                table_partition_value = table_partitions[0]['value']
                                value = datetime.strptime(table_partition_value, table_partition_format)
                                target_value = value + relativedelta(**relativedelta_attributes)
                                partition_value_formatted = target_value.strftime(partition_mask)
                                logger.info(f'This table {usage.upper()} dataset {dest_table} ' 
                                            f' Partition {partition} = {partition_value_formatted}')
                                # validate(table_db, table_name, table_partitions)
                            stage_b_message['prev_stage_processed_keys'] = processed_keys
                            stage_b_message['team'] = team
                            stage_b_message['pipeline'] = pipeline
                            stage_b_message['pipeline_stage'] = ''.join([stage[:-1], next_stage])
                            stage_b_message['dataset'] = dataset1
                            stage_b_message['org'] = body['org']
                            stage_b_message['app'] = body['app']
                            stage_b_message['env'] = body['env']
                            stage_b_message['behaviour'] = table['Usage'].lower()
                            stage_b_message['dest_db'] = dest_db
                            stage_b_message['dest_table'] = {}
                            stage_b_message['dest_table']['name'] = dest_table
                            stage_b_message['dest_table']['part_name'] = partition
                            stage_b_message['dest_table']['part_value'] = partition_value_formatted
                            stage_b_message['steps'] = item['steps']
                            stage_b_message['date_substitutions'] = date_substitutions

                    logger.info('Sending messages to next SQS queue if it exists')
                    logger.info(stage_b_message)
                    sqs_config = SQSConfiguration(team, pipeline, ''.join(
                        [stage[:-1], next_stage]))
                    sqs_interface = SQSInterface(sqs_config.get_stage_queue_name)
                    sqs_interface.send_message_to_fifo_queue(
                        json.dumps(stage_b_message), '{}-{}'.format(team, pipeline))

            else:
                logger.info('This table triggers 0 datasets')

        octagon_client.update_pipeline_execution(status=f'{stage} {component} Processing',
                                                 component=component)
        octagon_client.end_pipeline_execution_success()
    except Exception as e:
        logger.error("Fatal error", exc_info=True)
        octagon_client.end_pipeline_execution_failed(component=component,
                                                     issue_comment=f'{stage} {component} Error: {repr(e)}')
        raise e
    return 200
