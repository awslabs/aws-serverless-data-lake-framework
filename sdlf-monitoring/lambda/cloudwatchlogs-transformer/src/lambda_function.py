import base64
import gzip
import json
import logging
import os

import boto3
from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

firehose_endpoint_url = "https://firehose." + os.getenv("AWS_REGION") + ".amazonaws.com"
firehose = boto3.client("firehose", endpoint_url=firehose_endpoint_url)


def transform_log_event(log_event):
    return f"{log_event['message']}\n"


def put_records(stream_name, records, attempts_made, max_attempts):
    try:
        response = firehose.put_record_batch(
            DeliveryStreamName=stream_name,
            Records=records,
        )
    except (BotoCoreError, ClientError) as err:
        if attempts_made + 1 < max_attempts:
            logger.info(f"Some records failed while calling PutRecords, retrying. {str(err)}")
            put_records(stream_name, records, attempts_made + 1, max_attempts)
        else:
            raise Exception(f"Could not put records after {max_attempts} attempts. {str(err)}")

    if "FailedPutCount" in response and response["FailedPutCount"] > 0:
        codes = [rec["ErrorCode"] for rec in response["RequestResponses"] if "ErrorCode" in rec]
        failed = [records[i] for i, rec in enumerate(response["RequestResponses"]) if "ErrorCode" in rec]
        if attempts_made + 1 < max_attempts:
            logger.info(f"Some records failed while calling PutRecords, retrying. Individual error codes: {codes}")
            put_records(stream_name, failed, attempts_made + 1, max_attempts)
        else:
            raise Exception(f"Could not put records after {max_attempts} attempts. Individual error codes: {codes}")
    else:
        return ""


def lambda_handler(event, context):
    records_out = []
    records_to_reingest = []
    input_data_by_rec_id = {}

    for record in event["records"]:
        compressed_payload = base64.b64decode(record["data"])
        uncompressed_payload = gzip.decompress(compressed_payload)
        data = json.loads(uncompressed_payload)

        if data["messageType"] != "DATA_MESSAGE":
            records_out.append(
                {
                    "recordId": record["recordId"],
                    "result": "ProcessingFailed",
                }
            )
        else:
            transformed_log_events = [transform_log_event(log_event) for log_event in data["logEvents"]]

            for transformed_log_event in transformed_log_events:
                records_out.append(
                    {
                        "recordId": record["recordId"],
                        "result": "Ok",
                        "data": base64.b64encode(transformed_log_event.encode("utf-8")).decode("utf-8"),
                    }
                )

            input_data_by_rec_id[record["recordId"]] = compressed_payload

    projected_size = sum(
        [
            len(record["recordId"]) + len(record["data"])
            for record in records_out
            if record["result"] != "ProcessingFailed"
        ]
    )
    MAX_SIZE = 4000000
    logger.info(f"Projected size: {projected_size} / {MAX_SIZE}")
    for idx, record in enumerate(records_out):
        if projected_size > MAX_SIZE:
            if record["result"] != "ProcessingFailed":
                records_to_reingest.append({"Data": input_data_by_rec_id[record["recordId"]]})
                projected_size -= len(record["data"])
                del record["data"]
                record["result"] = "Dropped"

    if records_to_reingest:
        stream_arn = event["deliveryStreamArn"]
        stream_name = stream_arn.split("/")[1]

        try:
            put_records(stream_name, records_to_reingest, 0, 20)
            logger.info(f'Reingested {len(records_to_reingest)} records out of {len(event["records"])}')
        except Exception as err:
            logger.info(f"Failed to reingest records. {str(err)}")
            raise err
    else:
        logger.info("No records needed to be reingested.")

    return {"records": records_out}
