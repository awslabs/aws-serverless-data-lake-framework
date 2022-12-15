import ast
import datetime as dt
import json
import logging
import os
import time

import boto3
from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource("dynamodb")
ssm = boto3.client("ssm")
glue = boto3.client("glue")


def datetimeconverter(o):
    if isinstance(o, dt.datetime):
        return o.__str__()


def lambda_handler(event, context):
    """Calls custom transform developed by user

    Arguments:
        event {dict} -- Dictionary with details on previous processing step
        context {dict} -- Dictionary with details on Lambda context

    Returns:
        {dict} -- Dictionary with Data Quality Job details
    """
    try:
        logger.info("Fetching event data from previous step")
        team = event["body"]["team"]
        dataset = event["body"]["dataset"]
        tables = event["body"]["job"]["jobDetails"]["tables"]
        env = event["body"]["env"]

        job_name = "sdlf-data-quality-controller"
        response = {"job": {"jobName": job_name, "jobStatus": "PASS"}}

        # Checking if Data Quality is enabled on tables
        logger.info("Querying data quality enabled tables")
        schemas_table = dynamodb.Table("octagon-DataSchemas-{}".format(env))

        deequ_tables = []
        for table in tables:
            table_item = schemas_table.get_item(Key={"name": f"{team}-{dataset}-{table}"})
            if "Item" not in table_item:
                # In case replication Lambda is in the process of writing the item
                time.sleep(180)
                table_item = schemas_table.get_item(Key={"name": f"{team}-{dataset}-{table}"})

            if table_item["Item"]["data_quality_enabled"] == "Y":
                deequ_tables.append(table)

        if deequ_tables:
            logger.info("Running Data Quality Controller Glue Job")
            job_response = glue.start_job_run(
                JobName=job_name,
                Arguments={
                    "--team": team,
                    "--dataset": dataset,
                    "--glueDatabase": ssm.get_parameter(Name=f"/SDLF/Glue/{team}/{dataset}/DataCatalog")["Parameter"][
                        "Value"
                    ],
                    "--glueTables": ",".join(deequ_tables),
                },
            )
            json_data = json.loads(json.dumps(job_response, default=datetimeconverter))
            response["job"]["jobRunId"] = json_data.get("JobRunId")
            response["job"]["jobStatus"] = "STARTED"
    except Exception as e:
        logger.error("Fatal error", exc_info=True)
        raise e
    return response
