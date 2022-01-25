import boto3
import json
import os
import sys
import traceback

from typing import List, Any
from boto3.dynamodb.types import TypeDeserializer, TypeSerializer
from botocore.exceptions import ClientError

deserializer = TypeDeserializer()
serializer = TypeSerializer()
DYNAMO_DEPENDENCIES_BYTABLE = os.getenv('DYNAMO_DEPENDENCIES_BYTABLE')
DYNAMO_DEPENDENCIES = os.getenv('DYNAMO_DEPENDENCIES')


def lambda_handler(event, context):
    def deserialize(data):
        if isinstance(data, list):
            return [deserialize(v) for v in data]

        if isinstance(data, dict):
            try:
                return deserializer.deserialize(data)
            except TypeError:
                return {k: deserialize(v) for k, v in data.items()}
        else:
            return data

    def serialize(data):
        try:
            return {k: serializer.serialize(v) for k, v in data.items() if v != ""}
        except ClientError as err:
            raise err

    def update_table_transforms(table_name, transform_list):
        expr_attr = serialize({':transforms': transform_list})
        response = dynamodb_client.update_item(
            TableName=DYNAMO_DEPENDENCIES_BYTABLE,
            Key=serialize({'table_name': table_name}),
            UpdateExpression='SET list_transforms = :transforms',
            ExpressionAttributeValues=expr_attr)
        return response

    def delete_table_transforms(table_name):
        response = dynamodb_client.delete_item(
            TableName=DYNAMO_DEPENDENCIES_BYTABLE,
            Key=serialize({'table_name': table_name}))
        return response

    def get_table_transforms(table_name):
        table_dependencies = dynamodb_client.get_item(
            TableName=DYNAMO_DEPENDENCIES_BYTABLE,
            Key=serialize({'table_name': table_name})) # dep['TableName']
        table_dependencies = deserialize(table_dependencies)
        return table_dependencies['Item']['list_transforms']

    print(event)
    dynamodb_client = boto3.client("dynamodb")

   # If new item arrive to dependencies table
    if event['Records'][0]['eventName'] == 'INSERT':
        item = event['Records'][0]['dynamodb']['NewImage']
        deserialized_item = deserialize(item)
        print(deserialized_item)
        transform_name = deserialized_item['dataset']
        dependencies = deserialized_item['dependencies']

        # for each dependency
        for dependency in dependencies:
            list_transforms = []
            table = dependency['TableName']
            print(f'Mapping transform "{transform_name}" to "{table}" table')
            try:
                list_transforms = get_table_transforms(table)
                if list_transforms.count(transform_name) == 0:
                    list_transforms.append(transform_name)
                    update_table_transforms(table, list_transforms)
            except:
                list_transforms.append(transform_name)
                update_table_transforms(table, list_transforms)

    # If dependencies table item was modified
    if event['Records'][0]['eventName'] == 'MODIFY':
        old_item = deserialize(event['Records'][0]['dynamodb']['OldImage'])
        new_item = deserialize(event['Records'][0]['dynamodb']['NewImage'])
        array_old = []
        array_new = []

        for i in old_item['dependencies']:
            array_old.append(i["TableName"])
        for i in new_item['dependencies']:
            array_new.append(i["TableName"])

        diff_old = list(set(array_old) - set(array_new))
        diff_new = list(set(array_new) - set(array_old))
        old_transform = old_item['dataset']
        new_transform = new_item['dataset']
        for table in diff_old:
            if array_old.count(table) != 0:
                print(f'Removing transform "{old_transform}" from "{table}" table')
                try:
                    list_transforms = get_table_transforms(table)
                    transformation_count = len(list_transforms)
                    if list_transforms.count(old_transform) != 0:
                        if transformation_count <= 1:
                            delete_table_transforms(table)
                        else:
                            list_transforms.remove(old_transform)
                            update_table_transforms(table, list_transforms)
                except Exception as exp:
                    exception_type, exception_value, exception_traceback = sys.exc_info()
                    traceback_string = traceback.format_exception(exception_type, exception_value,
                                                                  exception_traceback)
                    err_msg = json.dumps({
                        "errorType": exception_type.__name__,
                        "errorMessage": str(exception_value),
                        "stackTrace": traceback_string
                    })
                    print(err_msg)
        for table in diff_new:
            if array_new.count(table) != 0:
                list_transforms = []
                print(f'Mapping transform "{old_transform}" to "{table}" table')
                try:
                    list_transforms = get_table_transforms(table)
                    if list_transforms.count(new_transform) != 0:
                        list_transforms.append(new_transform)
                        update_table_transforms(table, list_transforms)
                except:
                    list_transforms.append(new_transform)
                    update_table_transforms(table, list_transforms)
               # agregar logica para cuando se agregó un registro                                                                                        transform_name))

    elif event['Records'][0]['eventName'] == 'REMOVE':
        old_item = deserialize(event['Records'][0]['dynamodb']['OldImage'])
        transform_name =old_item['dataset']
        dependencies = old_item['dependencies']
        # print(event['Records'][0]['dynamodb']['OldImage'])
        # tables=list_transforms["Items"]

        for dependency in dependencies:
            table = dependency['TableName']
            try:
                print(f'Removing transform "{transform_name}" from "{table}" table')
                list_transforms = get_table_transforms(table)
                transformation_count = len(list_transforms)
                if list_transforms.count(transform_name) != 0:
                    if transformation_count <= 1:
                        delete_table_transforms(table)
                    else:
                        list_transforms.remove(transform_name)
                        update_table_transforms(table, list_transforms)
            except Exception as exp:
                exception_type, exception_value, exception_traceback = sys.exc_info()
                traceback_string = traceback.format_exception(exception_type, exception_value,
                                                              exception_traceback)
                err_msg = json.dumps({
                    "errorType": exception_type.__name__,
                    "errorMessage": str(exception_value),
                    "stackTrace": traceback_string
                })
                print(err_msg)
                print(f'Error with dependencies-by-table, table {table} does not have dependencies')
