#######################################################
# Manifest Blueprint example of a custom transformation
# where a file is copied from RAW to STAGE
# Any ligth tranformation logic can be applied here
#######################################################
# License: Apache 2.0
#######################################################
# Author: moumajhi
#######################################################

#######################################################
# Import section
# common-pipLibrary repository can be leveraged
# to add external libraries as a layer if need be
#######################################################


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
        logger.info("S3 Blueprint Light Transform initiated")

    def transform_object(self, bucket, key, team, dataset):
        # Copy the s3 object from raw to stage
        s3_path = 'pre-stage/{}/{}/{}'.format(team,
                                              dataset, key.split('/')[-1])        
        

        kms_key = KMSConfiguration(team).get_kms_arn
        s3_interface.copy_object(
            bucket, key,stage_bucket ,s3_path, kms_key=kms_key)
        # IMPORTANT S3 path(s) must be stored in a list
        processed_keys = [s3_path]

        #######################################################
        # IMPORTANT
        # This function must return a Python list
        # of transformed S3 paths. Example:
        # ['pre-stage/engineering/legislators/persons_parsed.json']
        #######################################################

        return processed_keys
