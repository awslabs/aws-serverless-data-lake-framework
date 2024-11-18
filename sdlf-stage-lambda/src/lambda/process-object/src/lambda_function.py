import json
import os
from pathlib import PurePath

from datalake_library.commons import init_logger
from datalake_library.sdlf import (
    KMSConfiguration,
    S3Configuration,
)
from datalake_library.interfaces.s3_interface import S3Interface

logger = init_logger(__name__)
dataset = os.environ["DATASET"]
pipeline = os.environ["PIPELINE"]
pipeline_stage = os.environ["PIPELINE_STAGE"]
org = os.environ["ORG"]
domain = os.environ["DOMAIN"]
storage_deployment_instance = os.environ["STORAGE_DEPLOYMENT_INSTANCE"]


def transform_object(bucket, key):
    s3_interface = S3Interface()
    # IMPORTANT: Stage bucket where transformed data must be uploaded
    stage_bucket = S3Configuration(instance=storage_deployment_instance).stage_bucket
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
    s3_path = f"{dataset}/{pipeline}/{pipeline_stage}/{PurePath(output_path).name}"
    # IMPORTANT: Notice "stage_bucket" not "bucket"
    kms_key = KMSConfiguration(instance=storage_deployment_instance).data_kms_key
    s3_interface.upload_object(output_path, stage_bucket, s3_path, kms_key=kms_key)

    return s3_path


def lambda_handler(event, context):
    """Calls custom transform developed by user

    Arguments:
        event {dict} -- Dictionary with details on previous processing step
        context {dict} -- Dictionary with details on Lambda context

    Returns:
        {dict} -- Dictionary with Processed Bucket and Key(s)
    """
    try:
        # this default Lambda expects records to be S3 events
        for record in event:
            logger.info(f"Processing file: {record['object']['key']} in {record['bucket']['name']}")
            try:
                transform_object(record["bucket"]["name"], record["object"]["key"])
                record["processed"] = True
            except json.decoder.JSONDecodeError as e:
                record["processed"] = False
                record["error"] = repr(e)

    except Exception as e:
        logger.error("Fatal error", exc_info=True)
        raise e

    return event
