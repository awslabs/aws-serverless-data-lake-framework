import os
import json
import boto3
import shutil
import tarfile

from io import BytesIO
from datalake_library.commons import init_logger
from datalake_library import octagon
from datalake_library.octagon import Artifact, EventReasonEnum, peh
from datalake_library.interfaces.s3_interface import S3Interface
from datalake_library.configuration.resource_configs import S3Configuration, KMSConfiguration

logger = init_logger(__name__)
s3client = boto3.client("s3")
s3_interface = S3Interface()
stage_bucket = S3Configuration().stage_bucket


def remove_content_tmp():
    # Remove contents of the Lambda /tmp folder (Not released by default)
    for root, dirs, files in os.walk('/tmp'):
        for f in files:
            os.unlink(os.path.join(root, f))
        for d in dirs:
            shutil.rmtree(os.path.join(root, d))


def lambda_handler(event, context):
    """Process Comprehend Output

    Arguments:
        event {dict} -- Dictionary with details on previous processing step
        context {dict} -- Dictionary with details on Lambda context

    Returns:
        {dict} -- Dictionary with Processed Bucket and Key(s)
    """
    try:
        logger.info('Fetching event data from previous step')
        bucket = event['body']['bucket']
        keys_to_process = event['body']['keysToProcess']
        team = event['body']['team']
        pipeline = event['body']['pipeline']
        stage = event['body']['pipeline_stage']
        dataset = event['body']['dataset']
        job_details = event['body']['job']['jobDetails']

        logger.info('Initializing Octagon client')
        component = context.function_name.split('-')[-2].title()
        octagon_client = (
            octagon.OctagonClient()
            .with_run_lambda(True)
            .with_configuration_instance(event['body']['env'])
            .build()
        )
        peh_id = octagon_client.start_pipeline_execution(
            pipeline_name='{}-{}-stage-{}'.format(team,
                                                  pipeline, stage[-1].lower()),
            dataset_name='{}-{}'.format(team, dataset),
            comment=event
        )

        s3_uri = job_details["outputDataConfig"]["S3Uri"]
        s3_key = '/'.join(s3_uri.split('/')[3:])
        temp_path = "/tmp/"
        temp_input_filename = temp_path + "output"
        temp_output_filename = temp_path + "output.json"

        # Untar the file
        obj = s3client.get_object(Bucket=bucket, Key=s3_key)
        with tarfile.open(fileobj=BytesIO(obj['Body'].read())) as tar:
            tar.extractall(path=temp_path)

        # Parse JSON lines and unnest
        output_str = ""
        with open(temp_input_filename) as f:
            for line in f:
                row = json.loads(line)
                for sentiment_key, sentiment_score in row["SentimentScore"].items():
                    row[sentiment_key + "_score"] = sentiment_score
                del row["SentimentScore"]
                output_str += json.dumps(row) + "\n"

        # Write output
        with open(temp_output_filename, "w") as f:
            f.write(output_str)

        # Upload output to S3 as output.json
        kms_key = KMSConfiguration(team).get_kms_arn
        s3_output_path = "post-stage/{}/{}/sentiments/output.json".format(team, dataset)
        s3_interface.upload_object(temp_output_filename, stage_bucket, s3_output_path, kms_key=kms_key)

        # Delete tar archive
        s3client.delete_object(Bucket=bucket, Key=s3_key)

        response = {
            'processed_keys': 's3_output_path',
            'peh_id': peh_id
        }
        remove_content_tmp()
        octagon_client.update_pipeline_execution(
            status="{} {} Processing".format(stage, component), component=component)
    except Exception as e:
        logger.error("Fatal error", exc_info=True)
        octagon_client.end_pipeline_execution_failed(component=component,
                                                     issue_comment="{} {} Error: {}".format(stage, component, repr(e)))
        remove_content_tmp()
        raise e
    return response
