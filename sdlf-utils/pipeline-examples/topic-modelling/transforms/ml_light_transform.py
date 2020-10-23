#######################################################
# Blueprint example of a custom transformation
# where a JSON file is dowloaded from RAW to /tmp
# then parsed before being re-uploaded to STAGE
#######################################################
# License: Apache 2.0
#######################################################
# Author: noahpaig
#######################################################

#######################################################
# Import section
# sdlf-pipLibrary repository can be leveraged
# to add external libraries as a layer if need be
#######################################################
import pandas as pd
import csv
from datetime import datetime
import os
import shutil
import boto3
import io
from langdetect import detect
#######################################################
# Use S3 Interface to interact with S3 objects
# For example to download/upload them
#######################################################
from datalake_library.commons import init_logger
from datalake_library.configuration.resource_configs import S3Configuration, KMSConfiguration
from datalake_library.interfaces.s3_interface import S3Interface

s3_interface = S3Interface()
# IMPORTANT: Stage bucket where transformed data must be uploaded
stage_bucket = S3Configuration().stage_bucket

logger = init_logger(__name__)
s3client = boto3.client('s3')


class CustomTransform():
    def __init__(self):
        logger.info("S3 Blueprint Light Transform initiated")

    def transform_object(self, bucket, key, team, dataset):

        # Apply business business logic:
        # Below example is opening a csv file with Pandas
        # and extracting fields, then saving the file
        # locally and re-uploading to Stage bucket

        # Reading file into DataFrame from raw bucket
        #   Bucket: Raw Bucket in S3
        #   Key : (e.g. /engineering/medicalresearch/data.csv)
        obj = s3client.get_object(Bucket=bucket, Key=key)
        medical_data = pd.read_csv(io.BytesIO(obj['Body'].read()))
        medical_data.dropna(subset=["abstract"], inplace=True)
        medical_data_clean = medical_data[[
            'title', 'abstract', 'url', 'publish_time', 'authors']]

        # Get the KMS Key to encrypt the data we ultimately write to s3
        kms_key = KMSConfiguration(team).get_kms_arn

        # Now we add each abstract text as a new file in the s3 directory
        docnames = []
        filename = key.split('/')[-1].split('.csv')[0]
        for index, row in medical_data_clean.iterrows():

            # Detect Language of the abstract and write txt file (if not English we drop the row)
            # NOTE: Only one language will both help Topic Model Results and
            # MultiLabel Classifier Must Specify Language
            try:
                language = detect(medical_data_clean['abstract'][index])
            except Exception as e:
                language = ''

            if language == 'en':
                f_path = 'abstract_doc_{}_{}.txt'.format(filename, str(index))
                docnames.append(f_path)
                with open('/tmp/' + f_path, 'w', encoding='utf-8') as file:
                    file.write(medical_data_clean["abstract"][index])
                    file.close()
                s3_path_docs = 'pre-stage/{}/{}/abstract_documents/{}'.format(
                    team, dataset, f_path)
                s3_interface.upload_object(
                    '/tmp/' + f_path, stage_bucket, s3_path_docs, kms_key=kms_key)

            # Else if not English we drop the row
            else:
                medical_data_clean.drop(index=index, inplace=True)

        # Adding the unique docnames to  each of the files we saved in s3
        # So that we can later match docnames metadata to their topic output
        medical_data_clean['docname'] = docnames

        # Saving Metadata by appending to existing csv in s3
        output_path = "{}_cleaned.csv".format(filename)
        medical_data_clean.to_csv("/tmp/" + output_path, index=True)

        # Uploading file to Stage bucket at appropriate path
        # IMPORTANT: Build the output s3_path without the s3://stage-bucket/
        s3_path = 'pre-stage/{}/{}/medical_data/{}'.format(
            team, dataset, output_path)
        # IMPORTANT: Notice "stage_bucket" not "bucket"
        s3_interface.upload_object(
            "/tmp/" + output_path, stage_bucket, s3_path, kms_key=kms_key)

        # Return the location of the s3 text files we wrote for the Topic Model Job
        # IMPORTANT S3 path(s) must be stored in a list

        processed_keys = [s3_path]

        #######################################################
        # IMPORTANT
        # This function must return a Python list
        # of transformed S3 paths. Example:
        # ['pre-stage/engineering/medicalresearch/abstract_documents/']
        #######################################################

        return processed_keys
