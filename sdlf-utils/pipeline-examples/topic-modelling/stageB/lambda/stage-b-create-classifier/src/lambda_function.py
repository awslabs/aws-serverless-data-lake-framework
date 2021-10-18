from datalake_library.commons import init_logger
from datalake_library.configuration.resource_configs import DynamoConfiguration, SQSConfiguration, KMSConfiguration
from datalake_library.interfaces.dynamo_interface import DynamoInterface
from datalake_library.interfaces.s3_interface import S3Interface
from datalake_library.interfaces.sqs_interface import SQSInterface
from datalake_library import octagon
from datalake_library.octagon import Artifact, EventReasonEnum, peh

logger = init_logger(__name__)

import boto3

def lambda_handler(event, context):
    """Updates the S3 objects metadata catalog

    Arguments:
        event {dict} -- Dictionary with details on Bucket and Keys
        context {dict} -- Dictionary with details on Lambda context

    Returns:
        {dict} -- Dictionary with response
    """
    try:
        logger.info('Fetching event data from previous step')
        bucket = event['body']['bucket']
        processed_keys_path = event['body']['job']['processedKeysPath']
        processed_keys = S3Interface().list_objects(bucket, processed_keys_path)
        team = event['body']['team']
        pipeline = event['body']['pipeline']
        stage = event['body']['pipeline_stage']
        dataset = event['body']['dataset']
        
        
        # Lastly, Lets Run Comprehend Multi-Label Classification Job 
        # with the Training Data we created earlier:
        
        # Connect to Comprehend Client
        comprehend_client = boto3.client('comprehend')
        
        # Set Parameters for Classifier Training Job and get KMS Key for Encryption
        input_key = "post-stage/{}/{}/multilabel_classification/training_data.csv".format(team, dataset)
        s3_input = "s3://{}/{}".format(bucket, input_key)
        output_key = "post-stage/{}/{}/multilabel_classification/".format(team, dataset)
        s3_output = "s3://{}/{}".format(bucket, output_key)
        
        kms_key = KMSConfiguration(team).get_kms_arn
        name = "MedicalResearchTopicClassifier"
        aws_account_id = context.invoked_function_arn.split(":")[4]
        data_access_role = 'arn:aws:iam::{}:role/sdlf-{}-{}-create-classifier-b'.format(aws_account_id, team, pipeline)

        # Call Multi-Label Classifier Training to Start
        response = comprehend_client.create_document_classifier(
            DocumentClassifierName=name,
            DataAccessRoleArn=data_access_role,
            Tags=[
                {
                    'Key': 'Framework',
                    'Value': 'sdlf'
                },
            ],
            InputDataConfig={
                'S3Uri': s3_input,
                'LabelDelimiter': '|'
            },
            OutputDataConfig={
                'S3Uri': s3_output,
                'KmsKeyId': kms_key
            },
            LanguageCode='en',
            VolumeKmsKeyId=kms_key,
            Mode='MULTI_LABEL'
        )

    except Exception as e:
        logger.error("Fatal error", exc_info=True)
        raise e
    return 200