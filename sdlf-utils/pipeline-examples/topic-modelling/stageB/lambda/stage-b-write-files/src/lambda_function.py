import boto3
import io
from io import StringIO
import pandas as pd
from datetime import datetime
import json

from datalake_library import octagon
from datalake_library.octagon import Artifact, EventReasonEnum, peh
from datalake_library.commons import init_logger
from datalake_library.configuration.resource_configs import S3Configuration, KMSConfiguration
from datalake_library.interfaces.s3_interface import S3Interface


logger = init_logger(__name__)
s3_interface = S3Interface()
s3client = boto3.client('s3')


def lambda_handler(event, context):
    """Crawl Data using specified Glue Crawler

    Arguments:
        event {dict} -- Dictionary with details on Bucket and Keys
        context {dict} -- Dictionary with details on Lambda context

    Returns:
        {dict} -- Dictionary with Processed Bucket and Keys Path
    """
    try:
        # Get Information on Start/End and s3 Locations from Parent Lambda
        logger.info('Fetching event data from previous step')
        start = event["start"]
        end = event["end"]
        key = event["key"]
        bucket = event["bucket"]
        directory_key = event["directory_key"]
        team = event["team"]
        dataset = event["dataset"]
        
        
        # Get KMS Key to Encrypt Data on Uplaod
        kms_key = KMSConfiguration(team).get_kms_arn
        
        # Read in metadata and topics to a DataFrame
        key = "post-stage/{}/{}/compile_topics_data.csv".format(team, dataset)
        obj = s3client.get_object(Bucket=bucket, Key=key)
        metadata = pd.read_csv(io.BytesIO(obj['Body'].read()), encoding='utf8')

        # For the range of rows repsonsible, write the metadata in json format to the 
        # metadata directory
        for index in range(int(start),int(end)):
            try:
                l=(metadata["authors"][index]).split(";")
            except:
                l = [""]
                    
            data = {
                "_authors": l,
                "_document_title":metadata["title"][index],
                "_category": metadata["term_list"][index][0],
                "_source_uri": metadata["url"][index],
                "publish_date": metadata["publish_time"][index],
                "subcategories": metadata["term_list"][index][1:]
            }
                
            filename = metadata["docname"][index] + ".metadata.json"
            with open ('/tmp/' + filename, 'w') as file:
                json.dump(data, file)
                file.close()
            s3_path_docs = 'pre-stage/{}/{}/datasource_metadata/{}'.format(team, dataset, filename)
            s3_interface.upload_object('/tmp/' + filename, bucket, s3_path_docs, kms_key=kms_key)
        
        
            
    except Exception as e:
        logger.error("Fatal error", exc_info=True)
        raise e
    return 200