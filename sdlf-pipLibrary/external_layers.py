"""
Create the Lambda Layer for the listed external libraries

MANDATORY args:
1 - Auxiliary S3 bucket

E.g. python3 MY_BUCKET_NAME
"""

import json
import sys
import urllib
from io import BytesIO
from time import sleep

import boto3
import botocore


def main():
    bucket = sys.argv[1]
    team_name = sys.argv[2]
    print(f"bucket: {bucket}")
    client_s3 = boto3.client(service_name="s3")
    client_lambda = boto3.client(service_name="lambda")
    client_ssm = boto3.client(service_name="ssm")
    with open('external_layers.json', 'r') as f:
        LAYERS_URLS = json.load(f)[0]

    for name, info in LAYERS_URLS.items():
        url = info["url"]
        file_name = url.rsplit(sep="/", maxsplit=1)[1]
        print(f"file_name: {file_name}")
        key = f"lambda_layers/{team_name}/{file_name}"
        print(f"key: {key}")
        print(f"Checking if this layer exists: {team_name}/{file_name}")
        try:
            client_s3.head_object(
                Bucket=bucket,
                Key=key,
            )
            print(f"s3://{bucket}/{key} already exists")
        except botocore.exceptions.ClientError as ex:
            if ex.response["Error"]["Code"] == "404":
                print(f"Downloading layer: {file_name}")
                print(f"url: {url}")
                response = urllib.request.urlopen(url)
                print(f"Uploading layers: {file_name}")
                client_s3.put_object(Body=BytesIO(response.read()),
                                     Bucket=bucket,
                                     Key=key)
                print(f"s3://{bucket}/{key} uploaded")
                sleep(5)
            else:
                raise ex
        res = client_lambda.publish_layer_version(
            LayerName=f"sdlf-{team_name}-{name}",
            Description=url,
            Content={"S3Bucket": bucket, "S3Key": key},
            CompatibleRuntimes=info["runtimes"],
        )
        client_ssm.put_parameter(
            Name=f"/SDLF/Lambda/{team_name}/{name}",
            Description=url,
            Value=res["LayerVersionArn"],
            Type="String",
            Overwrite=True
        )


if __name__ == "__main__":
    main()
