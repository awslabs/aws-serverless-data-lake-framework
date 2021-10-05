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
s3client = boto3.client('s3')
s3_interface = S3Interface()
stage_bucket = S3Configuration().stage_bucket


def remove_content_tmp():
    # Remove contents of the Lambda /tmp folder (Not released by default)
    for root, dirs, files in os.walk('/tmp'):
        for f in files:
            os.unlink(os.path.join(root, f))
        for d in dirs:
            shutil.rmtree(os.path.join(root, d))


def process_sentiments_row(row):
    for sentiment_key, sentiment_score in row["SentimentScore"].items():
        row[sentiment_key + "_score"] = sentiment_score
    del row["SentimentScore"]


def process_key_phrases_row(row):
    for key_phrase in row["KeyPhrases"]:
        key_phrase["File"] = row["File"]
    return row["KeyPhrases"]


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
        response = {
            'processed_keys': [],
            'peh_id': peh_id
        }

        for analysis_type, job_detail in zip(['sentiments', 'key_phrases'],
            [job_details['SentimentDetection'],  job_details['KeyPhrasesDetection']]):

            s3_uri = job_detail['outputDataConfig']['S3Uri']
            s3_key = '/'.join(s3_uri.split('/')[3:])
            temp_path = '/tmp/{}/'.format(analysis_type)
            temp_input_filename = '{}/output'.format(temp_path)
            temp_output_filename = '{}/output.json'.format(temp_path)

            # Untar
            obj = s3client.get_object(Bucket=bucket, Key=s3_key)
            with tarfile.open(fileobj=BytesIO(obj['Body'].read())) as tar:
                tar.extractall(path=temp_path)

            # Parse Sentiments JSON lines file and unnest
            output_str = ''
            with open(temp_input_filename) as f:
                for line in f:
                    row = json.loads(line)
                    if analysis_type == 'sentiments':
                        process_sentiments_row(row)
                        output_str += json.dumps(row) + '\n'
                    elif analysis_type == 'key_phrases':
                        for key_phrase in process_key_phrases_row(row):
                            output_str += json.dumps(key_phrase) + '\n'
                    else:
                        raise ValueError('Unknown analysis type')

            # Write output
            with open(temp_output_filename, 'w') as f:
                f.write(output_str)

            # Upload output to S3 as output.json
            kms_key = KMSConfiguration(team).get_kms_arn
            s3_output_path = 'post-stage/{}/{}/{}/output.json'.format(team, dataset, analysis_type)
            s3_interface.upload_object(temp_output_filename, stage_bucket, s3_output_path, kms_key=kms_key)

            # Delete tar archive
            s3client.delete_object(Bucket=bucket, Key=s3_key)

            response['processed_keys'].append(s3_output_path)

        remove_content_tmp()
        octagon_client.update_pipeline_execution(
            status='{} {} Processing'.format(stage, component), component=component)
    except Exception as e:
        logger.error('Fatal error', exc_info=True)
        octagon_client.end_pipeline_execution_failed(component=component,
                                                     issue_comment='{} {} Error: {}'.format(stage, component, repr(e)))
        remove_content_tmp()
        raise e
    return response
