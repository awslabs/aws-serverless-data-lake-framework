import json
import logging
import os
from enum import Enum

from .utils import throw_if_false


class ConfigObjectEnum(Enum):
    OCTAGON_OBJECT_DATASETS = "Datasets"
    OCTAGON_OBJECT_DATASCHEMAS = "DataSchemas"
    OCTAGON_OBJECT_PIPELINES = "Pipelines"
    OCTAGON_OBJECT_PIPELINEHISTORY = "PipelineExecutionHistory"
    OCTAGON_OBJECT_EVENTS = "Events"
    OCTAGON_OBJECT_ARTIFACTS = "Artifacts"
    OCTAGON_OBJECT_METRICS = "Metrics"


class ConfigTableInfo:
    def __init__(self, dynamo_table_name, ttl_in_days=0, read_capacity=0, write_capacity=0):
        self.dynamo_table_name = dynamo_table_name
        self.ttl_in_days = ttl_in_days
        self.read_capacity = read_capacity
        self.write_capacity = write_capacity

    def get_dynamo_table_name(self):
        return self.dynamo_table_name

    def get_ttl_days(self):
        return self.ttl_in_days

    def get_read_capacity(self):
        return self.read_capacity

    def get_write_capacity(self):
        return self.write_capacity

    def __str__(self):
        return f"[ Table name: {self.dynamo_table_name}, TTL: {self.ttl_in_days}, RC: {self.read_capacity}, WC: {self.write_capacity}]"


class MetricInfo:
    def __init__(self, metric, evaluation, threshold, notify, metric_type, sns_topic):
        self.metric = metric
        self.evaluation = evaluation
        self.threshold = threshold
        self.notify = notify
        self.metric_type = metric_type
        self.sns_topic = sns_topic

    def __str__(self):
        return f"[ Metric:{self.metric}, threshold: {self.threshold}]"


class ConfigParser:
    def __init__(self, config_file, instance):
        self.logger = logging.getLogger(__name__)
        self.instance = instance
        self.logger.debug(f"Reading configuration from file {config_file}")

        if not os.path.isfile(config_file):
            msg = f"Octagon configuration file is not found {config_file}"
            self.logger.error(msg)
            raise ValueError(msg)

        with open(config_file, "r") as f:
            config_dict = json.load(f)

        self.table_info = {}
        self.metric_info = []

        for config_instance in config_dict["configuration_instances"]:
            if config_instance["instance"] == instance:
                for ti in config_instance["tables"]:
                    if "object" in ti.keys() and "table_name" in ti.keys():
                        table_info = ConfigTableInfo(
                            dynamo_table_name=ti["table_name"],
                            ttl_in_days=ti.get("ttl", 0),
                            read_capacity=ti.get("read_capacity", 0),
                            write_capacity=ti.get("write_capacity", 0),
                        )
                        object_name = ti["object"]

                        self.table_info[object_name] = table_info
                        self.logger.debug(f"Loaded config for table: {table_info}")

                if "metrics" in config_instance.keys():
                    for mi in config_instance["metrics"]:
                        metric_info = MetricInfo(
                            metric=mi.get("metric"),
                            evaluation=mi.get("evaluation"),
                            threshold=mi.get("threshold"),
                            notify=mi.get("notify"),
                            metric_type=mi.get("metric_type"),
                            sns_topic=mi.get("sns_topic", ""),
                        )

                        self.metric_info.append(metric_info)
                        self.logger.debug(f"Loaded config for metric: {metric_info}")

        throw_if_false(len(self.table_info) > 0, "Configuration instance is not found")

    def get_table_info(self, config_obj: ConfigObjectEnum) -> ConfigTableInfo:
        return self.table_info[config_obj.value]

    def get_table_name(self, config_obj: ConfigObjectEnum) -> str:
        return self.get_table_info(config_obj).get_dynamo_table_name()

    def get_events_table(self) -> str:
        return self.get_table_name(ConfigObjectEnum.OCTAGON_OBJECT_EVENTS)

    def get_table_ttl(self, config_obj: ConfigObjectEnum) -> int:
        return self.get_table_info(config_obj).get_ttl_days()

    def get_events_ttl(self) -> int:
        return self.get_table_ttl(ConfigObjectEnum.OCTAGON_OBJECT_EVENTS)

    def get_pipelines_table(self) -> str:
        return self.get_table_name(ConfigObjectEnum.OCTAGON_OBJECT_PIPELINES)

    def get_peh_table(self) -> str:
        return self.get_table_name(ConfigObjectEnum.OCTAGON_OBJECT_PIPELINEHISTORY)

    def get_peh_ttl(self) -> str:
        return self.get_table_ttl(ConfigObjectEnum.OCTAGON_OBJECT_PIPELINEHISTORY)

    def get_artifacts_table(self) -> str:
        return self.get_table_name(ConfigObjectEnum.OCTAGON_OBJECT_ARTIFACTS)

    def get_artifacts_ttl(self) -> int:
        return self.get_table_ttl(ConfigObjectEnum.OCTAGON_OBJECT_ARTIFACTS)

    def get_metrics_table(self) -> str:
        return self.get_table_name(ConfigObjectEnum.OCTAGON_OBJECT_METRICS)

    def get_metrics_ttl(self) -> int:
        return self.get_table_ttl(ConfigObjectEnum.OCTAGON_OBJECT_METRICS)
