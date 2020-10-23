#######################################################
# Blueprint example of a custom transformation
# where a column is added to a CloudFront log file
# then transformed to CSV before being uploaded to STAGE
#######################################################
# License: Apache 2.0
#######################################################
# Author: jaidi
#######################################################

import csv

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


class CustomTransform():
    def __init__(self):
        logger.info("S3 CloudFront Transform initiated")

    def transform_object(self, bucket, key, team, dataset):

        def http_outcome(status_code):
            if status_code == '200':
                return 'success'
            else:
                return 'error'

        local_path = s3_interface.download_object(bucket, key)
        output_path = "{}_transformed.csv".format(local_path.split('.')[0])
        fh = open(output_path, "w")
        with open(local_path) as fd:
            rd = csv.reader(fd, delimiter="\t", quotechar='"')
            for row in rd:
                fh.write('{}\t{}\n'.format(
                    '\t'.join(row), http_outcome(row[8])))
        fh.close()

        # Uploading file to Stage bucket at appropriate path
        # IMPORTANT: Build the output s3_path without the s3://stage-bucket/
        s3_path = 'pre-stage/{}/{}/{}'.format(team,
                                              dataset, output_path.split('/')[2])
        # IMPORTANT: Notice "stage_bucket" not "bucket"
        kms_key = KMSConfiguration(team).get_kms_arn
        s3_interface.upload_object(
            output_path, stage_bucket, s3_path, kms_key=kms_key)
        # IMPORTANT S3 path(s) must be stored in a list
        processed_keys = [s3_path]

        #######################################################
        # IMPORTANT
        # This function must return a Python list
        # of transformed S3 paths. Example:
        # ['pre-stage/engineering/clf/log1_transformed.csv','pre-stage/engineering/clf/log2_transformed.csv']
        #######################################################

        return processed_keys
