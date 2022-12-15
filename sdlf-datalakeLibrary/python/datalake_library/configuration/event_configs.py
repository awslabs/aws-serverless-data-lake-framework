import os
from urllib import parse

import boto3

from ..commons import init_logger


class EventConfig:
    def __init__(self, event, ssm_interface=None):
        """
        Base class to hold the relevant information obtained from an event and any extra resources defined

        :param event: event JSON object
        """
        self._event = event
        self._ssm_interface = ssm_interface or boto3.client("ssm")

        self.log_level = os.getenv("LOG_LEVEL", "INFO")
        self._logger = init_logger(__name__, self.log_level)

        self._fetch_from_event()

    def _fetch_from_event(self):
        raise NotImplementedError()


class EmptyEventConfig(EventConfig):
    def __init__(self, ssm_interface=None):
        """
        Class to hold the config when the event is empty
        """
        super().__init__(None, ssm_interface)
        self._logger = init_logger(__name__, self.log_level)

    def _fetch_from_event(self):
        pass


class S3EventConfig(EventConfig):
    def __init__(self, event, ssm_interface=None):
        """
        Class to hold the relevant information obtained from an S3 write event and any extra resources defined

        :param event: S3 write event JSON object
        """
        super().__init__(event, ssm_interface)
        self._logger = init_logger(__name__, self.log_level)

    def _fetch_from_event(self):
        self._logger.info("Collecting config parameters from S3 write event")

        try:
            self._region = self._event["Records"][0]["awsRegion"]
            self._source_bucket = self._event["Records"][0]["s3"]["bucket"]["name"]
            self._object_key = parse.unquote_plus(
                self._event["Records"][0]["s3"]["object"]["key"].encode("utf8").decode("utf8")
            )
            if self._source_bucket.split("-")[-1] in ["raw", "stage", "analytics"]:
                self._stage = self._source_bucket.split("-")[-1]
                self._team = self._object_key.split("/")[0]
                self._dataset = self._object_key.split("/")[1]
            else:
                self._stage = self._object_key.split("/")[0]
                self._team = self._object_key.split("/")[1]
                self._dataset = self._object_key.split("/")[2]
            self._size = int(self._event["Records"][0]["s3"]["object"]["size"])
            self._landing_time = self._event["Records"][0]["eventTime"]
        except KeyError:
            if self._event["detail"].get("errorCode", None):
                msg = "Event refers to a failed command: " "error_code {}, bucket {}, object {}".format(
                    self._event["detail"]["error_code"],
                    self._event["detail"]["raw_s3_bucket"],
                    self._event["detail"]["file_key"],
                )
                raise ValueError(msg)
            # Falling back on CloudTrail Event
            self._region = self._event["detail"]["awsRegion"]
            self._source_bucket = self._event["detail"]["requestParameters"]["bucketName"]
            self._object_key = parse.unquote_plus(
                self._event["detail"]["requestParameters"]["key"].encode("utf8").decode("utf8")
            )
            if self._source_bucket.split("-")[-1] in ["raw", "stage", "analytics"]:
                self._stage = self._source_bucket.split("-")[-1]
                self._team = self._object_key.split("/")[0]
                self._dataset = self._object_key.split("/")[1]
            else:
                self._stage = self._object_key.split("/")[0]
                self._team = self._object_key.split("/")[1]
                self._dataset = self._object_key.split("/")[2]
            self._size = int(self._event["detail"]["additionalEventData"]["bytesTransferredIn"])
            self._landing_time = self._event["detail"]["eventTime"]

    @property
    def source_bucket(self):
        return self._source_bucket

    @property
    def region(self):
        return self._region

    @property
    def object_key(self):
        return self._object_key

    @property
    def stage(self):
        return self._stage

    @property
    def dataset(self):
        return self._dataset

    @property
    def size(self):
        return self._size

    @property
    def landing_time(self):
        return self._landing_time
