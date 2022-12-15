import logging
import os

import boto3
import pkg_resources

from .artifact import Artifact, ArtifactAPI
from .config import ConfigParser
from .event import EventAPI
from .metadata import OctagonMetadata
from .metric import MetricAPI
from .peh import PEH_STATUS_CANCELED, PEH_STATUS_COMPLETED, PEH_STATUS_FAILED, PipelineExecutionHistoryAPI


class OctagonClient:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.region = "us-east-1"
        self.profile = "default"
        self.configuration_file = pkg_resources.resource_filename(__name__, "octagon-configuration.json")
        self.configuration_instance = "dev"
        self.metadata_file = pkg_resources.resource_filename(__name__, "octagon-metadata.json")
        self.initialized = False
        self.run_in_fargate = False
        self.run_in_lambda = False
        self.sns_topic = None

        # No current pipeline execution
        self.pipeline_name = None
        self.pipeline_execution_id = None

    def with_sns_topic(self, sns_topic: str):
        """Set SNS topic configuration

        Arguments:
            sns_topic {str} -- SNS ARN or Queue Name (in the current account)

        Returns:
            OctagonClient -- Client reference
        """
        self.sns_topic = sns_topic
        return self

    def with_run_lambda(self, flag: bool):
        """ Set flag for running in lambda - no need for boto3 init

        Arguments:
            flag {bool} -- Enable/Disable

        Returns:
            OctagonClient -- Client reference
        """
        self.run_in_lambda = flag
        return self

    def with_run_fargate(self, flag: bool):
        """ Set flag for using AWS_ACCESS_KEY and AWS_SECRET_ACCESS_KEY environment variables for authentication

        Arguments:
            flag {bool} -- Enable/Disable

        Returns:
            OctagonClient -- Client reference
        """
        self.run_in_fargate = flag
        return self

    def with_region(self, region: str):
        """ Set AWS region

        Arguments:
            region {str} -- AWS region name, e.g "us-east-1"

        Returns:
            OctagonClient -- Client reference
        """
        self.region = region
        return self

    def with_profile(self, profile: str):
        """Set AWS profile

        Arguments:
            profile {str} -- Set AWS profile to use

        Returns:
            OctagonClient -- Client reference
        """
        self.profile = profile
        return self

    def with_config(self, config_file: str):
        """Set Octagon configuration file name

        Arguments:
            config_file {str} -- File name of Octagon configuration file

        Returns:
            OctagonClient -- Client reference
        """
        self.configuration_file = config_file
        return self

    def with_meta(self, metadata_file: str):
        """Set Octagon metadata file name

        Arguments:
            metadata_file {str} -- File name of Octagon metadata file

        Returns:
            OctagonClient -- Client reference
        """
        self.metadata_file = metadata_file
        return self

    def with_configuration_instance(self, instance: str):
        """ Set Configuration Instance to be used from Octagon configuration file
        Arguments:
            instance {str} -- Configuration Instance name

        Returns:
            OctagonClient -- Client reference
        """
        self.configuration_instance = instance
        return self

    def build(self):
        """ Client initialization method """
        # Initialization here
        if self.run_in_fargate:
            if "AWS_ACCESS_KEY" in os.environ and "AWS_SECRET_ACCESS_KEY" in os.environ:
                aws_access_key = os.environ.get("AWS_ACCESS_KEY")
                aws_secret_access_key = os.environ.get("AWS_SECRET_ACCESS_KEY")
                boto3.setup_default_session(
                    profile_name=self.profile,
                    region_name=self.region,
                    aws_access_key_id=aws_access_key,
                    aws_secret_access_key=aws_secret_access_key,
                )
            else:
                msg = "Environment variables AWS_ACCESS_KEY and AWS_SECRET_ACCESS_KEY are not set"
                self.logger.error(msg)
                raise ValueError(msg)

        elif self.run_in_lambda:
            pass

        else:
            boto3.setup_default_session(profile_name=self.profile, region_name=self.region)

        self.account_id = boto3.client("sts").get_caller_identity().get("Account")

        self.dynamodb = boto3.resource("dynamodb")
        self.sns = boto3.client("sns")
        self.config = ConfigParser(self.configuration_file, self.configuration_instance)
        self.meta = OctagonMetadata(self.metadata_file)
        self.initialized = True

        return self

    def start_pipeline_execution(self, pipeline_name: str, dataset_name: str = None, dataset_date: str = None, comment: str = None) -> str:
        """ Creates a record for Pipeline Execution History

        Arguments:
            pipeline_name {str} -- Name of pipeline (needs to be active)

        Keyword Arguments:
            dataset_date {str} -- Optional. ISO 8601 date of dataset
            comment {str} -- Optional. Comment

        Returns:
            str -- Unique reference to a Pipeline Execution History record (uuid4)
        """
        return PipelineExecutionHistoryAPI(self).start_pipeline_execution(pipeline_name, dataset_name, dataset_date, comment)

    def update_pipeline_execution(self, status: str, component: str = None) -> bool:
        """ Update status of Pipeline Execution History record

        Arguments:
            status {str} -- New status of Pipeline Execution
            component {str} -- Optional. Component of Pipeline Execution

        Returns:
            bool -- True if successfull
        """
        return PipelineExecutionHistoryAPI(self).update_pipeline_execution(status, component=component)

    def end_pipeline_execution_failed(self, component: str = None, issue_comment: str = None) -> bool:
        """ Closes Pipeline Execution History record with FAILED status

        Arguments:
            component {str} -- Optional. Component of Pipeline Execution
            issue_comment {str} -- Optional. Comment

        Returns:
            bool -- True if successfull
        """
        return PipelineExecutionHistoryAPI(self).update_pipeline_execution(
            PEH_STATUS_FAILED, component=component, issue_comment=issue_comment
        )

    def end_pipeline_execution_success(self, component: str = None) -> bool:
        """ Closes Pipeline Execution History record with COMPLETED status

        Arguments:
            component {str} -- Optional. Component of Pipeline Execution

        Returns:
            bool -- True if successfull
        """
        return PipelineExecutionHistoryAPI(self).update_pipeline_execution(PEH_STATUS_COMPLETED, component=component)

    def end_pipeline_execution_cancel(self, component: str = None, issue_comment: str = None) -> bool:
        """ Closes Pipeline execution with CANCELED status

        Arguments:
            component {str} -- Optional. Component of Pipeline Execution
            issue_comment {str} -- Optional. Comment

        Returns:
            bool -- True if successfull
        """
        return PipelineExecutionHistoryAPI(self).update_pipeline_execution(
            PEH_STATUS_CANCELED, component=component, issue_comment=issue_comment
        )

    def retrieve_pipeline_execution(self, peh_id: str):
        """Retrieve pipeline execution information and set as current execution in the Client

        Arguments:
            peh_id {str} -- Uniqie Pipeline execution ID

        Returns:
            None
        """
        return PipelineExecutionHistoryAPI(self).retrieve_pipeline_execution(peh_id)

    def create_event(self, reason: str, comment: str, component_name: str = None, event_details: str = None) -> str:
        """ Create Event for the current pipeline

        Arguments:
            reason {str} -- Reason string
            comment {str} -- Comment string

        Keyword Arguments:
            component_name {str} -- Optional. Component name
            event_details {str} -- Optional. Event details

        Returns:
            str -- Unique Event ID (uuid4)
        """
        return EventAPI(self).create_event(reason, comment, component_name, event_details)

    def create_artifact_registration(self, artifact: Artifact) -> str:
        """ Register artifact for the current pipeline

        Arguments:
            artifact {Artifact} -- Artifact object to register for current pipeline

        Returns:
            str -- Unique Atrifact ID (uuid4)
        """
        return ArtifactAPI(self).register_artifact(artifact)

    def create_metrics(self, date_str: str, metric_code: str, value: int) -> bool:
        """ Create/add metric value for the current pipeline

        Arguments:
            date_str {str} -- ISO 8601 date string to register metric for, e.g. "2019-05-01"
            metric_code {str} -- Code of the metric. Nested metrics with separator "#" are supported, e.g. "Streams#Stream1#Stream11"
            value {int} -- Integer value to add to the metric

        Returns:
            bool -- True if successful
        """
        return MetricAPI(self).create_metrics(date_str=date_str, metric_code=metric_code, value=value)

    def reset_pipeline_execution(self):
        """Clears the current pipeline execution
        """
        self.pipeline_execution_id = None
        self.pipeline_name = None

    def set_pipeline_execution(self, pipeline_execution_id: str, pipeline_name: str):
        """Sets the current pipeline execution

        Arguments:
            pipeline_execution_id {str} -- Unique identifier of pipeline execution
            pipeline_name {str} -- Pipeline name
        """
        self.pipeline_execution_id = pipeline_execution_id
        self.pipeline_name = pipeline_name

    def is_pipeline_set(self) -> bool:
        """Check if current pipeline execution is set

        Returns:
            bool -- True if pipeline execution is set
        """
        return self.pipeline_execution_id is not None and self.pipeline_name is not None

    def is_sns_set(self) -> bool:
        """Check if SNS is configured globally

        Returns:
            bool -- True if SNS configuration was set
        """
        return self.sns_topic is not None
