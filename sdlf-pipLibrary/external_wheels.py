"""
Upload the Glue Wheel for the listed external libraries

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


def add_wheels(name, info, team_name, bucket, client_s3, client_ssm):
    url = info["url"]
    file_name = url.rsplit(sep="/", maxsplit=1)[1]
    print(f"file_name: {file_name}")
    key = f"wheels/{team_name}/{file_name}"
    print(f"key: {key}")

    try:
        print(f"Downloading wheel: {file_name}")
        print(f"url: {url}")
        response = urllib.request.urlopen(url)
        print(f"Uploading wheel: {file_name}")
        client_s3.put_object(Body=BytesIO(response.read()), Bucket=bucket, Key=key)
        print(f"s3://{bucket}/{key} uploaded")
        sleep(5)
    except botocore.exceptions.ClientError as ex:
        raise ex

    client_ssm.put_parameter(
        Name=f"/SDLF/Wheels/{team_name}/{name}",
        Description=url,
        Value="s3://{}/{}".format(bucket, key),
        Type="String",
        Overwrite=True,
    )


def main():
    bucket = sys.argv[1]
    team_name = sys.argv[2]
    print(f"bucket: {bucket}")
    client_s3 = boto3.client(service_name="s3")
    client_ssm = boto3.client(service_name="ssm")
    with open("external_wheels.json", "r") as f:
        WHEEL_URLS = json.load(f)[0]

    for name, info in WHEEL_URLS.items():
        add_wheels(name, info, team_name, bucket, client_s3, client_ssm)


if __name__ == "__main__":
    main()
