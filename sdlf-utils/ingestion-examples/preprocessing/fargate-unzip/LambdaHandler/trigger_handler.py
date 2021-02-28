import os
import json
import boto3

print('Loading function')

s3 = boto3.client('s3')
ecs = boto3.client('ecs')

ecs_cluster_name = os.environ["EC2_CLUSTER_NAME"]
task_definition = os.environ["TASK_DEFINITION"]
subnet_id = os.environ["SUBNET_ID"]
dst_bucket = os.environ["DST_BUCKET"]

def lambda_handler(event, context):
    try:
        for sqs_record in event['Records']:
            records = json.loads(sqs_record['body'])['Records']
            for record in records:
                # print('record: ' + str(record))
                src_bucket = record['s3']['bucket']['name']
                src_key = record['s3']['object']['key']
                src_filename = src_key.split('/')[-1]
                # size in GB
                file_size = record['s3']['object']['size'] >> 30
                if file_size == 0:
                    file_size = 1
                file_size = file_size+1
                ram = 2 - (file_size % 2) + file_size*4
                cores = 1
                if ram > 30:
                    ram = 30
                    cores = 4
                elif ram > 16:
                    cores = 4
                elif ram > 8:
                    cores = 2
                response = ecs.run_task(
                    cluster = ecs_cluster_name,
                    launchType = 'FARGATE',
                    taskDefinition = task_definition,
                    count = 1,
                    platformVersion = 'LATEST',
                    networkConfiguration = {
                        'awsvpcConfiguration': {
                            'subnets': [
                                subnet_id,
                            ],
                            'assignPublicIp': 'ENABLED'
                        }
                    },
                    overrides = {
                        'cpu': str(cores * 1024),
                        'memory': str(ram * 1024),
                        'containerOverrides': [
                            {
                                'name': 'UnzipShellDocker',
                                'environment': [
                                    {
                                        'name': 'SRC_BUCKET',
                                        'value': src_bucket
                                    },
                                    {
                                        'name': 'DEST_BUCKET',
                                        'value': dst_bucket
                                    },
                                    {
                                        'name': 'SRC_KEY',
                                        'value': src_key
                                    }
                                ]
                            }
                        ]
                    }
                )
                print(response)
    except Exception as e:
        print(e)
        raise e
