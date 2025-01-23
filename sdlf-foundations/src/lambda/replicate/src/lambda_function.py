import json
import logging
import os
from datetime import UTC, datetime

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

glue_endpoint_url = "https://glue." + os.getenv("AWS_REGION") + ".amazonaws.com"
glue = boto3.client("glue", endpoint_url=glue_endpoint_url)
dynamodb = boto3.client("dynamodb")
ssm_endpoint_url = "https://ssm." + os.getenv("AWS_REGION") + ".amazonaws.com"
ssm = boto3.client("ssm", endpoint_url=ssm_endpoint_url)
lf_endpoint_url = "https://lakeformation." + os.getenv("AWS_REGION") + ".amazonaws.com"
lf = boto3.client("lakeformation", endpoint_url=lf_endpoint_url)
schemas_table = ssm.get_parameter(Name="/SDLF/Dynamo/DataSchemas")["Parameter"]["Value"]


def get_current_time():
    return datetime.now(UTC).isoformat()


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
        logger.info(f"{permissions} Permissions granted to {iam_arn} for table {database}.{table}")
    except Exception as e:
        logger.error(f"Error granting {permissions} permissions to {iam_arn} for table {database}.{table} . {e}")


def build_table_item(team, dataset, table):
    table_item = {}
    table_item["created_at"] = {"S": get_current_time()}
    table_item["updated_at"] = {"S": get_current_time()}
    table_item["team"] = {"S": team}
    table_item["dataset"] = {"S": dataset}
    table_item["table"] = {"S": table["Name"]}
    table_item["name"] = {"S": f"{team}-{dataset}-{table['Name']}"}
    table_item["glue_table"] = {"S": table["Name"]}
    table_item["glue_database"] = {"S": table["DatabaseName"]}
    table_item["status"] = {"S": "ACTIVE"}
    table_item["type"] = {"S": table["TableType"]}
    table_item["schema"] = {"S": str(sorted(table["StorageDescriptor"]["Columns"], key=lambda i: i["Name"]))}
    table_item["schema_version"] = {"N": "0"}
    return table_item


def get_table_item(table_id):
    response = dynamodb.get_item(TableName=schemas_table, Key={"name": {"S": table_id}})
    return response["Item"]


def put_table_item(table_item):
    response = dynamodb.put_item(TableName=schemas_table, Item=table_item)
    return response


def update_table_item(table_id, schema):
    dynamodb.update_item(
        TableName=schemas_table,
        Key={"name": {"S": table_id}},
        UpdateExpression="set #s=:s, updated_at=:t, schema_version=schema_version+:val",
        ExpressionAttributeValues={":s": {"S": schema}, ":t": {"S": get_current_time()}, ":val": {"N": "1"}},
        ExpressionAttributeNames={"#s": "schema"},
        ReturnValues="UPDATED_NEW",
    )


def delete_table_item(table_id):
    response = dynamodb.delete_item(TableName=schemas_table, Key={"name": {"S": table_id}})
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

        logger.info(f"Processing {type_of_change} change on {dataset} dataset (team: {team})")

        if type_of_change in ["CreateTable"]:
            changed_tables = event["detail"]["changedTables"]
            for table_name in changed_tables:
                logger.info(f"Processing table: {table_name}")
                try:
                    table = glue.get_table(DatabaseName=database_name, Name=table_name)["Table"]
                    table_item = build_table_item(team, dataset, table)
                    put_table_item(table_item)
                    iam_arn = ssm.get_parameter(Name="/SDLF/IAM/DataLakeAdminRoleArn")["Parameter"]["Value"]
                    grant_table_permissions(iam_arn, database_name, table_name, ["SELECT", "ALTER", "INSERT", "DELETE"])
                except Exception as e:
                    logger.error(f"Fatal error for table {table_name} in database {database_name}")
                    logger.error(e)
                    pass  # Pass to unblock valid tables

        elif type_of_change in ["DeleteTable", "BatchDeleteTable"]:
            changed_tables = event["detail"]["changedTables"]
            for table_name in changed_tables:
                logger.info(f"Processing table: {table_name}")
                table_id = f"{team}-{dataset}-{table_name}"
                delete_table_item(table_id)

        elif type_of_change in ["UpdateTable"]:
            table_name = event["detail"]["tableName"]
            logger.info(f"Processing table: {table_name}")
            table_id = f"{team}-{dataset}-{table_name}"
            table = glue.get_table(DatabaseName=database_name, Name=table_name)["Table"]
            new_schema = str(sorted(table["StorageDescriptor"]["Columns"], key=lambda i: i["Name"]))
            current_item = get_table_item(table_id)
            if current_item["schema"] != new_schema:
                update_table_item(table_id, new_schema)

        else:
            logger.info(f"Unsupported {type_of_change} operation")
    except Exception as e:
        logger.error("Fatal error", exc_info=True)
        raise e
    return {"body": json.dumps("Success")}
