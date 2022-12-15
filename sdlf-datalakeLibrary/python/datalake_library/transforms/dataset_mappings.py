import json
import sys

import boto3
from botocore.exceptions import ClientError


def main():
    team_name = sys.argv[1]
    env_name = sys.argv[2]
    client_dynamodb = boto3.client(service_name="dynamodb")
    f = open("./dataset_mappings.json")
    data = json.load(f)
    f.close()

    for j in data:
        dataset_name = j.get("name")
        d = {}
        for k, v in j.get("transforms").items():
            d[k] = {"S": v}
        try:
            client_dynamodb.update_item(
                TableName="octagon-Datasets-{}".format(env_name),
                Key={"name": {"S": "{}-{}".format(team_name, dataset_name)}},
                ExpressionAttributeNames={"#N": "name", "#T": "transforms"},
                ExpressionAttributeValues={":t": {"M": d}},
                UpdateExpression="SET #T = :t",
                ConditionExpression="attribute_exists(#N)",
            )
            print("Dataset {} transforms successfully updated".format(dataset_name))
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                print("Dataset {} does not exist in table - Skipping".format(dataset_name))
            else:
                raise (e)


if __name__ == "__main__":
    main()
