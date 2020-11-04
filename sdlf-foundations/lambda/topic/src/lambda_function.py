import json
import os
import logging
import traceback

import boto3

from urllib.request import Request, urlopen

logger = logging.getLogger()
logger.setLevel(logging.INFO)
logging.basicConfig(
    format='%(levelname)s %(threadName)s [%(filename)s:%(lineno)d] %(message)s',
    datefmt='%Y-%m-%d:%H:%M:%S',
    level=logging.INFO
)

try:
    logger.info("Container initialization completed")

except Exception as e:
    logger.error(e, exc_info=True)
    init_failed = e


def isHttpStatus200(response_data):
    return isExpectedHttpStatusCode(response_data, 200)


def isExpectedHttpStatusCode(response_data, status_code):
    if response_data is not None and \
        'ResponseMetadata' in response_data and \
        'HTTPStatusCode' in response_data['ResponseMetadata'] and \
            response_data['ResponseMetadata']['HTTPStatusCode'] == status_code:
        return True

    return False


def send_response(e, c, rs, rd):
    """
    Packages response and send signals to CloudFormation
    :param e: The event given to this Lambda function
    :param c: Context object, as above
    :param rs: Returned status to be sent back to CFN
    :param rd: Returned data to be sent back to CFN
    """
    r = json.dumps({
        "Status": rs,
        "Reason": "CloudWatch Log Stream: " + c.log_stream_name,
        "PhysicalResourceId": e['LogicalResourceId'],
        "StackId": e['StackId'],
        "RequestId": e['RequestId'],
        "LogicalResourceId": e['LogicalResourceId'],
        "Data": rd
    })
    d = str.encode(r)
    h = {
        'content-type': '',
        'content-length': str(len(d))
    }
    req = Request(e['ResponseURL'], data=d, method='PUT', headers=h)
    r = urlopen(req)
    logger.info("Status message: {} {}".format(r.msg, r.getcode()))


def get_ssm_parameter(logger, ssm_param_name):
    """
    Gets an SSM parameter.
    :param logger: Logger used for Lambda messages sent to CloudWatch
    :param ssm_param_name: Name of the SSM parameter
    """

    client = boto3.client('ssm')
    parameter = client.get_parameter(Name=ssm_param_name)
    ssm_param_value = parameter['Parameter']['Value']

    logger.debug("Getting the value for parameter {} = {}".format(
        ssm_param_name, ssm_param_value))

    return ssm_param_value


def get_team_metadata_from_dynamo(team_name, table=None):
    """
    Gets whole team metadata.
    :param team_name: Name of the team that holds metadata
    :param table: DynamoDB table (if passed, no new boto3 resource assignment is done)
    """

    if table is None:
        dynamodb = boto3.resource('dynamodb')
        table_name = get_ssm_parameter(
            logger, os.getenv('TEAM_METADATA_TABLE_SSM_PARAM'))
        table = dynamodb.Table(table_name)

    response_data = table.get_item(
        Key={
            'team': team_name
        }
    )

    if isHttpStatus200(response_data) and 'Item' in response_data:
        return response_data['Item']


def remove_subscription_from_dynamo(team_name, topic_arn, endpoint):
    """
    Deregisters an SNS topic subscription from DynamoDB table, organized by team names.
    :param team_name: Name of the team that holds metadata
    :param topic_arn: Topic ARN of the subscription
    :param endpoint: Endpoint to be added to DynamoDB control table
    """

    dynamodb = boto3.resource('dynamodb')
    table_name = get_ssm_parameter(
        logger, os.getenv('TEAM_METADATA_TABLE_SSM_PARAM'))
    table = dynamodb.Table(table_name)
    team_item = get_team_metadata_from_dynamo(team_name, table)
    item = None

    if team_item is None:
        logger.info("Team %s was not found into DynammoDB table.", team_name)

    else:
        item = team_item
        for i in range(len(item['sns_subscriptions'])):
            if item['sns_subscriptions'][i]['topic_arn'] == topic_arn \
                    and item['sns_subscriptions'][i]['endpoint'] == endpoint:
                del item['sns_subscriptions'][i]
                break

        response_data = table.put_item(
            Item=item
        )

        if isHttpStatus200(response_data):
            logger.info("Item updated %s into DynammoDB table.", item)


