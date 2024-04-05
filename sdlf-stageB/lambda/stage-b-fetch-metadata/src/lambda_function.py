from datalake_library import octagon
from datalake_library.commons import init_logger
from datalake_library.configuration.resource_configs import DynamoConfiguration
from datalake_library.interfaces.dynamo_interface import DynamoInterface

logger = init_logger(__name__)


def get_glue_transform_details(bucket, team, dataset, pipeline, stage):
    dynamo_config = DynamoConfiguration()
    dynamo_interface = DynamoInterface(dynamo_config)
    transform_info = dynamo_interface.get_transform_table_item(f"{team}-{dataset}")
    # we assume a Glue Job has already been created based on customer needs
    job_name = f"sdlf-{team}-{dataset}-glue-job"  # Name of the Glue Job
    glue_capacity = {"WorkerType": "G.1X", "NumberOfWorkers": 10}
    wait_time = 60
    glue_arguments = {
        # Specify any arguments needed based on bucket and keys (e.g. input/output S3 locations)
        "--SOURCE_LOCATION": f"s3://{bucket}/pre-stage/{team}/{dataset}",
        "--OUTPUT_LOCATION": f"s3://{bucket}/post-stage/{team}/{dataset}",
        "--job-bookmark-option": "job-bookmark-enable",
    }
    logger.info(f"Pipeline is {pipeline}, stage is {stage}")
    if pipeline in transform_info.get("pipeline", {}):
        if stage in transform_info["pipeline"][pipeline]:
            logger.info(f"Details from DynamoDB: {transform_info['pipeline'][pipeline][stage]}")
            job_name = transform_info["pipeline"][pipeline][stage].get("job_name", job_name)
            glue_capacity = transform_info["pipeline"][pipeline][stage].get("glue_capacity", glue_capacity)
            wait_time = transform_info["pipeline"][pipeline][stage].get("wait_time", wait_time)
            glue_arguments |= transform_info["pipeline"][pipeline][stage].get("glue_extra_arguments", {})

    return {"job_name": job_name, "wait_time": wait_time, "arguments": glue_arguments, **glue_capacity}


def lambda_handler(event, context):
    """Calls custom transform developed by user

    Arguments:
        event {dict} -- Dictionary with details on previous processing step
        context {dict} -- Dictionary with details on Lambda context

    Returns:
        {dict} -- Dictionary with Processed Bucket and Key(s)
    """
    try:
        logger.info("Fetching event data from previous step")
        bucket = event["body"]["bucket"]
        team = event["body"]["team"]
        pipeline = event["body"]["pipeline"]
        stage = event["body"]["pipeline_stage"]
        dataset = event["body"]["dataset"]

        logger.info("Initializing Octagon client")
        component = context.function_name.split("-")[-2].title()
        octagon_client = (
            octagon.OctagonClient().with_run_lambda(True).with_configuration_instance(event["body"]["env"]).build()
        )
        peh_id = octagon_client.start_pipeline_execution(
            pipeline_name="{}-{}-{}".format(team, pipeline, stage),
            dataset_name="{}-{}".format(team, dataset),
            comment=event,
        )

        # Call custom transform created by user and process the file
        logger.info("Calling user custom processing code")
        event["body"]["glue"] = get_glue_transform_details(
            bucket, team, dataset, pipeline, stage
        )  # custom user code called
        event["body"]["glue"]["crawler_name"] = "-".join(["sdlf", team, dataset, "post-stage-crawler"])
        event["body"]["peh_id"] = peh_id
        octagon_client.update_pipeline_execution(
            status="{} {} Processing".format(stage, component), component=component
        )
    except Exception as e:
        logger.error("Fatal error", exc_info=True)
        octagon_client.end_pipeline_execution_failed(
            component=component,
            issue_comment="{} {} Error: {}".format(stage, component, repr(e)),
        )
        raise e
    return event
