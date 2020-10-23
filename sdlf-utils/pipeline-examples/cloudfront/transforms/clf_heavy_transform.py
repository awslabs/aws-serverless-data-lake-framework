#######################################################
# Blueprint example of a custom transformation
# where EMR steps are defined (including Deequ) to
# process CloudFront logs from pre to post-stage
#######################################################
# License: Apache 2.0
#######################################################
# Author: jaidi
#######################################################

#######################################################
# Import section
# sdlf-pipLibrary repository can be leveraged
# to add external libraries as a layer
#######################################################
import json
import datetime as dt

import boto3

from datalake_library.commons import init_logger
from datalake_library.configuration.resource_configs import S3Configuration

# Fetching the Artifacts bucket where Hive and Spark scripts are defined
artifacts_bucket = S3Configuration().artifacts_bucket

logger = init_logger(__name__)


class CustomTransform():
    def __init__(self):
        logger.info("Glue Job Blueprint Heavy Transform initiated")

    def transform_object(self, bucket, keys, team, dataset):
        # Defining the S3 output path
        processed_keys_path = 'post-stage/{}/{}'.format(team, dataset)

        # Defining the EMR steps parameters
        job_details = {
            "createCluster": "true",
            "terminateCluster": "true",
            "logUri": "s3://{}/{}/{}/elasticmapreduce/logs/".format(artifacts_bucket, team, dataset),
            "securityConfiguration":  "sdlf-{}-emr-security-config".format(team),
            "bootstrapActions": "s3://{}/{}/{}/elasticmapreduce/scripts/bootstrap.sh".format(artifacts_bucket, team, dataset),
            "step1": [
                "spark-submit",
                "--deploy-mode",
                "client",
                      "--conf",
                      "spark.jars=/home/hadoop/deequ-1.0.1.jar",
                      "--class",
                      "dqs.DqsDriver",
                      "s3://{}/{}/{}/elasticmapreduce/scripts/dqstest_2.11-1.0.jar".format(
                          artifacts_bucket, team, dataset),
                      "healthy",
                      "2018-08-04",
                      "s3://{}/{}/{}/elasticmapreduce/deequ-metrics/metrics-repository/".format(
                          artifacts_bucket, team, dataset)
            ],
            "step2": [
                "hive-script",
                "--run-hive-script",
                "--args",
                "-f",
                "s3://eu-west-1.elasticmapreduce.samples/cloudfront/code/Hive_CloudFront.q",
                "-d",
                "INPUT=s3://eu-west-1.elasticmapreduce.samples",
                "-d",
                "OUTPUT=s3://{}/{}/".format(bucket,
                                            processed_keys_path)
            ],
            "step3": [
                "hive-script",
                "--run-hive-script",
                "--args",
                "-f",
                "s3://{}/{}/{}/elasticmapreduce/scripts/clf_hive.q".format(
                    artifacts_bucket, team, dataset),
                "-d",
                "INPUT=s3://{}/{}".format(bucket,
                                          keys[0].rsplit('/', 1)[0]),
                "-d",
                "OUTPUT=s3://{}/{}/".format(bucket,
                                            processed_keys_path)
            ]
        }

        response = {
            'processedKeysPath': processed_keys_path,
            'jobDetails': job_details
        }

        return response
