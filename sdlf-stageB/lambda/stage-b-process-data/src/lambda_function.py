import os
import shutil

from datalake_library import octagon
from datalake_library.commons import init_logger
from datalake_library.octagon import Artifact, EventReasonEnum, peh
from datalake_library.transforms.transform_handler import TransformHandler

logger = init_logger(__name__)


def remove_content_tmp():
    # Remove contents of the Lambda /tmp folder (Not released by default)
    for root, dirs, files in os.walk("/tmp"):
        for f in files:
            os.unlink(os.path.join(root, f))
        for d in dirs:
            shutil.rmtree(os.path.join(root, d))


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
        keys_to_process = event["body"]["keysToProcess"]
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
            pipeline_name="{}-{}-stage-{}".format(team, pipeline, stage[-1].lower()),
            dataset_name="{}-{}".format(team, dataset),
            comment=event,
        )

        # Call custom transform created by user and process the file
        logger.info("Calling user custom processing code")
        transform_handler = TransformHandler().stage_transform(team, dataset, stage)
        response = transform_handler().transform_object(
            bucket, keys_to_process, team, dataset
        )  # custom user code called
        response["peh_id"] = peh_id
        remove_content_tmp()
        octagon_client.update_pipeline_execution(
            status="{} {} Processing".format(stage, component), component=component
        )
    except Exception as e:
        logger.error("Fatal error", exc_info=True)
        octagon_client.end_pipeline_execution_failed(
            component=component, issue_comment="{} {} Error: {}".format(stage, component, repr(e))
        )
        remove_content_tmp()
        raise e
    return response
