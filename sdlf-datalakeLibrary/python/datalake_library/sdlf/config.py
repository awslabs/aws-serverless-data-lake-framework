import os

import boto3
from botocore.exceptions import ClientError

from ..commons import init_logger


class S3Configuration:
    def __init__(self, log_level=None, ssm_interface=None, instance=None):
        """
        Complementary S3 config stores the S3 specific parameters
        :param log_level: level the class logger should log at
        :param ssm_interface: ssm interface, normally boto, to read parameters from parameter store
        """
        self.log_level = log_level or os.getenv("LOG_LEVEL", "INFO")
        self._logger = init_logger(__name__, self.log_level)
        self.instance = instance

        ssm_endpoint_url = "https://ssm." + os.getenv("AWS_REGION") + ".amazonaws.com"
        self._ssm = ssm_interface or boto3.client("ssm", endpoint_url=ssm_endpoint_url)

        # self._fetch_from_environment()
        self._fetch_from_ssm()

    # def _fetch_from_environment(self):
    #     self._destination_bucket = os.getenv("BUCKET_TARGET", None)
    #     self._destination_encryption_key = os.getenv("TARGET_ENCRYPTION_KEY", None)

    def _fetch_from_ssm(self):
        self._logger.info(
            f"Reading configuration from SSM Parameter Store with configuration instance: {self.instance}"
        )
        try:
            raw_bucket_ssm = "/sdlf/storage/rRawBucket"
            self._logger.debug(f"Obtaining SSM Parameter: {raw_bucket_ssm}")
            self.raw_bucket = self._ssm.get_parameter(Name=raw_bucket_ssm)["Parameter"]["Value"]

            stage_bucket_ssm = "/sdlf/storage/rStageBucket"
            self._logger.debug(f"Obtaining SSM Parameter: {stage_bucket_ssm}")
            self.stage_bucket = self._ssm.get_parameter(Name=stage_bucket_ssm)["Parameter"]["Value"]

            analytics_bucket_ssm = "/sdlf/storage/rAnalyticsBucket"
            self._logger.debug(f"Obtaining SSM Parameter: {analytics_bucket_ssm}")
            self.analytics_bucket = self._ssm.get_parameter(Name=analytics_bucket_ssm)["Parameter"]["Value"]

            artifacts_bucket_ssm = "/sdlf/storage/rArtifactsBucket"
            self._logger.debug(f"Obtaining SSM Parameter: {artifacts_bucket_ssm}")
            self.artifacts_bucket = self._ssm.get_parameter(Name=artifacts_bucket_ssm)["Parameter"]["Value"]
        except ClientError as e:
            if e.response["Error"]["Code"] == "ThrottlingException":
                self._logger.error("SSM RATE LIMIT REACHED")
            else:
                self._logger.error("Unexpected error: %s" % e)
            raise


class DynamoConfiguration:
    def __init__(self, log_level=None, ssm_interface=None, instance=None):
        """
        Complementary Dynamo config stores the parameters required to access dynamo tables
        :param log_level: level the class logger should log at
        :param ssm_interface: ssm interface, normally boto, to read parameters from parameter store
        """
        self.log_level = log_level or os.getenv("LOG_LEVEL", "INFO")
        self._logger = init_logger(__name__, self.log_level)
        self.instance = instance

        ssm_endpoint_url = "https://ssm." + os.getenv("AWS_REGION") + ".amazonaws.com"
        self._ssm = ssm_interface or boto3.client("ssm", endpoint_url=ssm_endpoint_url)

        self._fetch_from_ssm()

    def _fetch_from_ssm(self):
        self._logger.info(
            f"Reading configuration from SSM Parameter Store with configuration instance: {self.instance}"
        )
        try:
            object_metadata_table_ssm = "/sdlf/storage/rDynamoObjectMetadata"
            self._logger.debug(f"Obtaining SSM Parameter: {object_metadata_table_ssm}")
            self.object_metadata_table = self._ssm.get_parameter(Name=object_metadata_table_ssm)["Parameter"]["Value"]

            peh_table_ssm = "/sdlf/dataset/rDynamoPipelineExecutionHistory"
            self._logger.debug(f"Obtaining SSM Parameter: {peh_table_ssm}")
            self.peh_table = self._ssm.get_parameter(Name=peh_table_ssm)["Parameter"]["Value"]

            manifests_table_ssm = "/sdlf/dataset/rDynamoManifests"
            self._logger.debug(f"Obtaining SSM Parameter: {manifests_table_ssm}")
            self.manifests_table = self._ssm.get_parameter(Name=manifests_table_ssm)["Parameter"]["Value"]
        except ClientError as e:
            if e.response["Error"]["Code"] == "ThrottlingException":
                self._logger.error("SSM RATE LIMIT REACHED")
            else:
                self._logger.error("Unexpected error: %s" % e)
            raise


