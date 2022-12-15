import json
import logging

from .utils import (
    get_local_date,
    get_timestamp_iso,
    get_ttl,
    parse_metrics,
    throw_if_false,
    throw_none_or_empty,
    validate_date,
)

METRIC_ROOT = "ROOT"
METRIC_YEARLY = "YEARLY"
METRIC_MONTHLY = "MONTHLY"
METRIC_WEEKLY = "WEEKLY"
METRIC_DAILY = "DAILY"

METRIC_ONCE = "ONCE"
METRIC_ALWAYS = "ALWAYS"


class MetricRecordInfo:
    def __init__(self, root, metric, metric_type):
        self.root = root
        self.metric = metric
        self.metric_type = metric_type

    def __str__(self):
        return f"[MRI root: {self.root}, metric: {self.metric}, metric_type: {self.metric_type}"


class MetricAPI:
    def __init__(self, client):
        self.logger = logging.getLogger(__name__)
        self.client = client
        self.metrics_table = client.dynamodb.Table(client.config.get_metrics_table())
        self.metrics_ttl = client.config.get_metrics_ttl()

    def create_metrics(self, date_str: str, metric_code: str, value: int):

        throw_if_false(self.client.is_pipeline_set(), "Pipeline execution is not yet assigned")

        throw_none_or_empty(metric_code, "Metric code is not defined")

        if value == 0:
            self.logger.error("Provided metrics value is 0")
            return None

        validate_date(date_str)

        metric_rec_arr = self._get_metric_records(date_str, metric_code)
        for metric_rec in metric_rec_arr:
            self._create_single_metric(metric_rec, value)

        return True

    def _create_single_metric(self, metric_rec: MetricRecordInfo, value: int):
        self.logger.debug(f"create_single_metric() {metric_rec}")

        result = self.metrics_table.get_item(
            Key={"root": metric_rec.root, "metric": metric_rec.metric},
            ConsistentRead=True,
            AttributesToGet=["root", "metric", "version"],
        )

        utc_time_iso = get_timestamp_iso()
        local_date_iso = get_local_date()

        metric_found = "Item" in result
        new_metric_value = None
        if metric_found:  # Update existing metrics
            version = result["Item"]["version"]

            expr_names = {
                "#V": "version",
                "#T": "last_updated_timestamp",
                "#D": "last_updated_date",
                "#X": "value",
                "#P": "last_pipeline_execution_id",
            }

            expr_values = {
                ":X": value,
                ":INC": 1,
                ":T": utc_time_iso,
                ":D": local_date_iso,
                ":V": version,
                ":P": self.client.pipeline_execution_id,
            }
            update_expr = "ADD #V :INC, #X :X SET #T = :T, #P = :P, #D = :D"

            result = self.metrics_table.update_item(
                Key={"root": metric_rec.root, "metric": metric_rec.metric},
                UpdateExpression=update_expr,
                ExpressionAttributeValues=expr_values,
                ExpressionAttributeNames=expr_names,
                ConditionExpression="#V = :V",
                ReturnValues="UPDATED_NEW",
            )
            # self.logger.debug(result)
            new_metric_value = int(result["Attributes"]["value"])
            new_metric_version = int(result["Attributes"]["version"])

        else:  # New metric
            item = {}
            item["root"] = metric_rec.root
            item["metric"] = metric_rec.metric
            item["type"] = metric_rec.metric_type
            item["creation_timestamp"] = utc_time_iso
            item["last_updated_timestamp"] = utc_time_iso
            item["last_updated_date"] = local_date_iso
            item["last_pipeline_execution_id"] = self.client.pipeline_execution_id
            item["value"] = value
            item["version"] = 1
            if self.metrics_ttl > 0:
                item["ttl"] = get_ttl(self.metrics_ttl)

            self.metrics_table.put_item(Item=item)
            new_metric_value = int(value)
            new_metric_version = 1

        # Process threshold settings and send SNS notifications
        self._process_sns_notifications(metric_rec, new_metric_value, new_metric_version)

        return True

    def _process_sns_notifications(self, metric_rec: MetricRecordInfo, new_metric_value: int, new_metric_version):
        for metric_config_info in self.client.config.metric_info:

            if (
                metric_rec.root == metric_config_info.metric
                and metric_rec.metric_type == metric_config_info.metric_type
            ):

                if self._check_metric_threshold(
                    new_metric_value, metric_config_info.evaluation, metric_config_info.threshold
                ) and (
                    (metric_config_info.notify == METRIC_ALWAYS)
                    or (metric_config_info.notify == METRIC_ONCE and not self._is_notification_sent(metric_rec))
                ):

                    message = {
                        "root": metric_rec.root,
                        "metric": metric_rec.metric,
                        "type": metric_rec.metric_type,
                        "threshold": metric_config_info.threshold,
                        "value": new_metric_value,
                    }
                    message_str = json.dumps(message)

                    # Get Global ARN if defined, then local metric ARN, then pass sending to SNS
                    if self.client.is_sns_set():
                        topic = self.client.sns_topic
                    elif metric_config_info.sns_topic != "":
                        topic = metric_config_info.sns_topic
                    else:
                        self.logger.warn("SNS ARN is not defined neither globally nor in the metrics")
                        return True

                    topic_arn = self._get_topic_arn(topic)

                    sns_result = self._send_sns_message(message_str, topic_arn)
                    sns_message_id = sns_result["MessageId"]
                    self._update_notification_info(
                        metric_info=metric_rec,
                        frequency=metric_config_info.notify,
                        threshold=metric_config_info.threshold,
                        sns_topic_arn=topic_arn,
                        sns_message_id=sns_message_id,
                        version=new_metric_version,
                    )

        return True

    def _get_metric_records(self, date_str, metric_name) -> [MetricRecordInfo]:

        validate_date(date_str)

        metric_arr = parse_metrics(metric_name)
        records = []
        for metric in metric_arr:

            # Root
            root_metric = MetricRecordInfo(root=metric, metric=metric, metric_type=METRIC_ROOT)
            records.append(root_metric)

            # Yearly
            year_suffix = ".Y" + date_str[:4]
            yearly_metric = MetricRecordInfo(root=metric, metric=metric + year_suffix, metric_type=METRIC_YEARLY)
            records.append(yearly_metric)

            # Monthly
            month_suffix = ".M" + date_str[:7]
            monthly_metric = MetricRecordInfo(root=metric, metric=metric + month_suffix, metric_type=METRIC_MONTHLY)
            records.append(monthly_metric)

            # Daily
            day_suffix = ".D" + date_str
            daily_metric = MetricRecordInfo(root=metric, metric=metric + day_suffix, metric_type=METRIC_DAILY)
            records.append(daily_metric)

        return records

    def get_metrics_value(self, metric):
        if "." in metric:
            root = metric.split(".")[0]
        else:
            root = metric

        result = self.metrics_table.get_item(Key={"root": root, "metric": metric}, ConsistentRead=True)
        if "Item" in result:
            return self.metrics_table.get_item(Key={"root": root, "metric": metric}, ConsistentRead=True)["Item"][
                "value"
            ]
        else:
            return 0

    def _update_notification_info(
        self,
        metric_info: MetricRecordInfo,
        frequency: str,
        threshold: int,
        sns_topic_arn: str,
        sns_message_id: str,
        version: int,
    ):

        utc_timestamp = get_timestamp_iso()

        expr_names = {
            "#L": "last_notification_timestamp",
            "#F": "notification_frequency",
            "#T": "notification_threshold",
            "#S": "notification_sns_topic_arn",
            "#M": "notification_sns_message_id",
            "#V": "version",
        }

        expr_values = {
            ":L": utc_timestamp,
            ":F": frequency,
            ":T": threshold,
            ":S": sns_topic_arn,
            ":M": sns_message_id,
            ":INC": 1,
            ":V": version,
        }
        update_expr = "SET #L = :L, #F = :F, #T = :T, #S = :S, #M = :M, #V = #V + :INC"

        self.metrics_table.update_item(
            Key={"root": metric_info.root, "metric": metric_info.metric},
            UpdateExpression=update_expr,
            ExpressionAttributeValues=expr_values,
            ExpressionAttributeNames=expr_names,
            ConditionExpression="#V = :V",
            ReturnValues="UPDATED_NEW",
        )
        return True

    def _is_notification_sent(self, metric_info: MetricRecordInfo):
        item = self.metrics_table.get_item(
            Key={"root": metric_info.root, "metric": metric_info.metric}, ConsistentRead=True
        )["Item"]
        return "notification_timestamp" in item.keys()

    def _send_sns_message(self, message, topic_arn):
        self.logger.debug(f"Send message to SNS: Message {message}, topicArn: {topic_arn}")
        sns = self.client.sns
        response = sns.publish(TopicArn=topic_arn, Message=message)
        # self.logger.debug(f"SNS response: {response}")
        return response

    def _check_metric_threshold(self, current_value, evaluation, threshold_value):

        throw_if_false(isinstance(current_value, int), "Wrong current value")
        throw_if_false(isinstance(threshold_value, int), "Wrong threshold value")

        if evaluation == "=":
            return current_value == threshold_value
        elif evaluation == ">":
            return current_value > threshold_value
        elif evaluation == "<":
            return current_value < threshold_value
        elif evaluation == ">=":
            return current_value >= threshold_value
        elif evaluation == "<=":
            return current_value <= threshold_value
        else:
            raise ValueError(f"Wrong evaluation operation: {evaluation}")

    def _get_topic_arn(self, name):
        if "arn:aws:sns:" in name:
            return name
        else:
            return ":".join(["arn", "aws", "sns", self.client.region, self.client.account_id, name])
