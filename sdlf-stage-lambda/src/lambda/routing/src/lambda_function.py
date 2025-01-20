import json
import os
from decimal import Decimal

from datalake_library.commons import init_logger
from datalake_library.interfaces.sqs_interface import SQSInterface
from datalake_library.interfaces.states_interface import StatesInterface
from datalake_library.sdlf import (
    PipelineExecutionHistoryAPI,
    SQSConfiguration,
    StateMachineConfiguration,
)

logger = init_logger(__name__)
deployment_instance = os.environ["DEPLOYMENT_INSTANCE"]
dataset_deployment_instance = peh_table_instance = manifests_table_instance = os.environ["DATASET_DEPLOYMENT_INSTANCE"]


def serializer(obj):
    if isinstance(obj, Decimal):
        if obj.as_integer_ratio()[1] == 1:
            return int(obj)
        else:
            return float(obj)
    raise TypeError("Type not serializable")


def pipeline_start(pipeline_execution, event):
    peh_id = pipeline_execution.start_pipeline_execution(
        pipeline_name=deployment_instance,
        dataset_name=dataset_deployment_instance,
        comment=event,  # TODO test maximum size
    )
    logger.info(f"peh_id: {peh_id}")
    return peh_id


# sdlf-stage-* stages supports three types of trigger:
# event: run stage when an event received on the team's event bus matches the configured event pattern
# event-schedule: store events received on the team's event bus matching the configured event pattern, then process them on the configured schedule
# schedule: run stage on the configured schedule, without any event as input
def get_source_records(event):
    records = []

    if event.get("trigger_type") == "schedule" and "event_pattern" not in event:
        logger.info("Stage trigger: schedule")
        records.append(event)
    elif event.get("trigger_type") == "schedule" and "event_pattern" in event:
        logger.info("Stage trigger: event-schedule")
        min_items_to_process = 1
        max_items_to_process = 100
        logger.info(f"Pipeline stage is {deployment_instance}")
        logger.info(
            f"Pipeline stage configuration: min_items_to_process {min_items_to_process}, max_items_to_process {max_items_to_process}"
        )

        sqs_config = SQSConfiguration(instance=deployment_instance)
        queue_interface = SQSInterface(sqs_config.stage_queue)
        logger.info(f"Querying {deployment_instance} objects waiting for processing")
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


def get_transform_details():
    transform_details = dict(transform=os.environ["STAGE_TRANSFORM"])

    return transform_details


def lambda_handler(event, context):
    try:
        pipeline_execution = PipelineExecutionHistoryAPI(
            run_in_context="LAMBDA",
            region=os.getenv("AWS_REGION"),
            peh_table_instance=peh_table_instance,
            manifests_table_instance=manifests_table_instance,
        )
        peh_id = pipeline_start(pipeline_execution, event)
        records = get_source_records(event)
        metadata = get_transform_details()
        metadata = dict(peh_id=peh_id, **metadata)
        records = enrich_records(records, metadata)

        if records:
            if records[0].get("trigger_type"):
                logger.info("Starting State Machine Execution (scheduled run without source events)")
            else:
                logger.info(f"Starting State Machine Execution (processing {len(records)} source events)")
            state_config = StateMachineConfiguration(instance=deployment_instance)
            StatesInterface().run_state_machine(
                state_config.stage_state_machine, json.dumps(records, default=serializer)
            )
            pipeline_execution.update_pipeline_execution(
                status=f"{deployment_instance} Transform Processing", component="Transform"
            )
        else:
            logger.info("Nothing to process, exiting pipeline")
            pipeline_execution.end_pipeline_execution_success()

    except Exception as e:
        logger.error("Fatal error", exc_info=True)
        component = context.function_name.split("-")[-2].title()
        pipeline_execution.end_pipeline_execution_failed(
            component=component,
            issue_comment=f"{deployment_instance} {component} Error: {repr(e)}",
        )
        raise e
