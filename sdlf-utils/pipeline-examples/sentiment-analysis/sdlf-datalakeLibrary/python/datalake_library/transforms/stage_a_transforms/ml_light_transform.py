#######################################################
# Blueprint example of a custom transformation
# where a JSON file is dowloaded from RAW to /tmp
# then parsed before being re-uploaded to STAGE
#######################################################
# License: Apache 2.0
#######################################################
# Author: antonkuk
#######################################################

#######################################################
# Import section
# sdlf-pipLibrary repository can be leveraged
# to add external libraries as a layer if need be
#######################################################
import pandas as pd
import boto3
import io
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
s3client = boto3.client("s3")


class CustomTransform():
    def __init__(self):
        logger.info("S3 Light Transform initiated")

    def transform_object(self, bucket, key, team, dataset):

        # Apply business business logic:
        # Below example is opening a JSON file with Pandas
        # and extracting fields, then saving the file
        # locally and re-uploading to Stage bucket

        # Reading file into DataFrame from raw bucket
        #   Bucket: Raw Bucket in S3
        #   Key : (e.g. /engineering/reviews/reviews.json)
        obj = s3client.get_object(Bucket=bucket, Key=key)
        reviews_data = pd.read_json(io.BytesIO(obj["Body"].read()))
        reviews_data.dropna(subset=["review_text"], inplace=True)
        reviews_data_clean = reviews_data[["username", "email", "review_text"]]

        # Get the KMS Key to encrypt the data we ultimately write to s3
        kms_key = KMSConfiguration(team).get_kms_arn

        # Now we add each abstract text as a new file in the s3 directory
        docnames = []
        filename = key.split("/")[-1].split(".json")[0]
        for index, row in reviews_data_clean.iterrows():

            f_path = "{}_{}.txt".format(filename, str(index))
            docnames.append(f_path)
            with open("/tmp/" + f_path, "w", encoding="utf-8") as file:
                file.write(reviews_data_clean["review_text"][index])
                file.close()
            s3_path_docs = "pre-stage/{}/{}/reviews/{}".format(
                team, dataset, f_path)
            s3_interface.upload_object(
                "/tmp/" + f_path, stage_bucket, s3_path_docs, kms_key=kms_key)

        # Return the location of the s3 text files we wrote for the Sentiment Analysis Job
        # IMPORTANT S3 path(s) must be stored in a list

        processed_keys = [s3_path_docs]

        #######################################################
        # IMPORTANT
        # This function must return a Python list
        # of transformed S3 paths. Example:
        # ["pre-stage/engineering/reviews/reviews/"]
        #######################################################

        return processed_keys
