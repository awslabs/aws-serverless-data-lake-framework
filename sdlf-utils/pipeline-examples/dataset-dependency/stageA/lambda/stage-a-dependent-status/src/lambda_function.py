import datetime
import os
import re
import shutil

import boto3
from boto3.dynamodb.conditions import Key

from datalake_library import octagon
from datalake_library.commons import init_logger
from datalake_library.configuration.resource_configs import DynamoConfiguration
from datalake_library.interfaces.dynamo_interface import DynamoInterface

dynamodbClient = boto3.resource("dynamodb")
logger = init_logger(__name__)


def get_current_date():
    return 'COMPLETED#{}T00:00:00.000Z'.format(
        datetime.datetime.utcnow().date().isoformat())


def get_dependent_datasets(team_name, dataset_name):
    dynamo_config = DynamoConfiguration()
    dynamo_interface = DynamoInterface(dynamo_config)
    transform_info = dynamo_interface.get_transform_table_item(
        "{}-{}".format(team_name, dataset_name)
    )
    return transform_info["dependencies"]


def get_dynamodb_peh_status(environment, dataset_name, dp_stage, current_date):
    peh_dynamodb_table = dynamodbClient.Table(
        f"octagon-PipelineExecutionHistory-{environment}")
    dynamodb_response = peh_dynamodb_table.query(
        IndexName="dataset-status_last_updated_timestamp-index",
        KeyConditionExpression=Key("dataset").eq(dataset_name)
        & Key("status_last_updated_timestamp").gt(current_date),
    )
    status_value = ""
    dp_stage_ft = re.sub(r'(?<!^)(?=[A-Z])', '-', dp_stage).lower()
    if dynamodb_response["Items"]:
        for i in dynamodb_response["Items"]:
            if dp_stage_ft in i["pipeline"]:
                status_value = i["status"]
    return status_value


def lambda_handler(event, context):
    """Checks dependent datasets status

    Arguments:
        event {dict} -- Dictionary with details on datasets dependency
        context {dict} -- Dictionary with details on Lambda context

    Returns:
        {dict} -- Dictionary with details on datasets dependency
    """
    try:
        logger.info("Dataset dependency Lambda")
        bucket = event['body']['bucket']
        team = event['body']['team']
        pipeline = event['body']['pipeline']
        stage = event['body']['pipeline_stage']
        dataset = event['body']['dataset']
        env = event['body']['env']
        dependent_stage = event['body']['dependent_stage']
        retry_count = event['body']["retry_count"]

        logger.info('Initializing Octagon client')
        component = context.function_name.split('-')[-2].title()
        octagon_client = (
            octagon.OctagonClient()
            .with_run_lambda(True)
            .with_configuration_instance(env)
            .build()
        )
        if 'peh_id' not in event['body']:
            peh_id = octagon_client.start_pipeline_execution(
                pipeline_name='{}-{}-stage-{}'.format(team,
                                                      pipeline, stage[-1].lower()),
                dataset_name='{}-{}'.format(team, dataset),
                comment=event
            )
        else:
            peh_id = event['body']['peh_id']
            octagon.peh.PipelineExecutionHistoryAPI(
                octagon_client).retrieve_pipeline_execution(peh_id)

        logger.info("Checking dependent tables status")
        dependent_datasets = get_dependent_datasets(team, dataset)

        atomic_completed_datasets_count = 0
        for each_dataset in dependent_datasets:
            output = get_dynamodb_peh_status(
                env,
                dependent_datasets[each_dataset],
                dependent_stage,
                get_current_date()
            )
            if output == "COMPLETED":
                atomic_completed_datasets_count += 1

        dependent_datasets_status = "SUCCEEDED" if len(
            dependent_datasets) == atomic_completed_datasets_count else "FAILED"

        octagon_client.update_pipeline_execution(
            status="{} {} Dependent Datasets Status".format(stage, component), component=component)
    except Exception as e:
        logger.error("Fatal error", exc_info=True)
        octagon_client.end_pipeline_execution_failed(component=component,
                                                     issue_comment="{} {} Error: {}".format(stage, component, repr(e)))
        raise e
    return {
        "body": {
            "bucket": bucket,
            "team": team,
            "pipeline": pipeline,
            "pipeline_stage": stage,
            "dataset": dataset,
            "env": env,
            "dependent_stage": dependent_stage,
            "retry_count": retry_count + 1,
            "dependent_datasets_status": dependent_datasets_status,
            "peh_id": peh_id
        }
    }
