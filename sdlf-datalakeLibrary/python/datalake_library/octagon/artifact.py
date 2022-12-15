import datetime
import logging
import uuid

from .utils import get_local_date, get_timestamp_iso, get_ttl, throw_if_false, throw_if_none, throw_none_or_empty


class Artifact:
    """Data object to handle Artifact information"""

    def __init__(self, dataset, comment=None, component=None):
        """Artifact object initialization

        Arguments:
            dataset {str} -- Dataset name

        Keyword Arguments:
            comment {str} -- Optional. Artifact comment
            component {str} -- Optional. Artifact component
        """
        self.target_locations = []
        self.dataset = dataset
        self.comment = comment
        self.component = component

    def with_source_info(self, source_type, source_service_arn, source_location_pointer):
        """Set Artifact source information

        Arguments:
            source_type {str} -- Artifact source type
            source_service_arn {str} -- Artifact source ARN
            source_location_pointer {str} -- Artifact source location pointer
        """

        throw_none_or_empty(source_type, "Source type is missing")
        throw_none_or_empty(source_service_arn, "Source service ARN is missing")
        throw_none_or_empty(source_location_pointer, "Source service locator is missing")

        self.source_type = source_type
        self.source_service_arn = source_service_arn
        self.source_location_pointer = source_location_pointer

    def with_target_info(self, target_type, target_service_arn, target_location_pointers):
        """Set Artifact target information

        Arguments:
            target_type {str} -- Artifact target type
            target_service_arn {str} -- Artifact target ARN
            target_location_pointers {str or [str]} -- Artifact target location pointer(s)
        """
        throw_none_or_empty(target_type, "Target type is missing")
        throw_none_or_empty(target_service_arn, "Target service ARN is missing")
        throw_none_or_empty(target_location_pointers, "Target location pointers are missing")

        self.target_type = target_type
        self.target_service_arn = target_service_arn
        if isinstance(target_location_pointers, str):
            self.target_locations.append(target_location_pointers)
        else:
            self.target_locations = target_location_pointers

    def get_ddb_item(self):
        item = {}
        item["dataset"] = self.dataset
        item["source_type"] = self.source_type
        item["source_service_arn"] = self.source_service_arn
        item["source_location_pointer"] = self.source_location_pointer
        item["target_type"] = self.target_type
        item["target_service_arn"] = self.target_service_arn
        item["target_location_pointers"] = self.target_locations

        if self.comment:
            item["comment"] = self.comment

        if self.component:
            item["component"] = self.component

        return item


class ArtifactAPI:
    def __init__(self, client):
        self.logger = logging.getLogger(__name__)
        self.client = client
        self.artifacts_table = client.dynamodb.Table(client.config.get_artifacts_table())
        self.artifacts_ttl = client.config.get_artifacts_ttl()

    def register_artifact(self, artifact: Artifact):
        throw_if_false(self.client.is_pipeline_set(), "Pipeline execution is not yet assigned")
        throw_if_none(artifact, "Artifact is not defined")

        current_time = datetime.datetime.utcnow()
        utc_time_iso = get_timestamp_iso(current_time)
        local_date_iso = get_local_date()

        item = artifact.get_ddb_item()
        # Add extra fields
        item["id"] = str(uuid.uuid4())
        item["pipeline"] = self.client.pipeline_name
        item["pipeline_execution_id"] = self.client.pipeline_execution_id
        item["timestamp"] = utc_time_iso
        item["date"] = local_date_iso
        item["pipeline_and_target_type"] = item["pipeline"] + "#" + item["target_type"]
        item["target_location_and_date"] = item["target_location_pointers"][0] + "#" + item["date"]
        if self.artifacts_ttl > 0:
            item["ttl"] = get_ttl(self.artifacts_ttl)

        self.artifacts_table.put_item(Item=item)
        return item["id"]

    def get_artifact(self, id):
        return self.artifacts_table.get_item(Key={"id": id}, ConsistentRead=True)["Item"]
