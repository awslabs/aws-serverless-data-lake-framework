import os

import boto3

from ..commons import init_logger
from .base_config import BaseConfig


class S3Configuration(BaseConfig):
    def __init__(self, log_level=None, ssm_interface=None):
        """
        Complementary S3 config stores the S3 specific parameters
        :param log_level: level the class logger should log at
        :param ssm_interface: ssm interface, normally boto, to read parameters from parameter store
        """
        self.log_level = log_level or os.getenv("LOG_LEVEL", "INFO")
        self._logger = init_logger(__name__, self.log_level)
        self._ssm = ssm_interface or boto3.client("ssm")
        super().__init__(self.log_level, self._ssm)

        self._fetch_from_environment()
        self._fetch_from_ssm()

    def _fetch_from_environment(self):
        self._destination_bucket = os.getenv("BUCKET_TARGET", None)
        self._destination_encryption_key = os.getenv("TARGET_ENCRYPTION_KEY", None)

    def _fetch_from_ssm(self):
        self._artifacts_bucket = None
        self._raw_bucket = None
        self._raw_bucket_kms_key = None
        self._stage_bucket = None
        self._stage_bucket_kms_key = None
        self._analytics_bucket = None
        self._analytics_bucket_kms_key = None

    @property
    def destination_bucket(self):
        return self._destination_bucket

    @property
    def destination_encryption_key(self):
        return self._destination_encryption_key

    @property
    def artifacts_bucket(self):
        if not self._artifacts_bucket:
            self._artifacts_bucket = self._get_ssm_param("/SDLF/S3/ArtifactsBucket")
        return self._artifacts_bucket

    @property
    def raw_bucket(self):
        if not self._raw_bucket:
            self._raw_bucket = self._get_ssm_param("/SDLF/S3/CentralBucket")
        return self._raw_bucket

    @property
    def raw_bucket_kms_key(self):
        if not self._raw_bucket_kms_key:
            self._raw_bucket_kms_key = self._get_ssm_param("/SDLF/KMS/CentralBucket")
        return self._raw_bucket_kms_key

    @property
    def stage_bucket(self):
        if not self._stage_bucket:
            self._stage_bucket = self._get_ssm_param("/SDLF/S3/StageBucket")
        return self._stage_bucket

    @property
    def stage_bucket_kms_key(self):
        if not self._stage_bucket_kms_key:
            self._stage_bucket_kms_key = self._get_ssm_param("/SDLF/KMS/StageBucket")
        return self._stage_bucket_kms_key

    @property
    def analytics_bucket(self):
        if not self._analytics_bucket:
            self._analytics_bucket = self._get_ssm_param("/SDLF/S3/AnalyticsBucket").split(":")[-1]
        return self._analytics_bucket

    @property
    def analytics_bucket_kms_key(self):
        if not self._analytics_bucket_kms_key:
            self._analytics_bucket_kms_key = self._get_ssm_param("/SDLF/KMS/AnalyticsBucket")
        return self._analytics_bucket_kms_key


class DynamoConfiguration(BaseConfig):
    def __init__(self, log_level=None, ssm_interface=None):
        """
        Complementary Dynamo config stores the parameters required to access dynamo tables
        :param log_level: level the class logger should log at
        :param ssm_interface: ssm interface, normally boto, to read parameters from parameter store
        """
        self.log_level = log_level or os.getenv("LOG_LEVEL", "INFO")
        self._logger = init_logger(__name__, self.log_level)
        self._ssm = ssm_interface or boto3.client("ssm")
        super().__init__(self.log_level, self._ssm)

        self._fetch_from_ssm()

    def _fetch_from_ssm(self):
        self._object_metadata_table = None
        self._transform_mapping_table = None
        self._manifests_control_table = None

    @property
    def object_metadata_table(self):
        if not self._object_metadata_table:
            self._object_metadata_table = self._get_ssm_param("/SDLF/Dynamo/ObjectCatalog")
        return self._object_metadata_table

    @property
    def transform_mapping_table(self):
        if not self._transform_mapping_table:
            self._transform_mapping_table = self._get_ssm_param("/SDLF/Dynamo/TransformMapping")
        return self._transform_mapping_table

    @property
    def manifests_control_table(self):
        if not self._manifests_control_table:
            self._manifests_control_table = self._get_ssm_param("/SDLF/Dynamo/Manifests")
        return self._manifests_control_table


class SQSConfiguration(BaseConfig):
    def __init__(self, team, prefix, stage, log_level=None, ssm_interface=None):
        """
        Complementary SQS config stores the parameters required to access SQS
        :param log_level: level the class logger should log at
        :param ssm_interface: ssm interface, normally boto, to read parameters from parameter store
        """
        self.log_level = log_level or os.getenv("LOG_LEVEL", "INFO")
        self._logger = init_logger(__name__, self.log_level)
        self._ssm = ssm_interface or boto3.client("ssm")
        self._team = team
        self._prefix = prefix
        self._stage = stage
        super().__init__(self.log_level, self._ssm)

        self._fetch_from_ssm()

    def _fetch_from_ssm(self):
        self._stage_queue_name = None
        self._stage_dlq_name = None

    @property
    def get_stage_queue_name(self):
        if not self._stage_queue_name:
            self._stage_queue_name = self._get_ssm_param(
                "/SDLF/SQS/{}/{}{}Queue".format(self._team, self._prefix, self._stage)
            )
        return self._stage_queue_name

    @property
    def get_stage_dlq_name(self):
        if not self._stage_dlq_name:
            self._stage_dlq_name = self._get_ssm_param(
                "/SDLF/SQS/{}/{}{}DLQ".format(self._team, self._prefix, self._stage)
            )
        return self._stage_dlq_name


class StateMachineConfiguration(BaseConfig):
    def __init__(self, team, pipeline, stage, log_level=None, ssm_interface=None):
        """
        Complementary State Machine config stores the parameters required to access State Machines
        :param log_level: level the class logger should log at
        :param ssm_interface: ssm interface, normally boto, to read parameters from parameter store
        """
        self.log_level = log_level or os.getenv("LOG_LEVEL", "INFO")
        self._logger = init_logger(__name__, self.log_level)
        self._ssm = ssm_interface or boto3.client("ssm")
        self._team = team
        self._pipeline = pipeline
        self._stage = stage
        super().__init__(self.log_level, self._ssm)

        self._fetch_from_ssm()

    def _fetch_from_ssm(self):
        self._stage_state_machine_arn = None

    @property
    def get_stage_state_machine_arn(self):
        if not self._stage_state_machine_arn:
            self._stage_state_machine_arn = self._get_ssm_param(
                "/SDLF/SM/{}/{}{}SM".format(self._team, self._pipeline, self._stage)
            )
        return self._stage_state_machine_arn


class KMSConfiguration(BaseConfig):
    def __init__(self, team, log_level=None, ssm_interface=None):
        """
        Complementary KMS config stores the parameters required to access CMKs
        :param log_level: level the class logger should log at
        :param ssm_interface: ssm interface, normally boto, to read parameters from parameter store
        """
        self.log_level = log_level or os.getenv("LOG_LEVEL", "INFO")
        self._logger = init_logger(__name__, self.log_level)
        self._ssm = ssm_interface or boto3.client("ssm")
        self._team = team
        super().__init__(self.log_level, self._ssm)

        self._fetch_from_ssm()

    def _fetch_from_ssm(self):
        self._kms_arn = None

    @property
    def get_kms_arn(self):
        if not self._kms_arn:
            self._kms_arn = self._get_ssm_param("/SDLF/KMS/{}/DataKeyId".format(self._team))
        return self._kms_arn
