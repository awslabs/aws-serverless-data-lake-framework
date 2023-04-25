import json
import logging
import os
from datetime import datetime
from urllib.parse import unquote_plus

import boto3
from boto3.dynamodb.conditions import Key
from botocore.config import Config
from botocore.exceptions import ClientError

session_config = Config(user_agent_extra="awssdlf/2.0.0")

logger = logging.getLogger()
logger.setLevel(logging.INFO)
events = boto3.client("events", config=session_config)
dynamodb = boto3.resource("dynamodb", config=session_config)
dataset_table = dynamodb.Table("octagon-Datasets-{}".format(os.environ["ENV"]))
pipeline_table = dynamodb.Table("octagon-Pipelines-{}".format(os.environ["ENV"]))


def parse_s3_event(s3_event):
    return {
        "bucket": s3_event["s3"]["bucket"]["name"],
        "key": unquote_plus(s3_event["s3"]["object"]["key"]),
        "size": s3_event["s3"]["object"]["size"],
        "last_modified_date": s3_event["eventTime"].split(".")[0] + "+00:00",
        "timestamp": int(round(datetime.utcnow().timestamp() * 1000, 0)),
        "stage": "raw",
    }


def paginate_dynamodb_response(dynamodb_action, **kwargs):
    keywords = kwargs

    done = False
    start_key = None

    while not done:
        if start_key:
            keywords["ExclusiveStartKey"] = start_key

        response = dynamodb_action(**keywords)

        start_key = response.get("LastEvaluatedKey", None)
        done = start_key is None

        for item in response.get("Items", []):
            yield item


def get_item(table, team, dataset):
    try:
        response = table.get_item(Key={"name": "{}-{}".format(team, dataset)})
    except ClientError as e:
        print(e.response["Error"]["Message"])
    else:
        item = response["Item"]
        for key in item["pipeline"]:
            return key # there is only one element currently

def get_pipeline_entrypoint(table, team, pipeline):
    query = paginate_dynamodb_response(
        table.query,
        IndexName="entrypoint-name-index",
        KeyConditionExpression=Key("entrypoint").eq("true") & Key("name").begins_with("{}-{}-".format(team, pipeline)),
    )

    for row in query:
        return row["name"].removeprefix("{}-{}-".format(team, pipeline))
    else:
        raise Exception("The selected pipeline does not have an entry point.")


def lambda_handler(event, context):
    try:
        logger.info("Received {} messages".format(len(event["Records"])))
        for record in event["Records"]:
            logger.info("Parsing S3 Event")
            message = parse_s3_event(json.loads(record["body"]))

            if os.environ["NUM_BUCKETS"] == "1":
                team = message["key"].split("/")[1]
                dataset = message["key"].split("/")[2]
            else:
                team = message["key"].split("/")[0]
                dataset = message["key"].split("/")[1]
            message["team"] = team
            message["dataset"] = dataset
            pipeline = get_item(dataset_table, team, dataset)
            message["pipeline"] = pipeline
            message["org"] = os.environ["ORG"]
            message["domain"] = os.environ["DOMAIN"]
            message["env"] = os.environ["ENV"]
            pipeline_stage = get_pipeline_entrypoint(pipeline_table, team, pipeline)
            logger.info("Pipeline entrypoint: {}".format(pipeline_stage))
            message["pipeline_stage"] = pipeline_stage

            logger.info("Sending events to default event bus for processing")
            entries = events.put_events(
                Entries=[
                    {"Source": "sdlf.s3", "DetailType": "SdlfObjectInS3", "Detail": json.dumps(message)},
                ]
            )

            if entries["FailedEntryCount"] > 0:
                raise Exception("Some entries could not be sent to EventBridge: {}".format(entries))
    except Exception as e:
        logger.error("Fatal error", exc_info=True)
        raise e
    return
