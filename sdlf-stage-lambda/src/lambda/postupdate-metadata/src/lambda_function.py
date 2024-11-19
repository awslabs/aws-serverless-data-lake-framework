import os

from datalake_library.sdlf import PipelineExecutionHistoryAPI
from datalake_library.commons import init_logger

logger = init_logger(__name__)
dataset = os.environ["DATASET"]
pipeline = os.environ["PIPELINE"]
pipeline_stage = os.environ["PIPELINE_STAGE"]
org = os.environ["ORG"]
domain = os.environ["DOMAIN"]
deployment_instance = os.environ["DEPLOYMENT_INSTANCE"]
object_metadata_table_instance = os.environ["STORAGE_DEPLOYMENT_INSTANCE"]
peh_table_instance = os.environ["DATASET_DEPLOYMENT_INSTANCE"]
manifests_table_instance = os.environ["DATASET_DEPLOYMENT_INSTANCE"]


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
        pipeline_execution = PipelineExecutionHistoryAPI(run_in_context="LAMBDA", region=os.getenv("AWS_REGION"), object_metadata_table_instance=object_metadata_table_instance, peh_table_instance=peh_table_instance, manifests_table_instance=manifests_table_instance)
        peh_id = event[0]["run_output"][0]["transform"]["peh_id"]
        pipeline_execution.retrieve_pipeline_execution(peh_id)

        partial_failure = False
        # for records in event:
        #     for record in records:
        #         if "processed" not in record or not record["processed"]:
        #             partial_failure = True

        if not partial_failure:
            pipeline_execution.update_pipeline_execution(
                status=f"{pipeline}-{pipeline_stage} {component} Processing", component=component
            )
            pipeline_execution.end_pipeline_execution_success()
        else:
            raise Exception("Failure: Processing failed for one or more record")

    except Exception as e:
        logger.error("Fatal error", exc_info=True)
        pipeline_execution.end_pipeline_execution_failed(
            component=component, issue_comment=f"{pipeline}-{pipeline_stage} {component} Error: {repr(e)}"
        )
        raise e
