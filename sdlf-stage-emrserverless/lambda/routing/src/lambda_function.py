import json
import os
from decimal import Decimal

from datalake_library import octagon
from datalake_library.commons import init_logger
from datalake_library.configuration.resource_configs import (
    DynamoConfiguration,
    SQSConfiguration,
    StateMachineConfiguration,
)
from datalake_library.interfaces.dynamo_interface import DynamoInterface
from datalake_library.interfaces.sqs_interface import SQSInterface
from datalake_library.interfaces.states_interface import StatesInterface

logger = init_logger(__name__)
team = os.environ["TEAM"]
dataset = os.environ["DATASET"]
pipeline = os.environ["PIPELINE"]
pipeline_stage = os.environ["PIPELINE_STAGE"]
org = os.environ["ORG"]
domain = os.environ["DOMAIN"]
env = os.environ["ENV"]


def serializer(obj):
    if isinstance(obj, Decimal):
        if obj.as_integer_ratio()[1] == 1:
            return int(obj)
        else:
            return float(obj)
    raise TypeError("Type not serializable")


def pipeline_start(octagon_client, event):
    peh_id = octagon_client.start_pipeline_execution(
        pipeline_name=f"{team}-{pipeline}-{pipeline_stage}",
        dataset_name=f"{team}-{dataset}",
        comment=event,  # TODO test maximum size
    )
    logger.info(f"peh_id: {peh_id}")
    return peh_id


# sdlf-stage-* stages supports three types of trigger:
# event: run stage when an event received on the team's event bus matches the configured event pattern
# event-schedule: store events received on the team's event bus matching the configured event pattern, then process them on the configured schedule
# schedule: run stage on the configured schedule, without any event as input
def get_source_records(event, dynamo_interface):
    records = []

    if event.get("trigger_type") == "schedule" and "event_pattern" not in event:
        logger.info("Stage trigger: schedule")
        records.append(event)
    elif event.get("trigger_type") == "schedule" and "event_pattern" in event:
        logger.info("Stage trigger: event-schedule")
        pipeline_info = dynamo_interface.get_pipelines_table_item(f"{team}-{pipeline}-{pipeline_stage}")
        min_items_to_process = 1
        max_items_to_process = 100
        logger.info(f"Pipeline is {pipeline}, stage is {pipeline_stage}")
        logger.info(f"Details from DynamoDB: {pipeline_info.get('pipeline', {})}")
        min_items_to_process = pipeline_info["pipeline"].get("min_items_process", min_items_to_process)
        max_items_to_process = pipeline_info["pipeline"].get("max_items_process", max_items_to_process)

        sqs_config = SQSConfiguration(team, pipeline, pipeline_stage)
        queue_interface = SQSInterface(sqs_config.get_stage_queue_name)
        logger.info(f"Querying {team}-{pipeline}-{pipeline_stage} objects waiting for processing")
        messages = queue_interface.receive_min_max_messages(min_items_to_process, max_items_to_process)
        logger.info(f"{len(messages)} Objects ready for processing")

        for record in messages:
            records.append(json.loads(record))
    elif "Records" in event:
        logger.info("Stage trigger: event")
        for record in event["Records"]:
            records.append(json.loads(record["body"]))
    else:
        raise Exception("Unable to ascertain trigger type (schedule, event-schedule or event)")

    return records


def enrich_records(records, metadata):
    enriched_records = []
    for record in records:
        enriched_record = dict(**record, transform=metadata)
        enriched_records.append(enriched_record)

    return enriched_records


def get_transform_details(dynamo_interface):
    transform_info = dynamo_interface.get_transform_table_item(f"{team}-{dataset}")
    logger.info(f"Pipeline is {pipeline}, stage is {pipeline_stage}")
    # an example transform is bundled with any sdlf-stage-*
    # if needed, either make changes to it, or deploy a custom transform (preferred)
    transform_details = dict(transform=os.environ["STAGE_TRANSFORM"])
    if pipeline in transform_info.get("pipeline", {}):
        if pipeline_stage in transform_info["pipeline"][pipeline]:
            transform_details = transform_details | transform_info["pipeline"][pipeline][pipeline_stage]
            logger.info(f"Details from DynamoDB: {transform_details}")

    return transform_details


def lambda_handler(event, context):
    try:
        octagon_client = octagon.OctagonClient().with_run_lambda(True).with_configuration_instance(env).build()
        dynamo_config = DynamoConfiguration()
        dynamo_interface = DynamoInterface(dynamo_config)
        peh_id = pipeline_start(octagon_client, event)
        records = get_source_records(event, dynamo_interface)
        metadata = get_transform_details(
            dynamo_interface
        )  # allow customising the transform through sdlf-dataset's pPipelineDetails
        metadata = dict(peh_id=peh_id, **metadata)
        records = enrich_records(records, metadata)

        if records:
            if records[0].get("trigger_type"):
                logger.info("Starting State Machine Execution (scheduled run without source events)")
            else:
                logger.info(f"Starting State Machine Execution (processing {len(records)} source events)")
            state_config = StateMachineConfiguration(team, pipeline, pipeline_stage)
            StatesInterface().run_state_machine(
                state_config.get_stage_state_machine_arn, json.dumps(records, default=serializer)
            )
            octagon_client.update_pipeline_execution(
                status=f"{pipeline_stage} Transform Processing", component="Transform"
            )
        else:
            logger.info("Nothing to process, exiting pipeline")
            octagon_client.end_pipeline_execution_success()

    except Exception as e:
        logger.error("Fatal error", exc_info=True)
        component = context.function_name.split("-")[-2].title()
        octagon_client.end_pipeline_execution_failed(
            component=component,
            issue_comment=f"{pipeline_stage} {component} Error: {repr(e)}",
        )
        raise e