def get_subscription_arn_from_dynamo(team_name, topic_arn, endpoint):
    """
    Get a subscription ARN base on the endpoint filter informed.
    :param team_name: Name of the team that holds metadata
    :param topic_arn: Topic ARN of the subscription
    :param endpoint: Endpoint to be found in DynamoDB control table
    """

    team_item = get_team_metadata_from_dynamo(team_name)
    if team_item and 'sns_subscriptions' in team_item:
        sns_subscriptions = list(filter(lambda d: d['topic_arn'] in [topic_arn]
                                        and d['endpoint'] in [endpoint], team_item['sns_subscriptions']))
        # It should have exist only one subscription ARN for a specific endpoint/SNS topic
        if sns_subscriptions is not None and len(sns_subscriptions) == 1:
            subscription_arn = sns_subscriptions[0]['subscription_arn']
            logger.debug("Subscription ARN %s", subscription_arn)

            return subscription_arn

    return None


def unsubscribe_endpoint(logger, team_name, topic_arn, endpoint):
    """
    Unsubscribes and endpoint to an SNS topic and deregisters that from DynamoDB table,
    organized by team names.
    :param logger: Logger used for Lambda messages sent to CloudWatch
    :param team_name: Name of the team that holds metadata
    :param topic_arn: Topic ARN for unsubscription
    :param endpoint: Endpoint to be unsubscribed from Topic ARN
    """

    error_code = None
    subscription_arn = get_subscription_arn_from_dynamo(
        team_name, topic_arn, endpoint)
    if subscription_arn is None:
        raise Exception(
            "Failed, subscription ARN not found, when unsubscribing %s from topic %s.", endpoint, topic_arn)

    try:
        client = boto3.client('sns')
        response_data = client.unsubscribe(
            SubscriptionArn=subscription_arn
        )
    except Exception as ex:
        error_code = ex.response.get("Error", {}).get("Code")
        if error_code == "InvalidParameter":
            logger.info(
                "Endpoint %s is still pending confirmation, so no unsubscription required.", endpoint)

    # Endpoint was removed from parameters-ENV.json file but the subscription was not confirmed.
    # Due to that, we have to ignore this error (try/catch above) but need to remove from dynamodb.
    if error_code == "InvalidParameter" or isHttpStatus200(response_data):
        remove_subscription_from_dynamo(team_name, topic_arn, endpoint)
        logger.info(
            "Endpoint %s unsubscribed from topic %s.", endpoint, topic_arn)
    else:
        raise Exception(
            "Failed when unsubscribing %s from topic %s.", endpoint, topic_arn)


def register_subscription_into_dynamo(team_name, topic_arn, endpoint, subscription_arn):
    """
    Registers an SNS topic subscription into DynamoDB table, organized by team names.
    :param team_name: Name of the team that holds metadata
    :param topic_arn: Topic ARN of the subscription
    :param endpoint: Endpoint to be added to DynamoDB control table
    :param subscription_arn: Subscription ARN of the endpoint
    """

    dynamodb = boto3.resource('dynamodb')
    table_name = get_ssm_parameter(
        logger, os.getenv('TEAM_METADATA_TABLE_SSM_PARAM'))
    table = dynamodb.Table(table_name)
    team_item = get_team_metadata_from_dynamo(team_name, table)
    item = None
    item_status = None

    if team_item is None:
        item = {
            'team': team_name,
            'sns_subscriptions': [
                {
                    'endpoint': endpoint,
                    'subscription_arn': subscription_arn,
                    'topic_arn': topic_arn

                }
            ]
        }
        item_status = "added"

    else:
        item = team_item
        for subscription in item['sns_subscriptions']:
            if subscription['topic_arn'] == topic_arn and subscription['endpoint'] == endpoint:
                subscription['subscription_arn'] = subscription_arn
                item_status = "updated"
                break

        # New item
        if item_status is None:
            subscription = {
                'endpoint': endpoint,
                'subscription_arn': subscription_arn,
                'topic_arn': topic_arn
            }

            item['sns_subscriptions'].append(subscription)
            item_status = "added"

    response_data = table.put_item(
        Item=item
    )

    if isHttpStatus200(response_data):
        logger.info("Item %s %s into DynammoDB table.", item_status, item)


