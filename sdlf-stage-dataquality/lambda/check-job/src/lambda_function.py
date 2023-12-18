import datetime as dt
import json
import logging

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

glue = boto3.client("glue")


def datetimeconverter(o):
    if isinstance(o, dt.datetime):
        return o.__str__()


def lambda_handler(event, context):
    """Calls custom job waiter developed by user

    Arguments:
        event {dict} -- Dictionary with details on previous processing step
        context {dict} -- Dictionary with details on Lambda context

    Returns:
        {dict} -- Dictionary with Data Quality Job details
    """
    try:
        logger.info("Fetching event data from previous step")
        job_details = event["body"]["dataQuality"]

        logger.info("Checking Job Status")
        job_response = glue.get_job_run(JobName=job_details["job"]["jobName"], RunId=job_details["job"]["jobRunId"])
        json_data = json.loads(json.dumps(job_response, default=datetimeconverter))
        job_details["job"]["jobStatus"] = json_data.get("JobRun").get("JobRunState")
    except Exception as e:
        logger.error("Fatal error", exc_info=True)
        raise e
    return job_details
