import os

from datalake_library import octagon
from datalake_library.commons import init_logger
from datalake_library.octagon import peh

logger = init_logger(__name__)
team = os.environ["TEAM"]
dataset = os.environ["DATASET"]
pipeline = os.environ["PIPELINE"]
pipeline_stage = os.environ["PIPELINE_STAGE"]
org = os.environ["ORG"]
domain = os.environ["DOMAIN"]
env = os.environ["ENV"]


def lambda_handler(event, context):
    """Updates the S3 objects metadata catalog

    Arguments:
        event {dict} -- Dictionary with details on previous processing step
        context {dict} -- Dictionary with details on Lambda context

    Returns:
        {dict} -- Dictionary with outcome of the process
    """
    try:
        logger.info("Initializing Octagon client")
        component = context.function_name.split("-")[-2].title()
        octagon_client = octagon.OctagonClient().with_run_lambda(True).with_configuration_instance(env).build()
        peh_id = event[0]["Items"][0]["transform"]["peh_id"]
        peh.PipelineExecutionHistoryAPI(octagon_client).retrieve_pipeline_execution(peh_id)

        partial_failure = False
        for records in event:
            for record in records:
                if "processed" not in record or not record["processed"]:
                    partial_failure = True

        if not partial_failure:
            octagon_client.update_pipeline_execution(
                status="{} {} Processing".format(pipeline_stage, component), component=component
            )
            octagon_client.end_pipeline_execution_success()
        else:
            raise Exception("Failure: Processing failed for one or more record")

    except Exception as e:
        logger.error("Fatal error", exc_info=True)
        octagon_client.end_pipeline_execution_failed(
            component=component, issue_comment=f"{pipeline_stage} {component} Error: {repr(e)}"
        )
        raise e