def subscribe_endpoint(logger, team_name, topic_arn, endpoint, protocol):
    """
    Subscribes and endpoint to an SNS topic and registers that into DynamoDB table,
    organized by team names.
    :param logger: Logger used for Lambda messages sent to CloudWatch
    :param team_name: Name of the team that holds metadata
    :param topic_arn: Topic ARN for subscription
    :param endpoint: Endpoint to be subscribed to Topic ARN
    :param protocol: Protocol of the endpoint being subscribed
    """

    # Only does if there is no subscription yet for endpoint/SNS Topic
    if get_subscription_arn_from_dynamo(team_name, topic_arn, endpoint) is None:
        client = boto3.client('sns')

        response_data = client.subscribe(
            TopicArn=topic_arn,
            Protocol=protocol,
            Endpoint=endpoint,
            ReturnSubscriptionArn=True
        )

        if isHttpStatus200(response_data):
            register_subscription_into_dynamo(
                team_name, topic_arn, endpoint, response_data['SubscriptionArn'])

            logger.info(
                "Endpoint %s subscribed to topic %s at team %s.", endpoint, topic_arn, team_name)
        else:
            raise Exception(
                "Failed when subscribing %s to topic %s at team %s.", endpoint, topic_arn, team_name)
    else:
        logger.info(
            "Endpoint %s is already subscribed to topic %s at team %s.", endpoint, topic_arn, team_name)


def adjust_subscriptions(event, logger):
    """
    Adjusts subscription according to the parameters informed into the Custom Resource.
    :param event: Event sent from CFN when the custom resource is created
    :param logger: Logger used for Lambda messages sent to CloudWatch
    """

    resource_properties = event['ResourceProperties']
    team_name = resource_properties['TeamName']
    topic_arn = resource_properties['TopicArn']
    subscription_protocol = resource_properties['SubscriptionProtocol']
    subscription_endpoints = resource_properties['SubscriptionEndpoints']
    old_resource_properties = event['OldResourceProperties'] if 'OldResourceProperties' in event else None
    old_subscription_endpoints = old_resource_properties[
        'SubscriptionEndpoints'] if old_resource_properties else None

    if subscription_endpoints:
        for endpoint in subscription_endpoints:
            if old_subscription_endpoints is None or endpoint not in old_subscription_endpoints:
                subscribe_endpoint(logger, team_name, topic_arn,
                                   endpoint, subscription_protocol)

    if old_subscription_endpoints:
        for endpoint in old_subscription_endpoints:
            if subscription_endpoints is None or endpoint not in subscription_endpoints:
                unsubscribe_endpoint(logger, team_name, topic_arn, endpoint)


def lambda_handler(event, context):
    """
    Entrypoint to Lambda.
    :param event: The event given to this Lambda function
    :param context: Context object containing Lambda metadata
    """
    logger.info(event)
    request_type = event['RequestType']

    try:
        if request_type == 'Create' or request_type == 'Update':
            adjust_subscriptions(event, logger)

            message = None
            if request_type == 'Create':
                message = {
                    "Message": "Created"
                }
            elif request_type == 'Update':
                message = {
                    "Message": "Updated"
                }

            send_response(event, context, "SUCCESS", message)

        else:
            send_response(event, context, "SUCCESS", {
                          "Message": "Function Not Applicable"})

    except Exception as ex:
        logger.error(ex)
        traceback.print_tb(ex.__traceback__)
        send_response(
            event,
            context,
            "FAILED",
            {
                "Message": "Exception"
            }
        )
