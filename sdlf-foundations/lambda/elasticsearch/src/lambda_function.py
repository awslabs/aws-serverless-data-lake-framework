from __future__ import print_function

import json
import logging
import traceback
from urllib.request import Request, urlopen

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)
logging.basicConfig(
    format="%(levelname)s %(threadName)s [%(filename)s:%(lineno)d] %(message)s",
    datefmt="%Y-%m-%d:%H:%M:%S",
    level=logging.INFO,
)

try:
    logger.info("Container initialization completed")
except Exception as e:
    logger.error(e, exc_info=True)
    init_failed = e


############################################################
#                 SIGNAL HANDLER FUNCTIONS                 #
############################################################


def create(event, logs_client, logger):
    """
    Upon creation of dataset, puts a subscription filter to stream logs to Lambda
    :param event: Event sent from CFN when the custom resource is deleted
    :param logs_client: Initialized CloudWatch Logs client
    """
    resource_properties = event["ResourceProperties"]
    log_group_name = resource_properties["LogGroupName"]
    destination_arn = resource_properties["DestinationArn"]
    filter_pattern = resource_properties["FilterPattern"]
    # Get name of function
    destination_lambda_name = destination_arn.split(":")[6]

    filter_name = ""
    try:
        filter_name = logs_client.describe_subscription_filters(logGroupName=log_group_name)["subscriptionFilters"][0][
            "filterName"
        ]
    except (KeyError, IndexError) as e:
        filter_name = "LambdaStream_" + destination_lambda_name
        logger.info("Cannot find existing subscription filter: %s. Created filter name: %s", e, filter_name)

    logs_client.put_subscription_filter(
        logGroupName=log_group_name,
        filterName=filter_name,
        filterPattern=filter_pattern,
        destinationArn=destination_arn,
    )

    return


def delete(event, logs_client):
    """
    Deletes the subscription filter that streams to Lambda
    :param event: Event sent from CFN when the custom resource is deleted
    :param logs_client: Initialized CloudWatch Logs client
    """
    resource_properties = event["ResourceProperties"]
    log_group_name = resource_properties["LogGroupName"]

    filter_name = logs_client.describe_subscription_filters(logGroupName=log_group_name)["subscriptionFilters"][0][
        "filterName"
    ]

    logs_client.delete_subscription_filter(logGroupName=log_group_name, filterName=filter_name)

    return


# NOT IN USE
def update(event, context):
    """ """
    return


############################################################
#                     HELPER FUNCTION                      #
############################################################


def send_response(e, c, rs, rd):
    """
    Packages response and send signals to CloudFormation
    :param e: The event given to this Lambda function
    :param c: Context object, as above
    :param rs: Returned status to be sent back to CFN
    :param rd: Returned data to be sent back to CFN
    """
    r = json.dumps(
        {
            "Status": rs,
            "Reason": "CloudWatch Log Stream: " + c.log_stream_name,
            "PhysicalResourceId": e["LogicalResourceId"],
            "StackId": e["StackId"],
            "RequestId": e["RequestId"],
            "LogicalResourceId": e["LogicalResourceId"],
            "Data": rd,
        }
    )
    d = str.encode(r)
    h = {"content-type": "", "content-length": str(len(d))}
    req = Request(e["ResponseURL"], data=d, method="PUT", headers=h)
    r = urlopen(req)
    logger.info("Status message: {} {}".format(r.msg, r.getcode()))


############################################################
#                LAMBDA FUNCTION HANDLER                   #
############################################################
# IMPORTANT: The Lambda function will be called whenever   #
# changes are made to the stack. Thus, ensure that the     #
# signals are handled by your Lambda function correctly,   #
# or the stack could get stuck in the DELETE_FAILED state  #
############################################################


def handler(event, context):
    """
    Entrypoint to Lambda, updates the main CloudTrail trail
    :param event: The event given to this Lambda function
    :param context: Context object containing Lambda metadata
    """
    request_type = event["RequestType"]
    client = boto3.client("logs")

    try:
        if request_type == "Create":
            create(event, client, logger)
            send_response(event, context, "SUCCESS", {"Message": "Created"})
        elif request_type == "Update":
            create(event, client, logger)
            send_response(event, context, "SUCCESS", {"Message": "Updated"})
        elif request_type == "Delete":
            delete(event, client)
            send_response(event, context, "SUCCESS", {"Message": "Deleted"})
        else:
            send_response(event, context, "FAILED", {"Message": "Unexpected"})

    except Exception as ex:
        logger.error(ex)
        traceback.print_tb(ex.__traceback__)
        send_response(event, context, "FAILED", {"Message": "Exception"})
