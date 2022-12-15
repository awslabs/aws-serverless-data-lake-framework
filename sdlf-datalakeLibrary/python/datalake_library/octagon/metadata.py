import json
import logging
import os

from .config import ConfigObjectEnum


class FieldMeta:
    def __init__(
        self, attribute, type, partition_key=False, sort_key=False, generated=False, mandatory=False, composite=False
    ):
        self.attribute = attribute
        self.type = type
        self.partition_key = partition_key
        self.sort_key = sort_key
        self.generated = generated
        self.mandatory = mandatory
        self.composite = composite


class TableMeta:
    def __init__(self, octagon_object):
        self.octagon_object = octagon_object
        self.fields_meta = {}
        self.partition_key = ""
        self.sort_key = ""

    def add_field_meta(self, field_meta: FieldMeta):
        self.fields_meta[field_meta.attribute] = field_meta

        if field_meta.partition_key:
            self.partition_key = field_meta.attribute

        if field_meta.sort_key:
            self.sort_key = field_meta.attribute

    def get_partition_key(self):
        return self.partition_key

    def get_sort_key(self):
        return self.sort_key

    def get_field_meta(self, attribute: str) -> FieldMeta:
        return self.fields_meta[attribute]


class OctagonMetadata:
    def __init__(self, metadata_filename):
        self.logger = logging.getLogger(__name__)

        if not os.path.isfile(metadata_filename):
            self.logger.error(f"Octagon metadata file is not found {metadata_filename}")
            raise ValueError("Metadata file is not found!")

        with open(metadata_filename, "r") as f:
            meta_dict = json.load(f)

        self.table_meta = {}

        for oct_obj in meta_dict["octagon_metadata"]:
            object_name = oct_obj["octagon_object"]
            tm = TableMeta(object_name)
            self.table_meta[object_name] = tm
            self.logger.debug(f"Loading metadata for object {object_name}")

            for oct_field in oct_obj["fields_metadata"]:
                field_meta = FieldMeta(
                    attribute=oct_field["attribute"],
                    type=oct_field["type"],
                    partition_key=oct_field.get("partition_key", False),
                    sort_key=oct_field.get("sort_key", False),
                    generated=oct_field.get("generated", False),
                    mandatory=oct_field.get("mandatory", False),
                    composite=oct_field.get("composite", False),
                )
                tm.add_field_meta(field_meta)
            self.logger.debug(f"Loading metadata for object {object_name} DONE")

    def get_table_meta(self, octagon_object: ConfigObjectEnum) -> TableMeta:
        return self.table_meta[octagon_object.value]

    def get_metrics_pk(self):
        return self.get_table_meta(ConfigObjectEnum.OCTAGON_OBJECT_METRICS).get_partition_key()

    def get_metrics_sk(self):
        return self.get_table_meta(ConfigObjectEnum.OCTAGON_OBJECT_METRICS).get_sort_key()

    def get_pipelines_pk(self):
        return self.get_table_meta(ConfigObjectEnum.OCTAGON_OBJECT_PIPELINES).get_partition_key()

    def get_artifacts_pk(self):
        return self.get_table_meta(ConfigObjectEnum.OCTAGON_OBJECT_ARTIFACTS).get_partition_key()

    def get_peh_pk(self):
        return self.get_table_meta(ConfigObjectEnum.OCTAGON_OBJECT_PIPELINEHISTORY).get_partition_key()

    def get_events_pk(self):
        return self.get_table_meta(ConfigObjectEnum.OCTAGON_OBJECT_EVENTS).get_partition_key()