class SQSConfiguration:
    def __init__(self, log_level=None, ssm_interface=None, instance=None):
        """
        Complementary SQS config stores the parameters required to access SQS
        :param log_level: level the class logger should log at
        :param ssm_interface: ssm interface, normally boto, to read parameters from parameter store
        """
        self.log_level = log_level or os.getenv("LOG_LEVEL", "INFO")
        self._logger = init_logger(__name__, self.log_level)
        self.instance = instance

        ssm_endpoint_url = "https://ssm." + os.getenv("AWS_REGION") + ".amazonaws.com"
        self._ssm = ssm_interface or boto3.client("ssm", endpoint_url=ssm_endpoint_url)

        self._fetch_from_ssm()

    def _fetch_from_ssm(self):
        self._logger.info(
            f"Reading configuration from SSM Parameter Store with configuration instance: {self.instance}"
        )
        try:
            stage_queue_ssm = "/sdlf/pipeline/rQueueRoutingStep"
            self._logger.debug(f"Obtaining SSM Parameter: {stage_queue_ssm}")
            self.stage_queue = self._ssm.get_parameter(Name=stage_queue_ssm)["Parameter"]["Value"]

            stage_dlq_ssm = "/sdlf/pipeline/rDeadLetterQueueRoutingStep"
            self._logger.debug(f"Obtaining SSM Parameter: {stage_dlq_ssm}")
            self.stage_dlq = self._ssm.get_parameter(Name=stage_dlq_ssm)["Parameter"]["Value"]
        except ClientError as e:
            if e.response["Error"]["Code"] == "ThrottlingException":
                self._logger.error("SSM RATE LIMIT REACHED")
            else:
                self._logger.error("Unexpected error: %s" % e)
            raise


class StateMachineConfiguration:
    def __init__(self, log_level=None, ssm_interface=None, instance=None):
        """
        Complementary State Machine config stores the parameters required to access State Machines
        :param log_level: level the class logger should log at
        :param ssm_interface: ssm interface, normally boto, to read parameters from parameter store
        """
        self.log_level = log_level or os.getenv("LOG_LEVEL", "INFO")
        self._logger = init_logger(__name__, self.log_level)
        self.instance = instance

        ssm_endpoint_url = "https://ssm." + os.getenv("AWS_REGION") + ".amazonaws.com"
        self._ssm = ssm_interface or boto3.client("ssm", endpoint_url=ssm_endpoint_url)

        self._fetch_from_ssm()

    def _fetch_from_ssm(self):
        self._logger.info(
            f"Reading configuration from SSM Parameter Store with configuration instance: {self.instance}"
        )
        try:
            stage_state_machine_ssm = "/sdlf/pipeline/rStateMachine"
            self._logger.debug(f"Obtaining SSM Parameter: {stage_state_machine_ssm}")
            self.stage_state_machine = self._ssm.get_parameter(Name=stage_state_machine_ssm)["Parameter"]["Value"]
        except ClientError as e:
            if e.response["Error"]["Code"] == "ThrottlingException":
                self._logger.error("SSM RATE LIMIT REACHED")
            else:
                self._logger.error("Unexpected error: %s" % e)
            raise


class KMSConfiguration:
    def __init__(self, log_level=None, ssm_interface=None, instance=None):
        """
        Complementary KMS config stores the parameters required to access CMKs
        :param log_level: level the class logger should log at
        :param ssm_interface: ssm interface, normally boto, to read parameters from parameter store
        """
        self.log_level = log_level or os.getenv("LOG_LEVEL", "INFO")
        self._logger = init_logger(__name__, self.log_level)
        self.instance = instance

        ssm_endpoint_url = "https://ssm." + os.getenv("AWS_REGION") + ".amazonaws.com"
        self._ssm = ssm_interface or boto3.client("ssm", endpoint_url=ssm_endpoint_url)

        self._fetch_from_ssm()

    def _fetch_from_ssm(self):
        self._logger.info(
            f"Reading configuration from SSM Parameter Store with configuration instance: {self.instance}"
        )
        try:
            data_kms_key_ssm = "/sdlf/dataset/rKMSDataKey"
            self._logger.debug(f"Obtaining SSM Parameter: {data_kms_key_ssm}")
            self.data_kms_key = self._ssm.get_parameter(Name=data_kms_key_ssm)["Parameter"]["Value"]
        except ClientError as e:
            if e.response["Error"]["Code"] == "ThrottlingException":
                self._logger.error("SSM RATE LIMIT REACHED")
            else:
                self._logger.error("Unexpected error: %s" % e)
            raise
