import json
import logging
import os
from datetime import datetime

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

glue_client = boto3.client("glue")
dynamodb = boto3.resource("dynamodb")
ssm = boto3.client("ssm")
lf = boto3.client("lakeformation")
schemas_table = dynamodb.Table("octagon-DataSchemas-{}".format(os.environ["ENV"]))


def get_current_time():
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def grant_table_permissions(iam_arn, database, table, permissions):
    """
    Grants all permissions for a given iam arn to a given aws catalog table
    :param iam_arn: iam user or role arn permissions are applied to
    :param database: database to which permissions will be granted
    :param table: table to which permissions will be granted
    :param permissions: list of permissions to be applied
    :return: None.
    """
    try:
        lf.grant_permissions(
            Principal={"DataLakePrincipalIdentifier": iam_arn},
            Resource={"Table": {"DatabaseName": database, "Name": table}},
            Permissions=permissions,
        )
        logger.info("{} Permissions granted to {} for table {}.{}".format(permissions, iam_arn, database, table))
    except Exception as e:
        logger.error(
            "Error granting {} permissions to {} for table {}.{} . {}".format(permissions, iam_arn, database, table, e)
        )


def build_table_item(team, dataset, table):
    table_item = {}
    table_item["created_at"] = get_current_time()
    table_item["updated_at"] = get_current_time()
    table_item["team"] = team
    table_item["dataset"] = dataset
    table_item["table"] = table["Name"]
    table_item["name"] = "{}-{}-{}".format(team, dataset, table["Name"])
    table_item["glue_table"] = table["Name"]
    table_item["glue_database"] = table["DatabaseName"]
    table_item["status"] = "ACTIVE"
    table_item["type"] = table["TableType"]
    table_item["schema"] = sorted(table["StorageDescriptor"]["Columns"], key=lambda i: i["Name"])
    table_item["schema_version"] = 0
    table_item["data_quality_enabled"] = "Y"
    return table_item


def get_table_item(table_id):
    response = schemas_table.get_item(Key={"name": table_id})
    return response["Item"]


def put_table_item(table_item):
    response = schemas_table.put_item(Item=table_item)
    return response


def update_table_item(table_id, schema):
    schemas_table.update_item(
        Key={"name": table_id},
        UpdateExpression="set #s=:s, updated_at=:t, schema_version=schema_version+:val",
        ExpressionAttributeValues={":s": schema, ":t": get_current_time(), ":val": 1},
        ExpressionAttributeNames={"#s": "schema"},
        ReturnValues="UPDATED_NEW",
    )
    return


def delete_table_item(table_id):
    response = schemas_table.delete_item(Key={"name": table_id})
    return response


def lambda_handler(event, context):
    """Replicates Glue catalog table to Octagon Schemas DynamoDB table

    Arguments:
        event {dict} -- Dictionary of Glue Data Catalog Database State Change
        context {dict} -- Dictionary with details on Lambda context

    Returns:
        {dict}
    """
    try:
        type_of_change = event["detail"]["typeOfChange"]
        database_name = event["detail"]["databaseName"]
        team = database_name.split("_")[-3]
        dataset = database_name.split("_")[-2]

        logger.info("Processing {} change on {} dataset".format(type_of_change, dataset))

        if type_of_change in ["CreateTable"]:
            changed_tables = event["detail"]["changedTables"]
            for table_name in changed_tables:
                logger.info("Processing table: {}".format(table_name))
                try:
                    table = glue_client.get_table(DatabaseName=database_name, Name=table_name)["Table"]
                    table_item = build_table_item(team, dataset, table)
                    put_table_item(table_item)
                    iam_arn = ssm.get_parameter(Name="/SDLF/IAM/DataLakeAdminRoleArn")["Parameter"]["Value"]
                    grant_table_permissions(iam_arn, database_name, table_name, ["SELECT", "ALTER", "INSERT", "DELETE"])
                except Exception as e:
                    logger.error("Fatal error for table {} in database {}".format(table_name, database_name))
                    logger.error(e)
                    pass  # Pass to unblock valid tables

        elif type_of_change in ["DeleteTable", "BatchDeleteTable"]:
            changed_tables = event["detail"]["changedTables"]
            for table_name in changed_tables:
                logger.info("Processing table: {}".format(table_name))
                table_id = "{}-{}-{}".format(team, dataset, table_name)
                delete_table_item(table_id)

        elif type_of_change in ["UpdateTable"]:
            table_name = event["detail"]["tableName"]
            logger.info("Processing table: {}".format(table_name))
            table_id = "{}-{}-{}".format(team, dataset, table_name)
            table = glue_client.get_table(DatabaseName=database_name, Name=table_name)["Table"]
            new_schema = sorted(table["StorageDescriptor"]["Columns"], key=lambda i: i["Name"])
            current_item = get_table_item(table_id)
            if current_item["schema"] != new_schema:
                update_table_item(table_id, new_schema)

        else:
            logger.info("Unsupported {} operation".format(type_of_change))
    except Exception as e:
        logger.error("Fatal error", exc_info=True)
        raise e
    return {"body": json.dumps("Success")}
