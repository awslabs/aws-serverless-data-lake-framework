import boto3
from datalake_library import octagon
from datalake_library.commons import init_logger
from datalake_library.octagon import Artifact, EventReasonEnum, peh

logger = init_logger(__name__)
client = boto3.client("glue")


def lambda_handler(event, context):
    """Crawl Data using specified Glue Crawler

    Arguments:
        event {dict} -- Dictionary with details on Bucket and Keys
        context {dict} -- Dictionary with details on Lambda context

    Returns:
        {dict} -- Dictionary with Processed Bucket and Keys Path
    """
    try:
        logger.info("Fetching event data from previous step")
        team = event["body"]["team"]
        stage = event["body"]["pipeline_stage"]
        dataset = event["body"]["dataset"]

        logger.info("Initializing Octagon client")
        component = context.function_name.split("-")[-2].title()
        octagon_client = (
            octagon.OctagonClient().with_run_lambda(True).with_configuration_instance(event["body"]["env"]).build()
        )
        peh.PipelineExecutionHistoryAPI(octagon_client).retrieve_pipeline_execution(event["body"]["job"]["peh_id"])

        crawler_name = "-".join(["sdlf", team, dataset, "post-stage-crawler"])
        logger.info("Starting Crawler {}".format(crawler_name))
        try:
            client.start_crawler(Name=crawler_name)
        except client.exceptions.CrawlerRunningException:
            logger.info("Crawler is already running")
        octagon_client.update_pipeline_execution(
            status="{} {} Processing".format(stage, component), component=component
        )
    except Exception as e:
        logger.error("Fatal error", exc_info=True)
        octagon_client.end_pipeline_execution_failed(
            component=component, issue_comment="{} {} Error: {}".format(stage, component, repr(e))
        )
        raise e
    return 200
