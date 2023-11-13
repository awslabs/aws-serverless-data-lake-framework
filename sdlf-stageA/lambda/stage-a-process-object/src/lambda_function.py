import json
from pathlib import PurePath

from datalake_library import octagon
from datalake_library.commons import init_logger
from datalake_library.configuration.resource_configs import (
    KMSConfiguration,
    S3Configuration,
)
from datalake_library.interfaces.s3_interface import S3Interface
from datalake_library.octagon import peh

logger = init_logger(__name__)


def transform_object(bucket, key, team, dataset):
    s3_interface = S3Interface()
    # IMPORTANT: Stage bucket where transformed data must be uploaded
    stage_bucket = S3Configuration().stage_bucket
    # Download S3 object locally to /tmp directory
    # The s3_helper.download_object method
    # returns the local path where the file was saved
    local_path = s3_interface.download_object(bucket, key)

    # Apply business business logic:
    # Below example is opening a JSON file and
    # extracting fields, then saving the file
    # locally and re-uploading to Stage bucket
    def parse(json_data):
        l = []  # noqa: E741
        for d in json_data:
            o = d.copy()
            for k in d:
                if type(d[k]) in [dict, list]:
                    o.pop(k)
            l.append(o)

        return l

    # Reading file locally
    with open(local_path, "r") as raw_file:
        data = raw_file.read()

    json_data = json.loads(data)

    # Saving file locally to /tmp after parsing
    output_path = f"{PurePath(local_path).with_suffix('')}_parsed.json"
    with open(output_path, "w", encoding="utf-8") as write_file:
        json.dump(parse(json_data), write_file, ensure_ascii=False, indent=4)

    # Uploading file to Stage bucket at appropriate path
    # IMPORTANT: Build the output s3_path without the s3://stage-bucket/
    s3_path = f"pre-stage/{team}/{dataset}/{PurePath(output_path).name}"
    # IMPORTANT: Notice "stage_bucket" not "bucket"
    kms_key = KMSConfiguration(team).get_kms_arn
    s3_interface.upload_object(output_path, stage_bucket, s3_path, kms_key=kms_key)
    # IMPORTANT S3 path(s) must be stored in a list
    processed_keys = [s3_path]

    #######################################################
    # IMPORTANT
    # This function must return a Python list
    # of transformed S3 paths. Example:
    # ['pre-stage/engineering/legislators/persons_parsed.json']
    #######################################################

    return processed_keys


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
        key = event["body"]["key"]
        team = event["body"]["team"]
        stage = event["body"]["pipeline_stage"]
        dataset = event["body"]["dataset"]

        logger.info("Initializing Octagon client")
        component = context.function_name.split("-")[-2].title()
        octagon_client = (
            octagon.OctagonClient().with_run_lambda(True).with_configuration_instance(event["body"]["env"]).build()
        )
        peh.PipelineExecutionHistoryAPI(octagon_client).retrieve_pipeline_execution(event["body"]["peh_id"])

        # Call custom transform created by user and process the file
        logger.info("Calling user custom processing code")
        event["body"]["processedKeys"] = transform_object(bucket, key, team, dataset)
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
