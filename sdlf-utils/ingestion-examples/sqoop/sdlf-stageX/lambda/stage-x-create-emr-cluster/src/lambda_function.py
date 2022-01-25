import os
import json
import boto3
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)
emr_client = boto3.client('emr')
s3_client = boto3.resource('s3')
ssm_client = boto3.client('ssm')


def build_instace_groups():
    try:
        instace_groups = [
            {
                "InstanceRole": "MASTER",
                "InstanceType": os.environ['INSTANCE_TYPE_MASTER'],
                "Name": "Master instance group",
                "InstanceCount": 1
            }
        ]
        if int(os.environ['INSTANCE_COUNT_CORE_NODE']) > 0:
            instace_groups += [
                {
                    "InstanceRole": "CORE",
                    "InstanceType": os.environ['INSTANCE_TYPE_CORE'],
                    "Name": "Core instance group",
                    "InstanceCount": int(os.environ['INSTANCE_COUNT_CORE_NODE']),
                    "EbsConfiguration": {
                        "EbsBlockDeviceConfigs": [{
                            "VolumeSpecification": {
                                "SizeInGB": 100,
                                "VolumeType": "gp2"
                            },
                            "VolumesPerInstance": 1
                        }
                        ],
                        "EbsOptimized": True
                    }
                }
            ]
        if int(os.environ['INSTANCE_COUNT_TASK_NODE']) > 0:
            instace_groups += [{
                "InstanceRole": "TASK",
                "InstanceType": os.environ['INSTANCE_TYPE_TASK'],
                "Name": "Task instance group",
                "InstanceCount": int(os.environ['INSTANCE_COUNT_TASK_NODE'])}
            ]
    except Exception as e:
        logger.error("Fatal error", exc_info=True)
        raise e
    return instace_groups


def lambda_handler(event, context):
    try:
        kms_data_key = os.environ['KMS_DATA_KEY']
        emr_release = os.environ['EMR_RELEASE']
        emr_ec2_role = os.environ['EMR_EC2_ROLE']
        emr_role = os.environ['EMR_ROLE']
        subnet = os.environ['SUBNET_ID']
        logger.info(f'Evento: {event}')
        message = event  # ['body']
        team = message['team']
        env = message['env']
        pipeline = message['pipeline']
        cluster_name = event['clusterName']
        ssmresponse = ssm_client.get_parameter(
                Name='/SDLF/S3/ArtifactsBucket'
            )
        artifacts_bucket =  ssmresponse['Parameter']['Value']
        ssmresponse = ssm_client.get_parameter(
                Name='/SDLF/S3/CloudTrailBucket'
            )
        cloudtrail_bucket = ssmresponse['Parameter']['Value']
        response = emr_client.run_job_flow(
            Name=cluster_name,
            LogUri=f"s3://{cloudtrail_bucket}/{team}/{team}-{pipeline}-emr-sqoop-logs-x/",
            # LogEncryptionKmsKeyId=kms_data_key,
            ReleaseLabel=emr_release,
            VisibleToAllUsers=True,
            JobFlowRole=emr_ec2_role,
            ServiceRole=emr_role,
            Instances={
                'InstanceGroups': build_instace_groups(),
                'KeepJobFlowAliveWhenNoSteps': True,
                'TerminationProtected': False,
                'Ec2SubnetId': subnet
            },
            BootstrapActions=[
                {
                    'Name': 'Bootstrap scripts',
                    'ScriptBootstrapAction': {
                        'Path': f's3://{artifacts_bucket}/emr-sqoop-bootstrap/install_libs.sh',
                        # 'Args': [artifacts_bucket, team]
                        'Args': [artifacts_bucket, 'emr-sqoop-bootstrap']
                    }
                },
                {
                    'Name': 'Install Terminate Cluster Action',
                    'ScriptBootstrapAction': {
                        'Path': f's3://{artifacts_bucket}/emr-sqoop-bootstrap/manage_emr_sqoop_shutdown_install.sh',
                    }
                }
            ],
            Applications=[
                {
                    'Name': 'Hadoop'
                }, {
                    'Name': 'Hive'
                }, {
                    'Name': 'Sqoop'
                }
            ],
            Configurations=[
                {
                    "Classification": "hive-site",
                    "Properties": {
                        "hive.metastore.client.factory.class":
                            "com.amazonaws.glue.catalog.metastore.AWSGlueDataCatalogHiveClientFactory"
                    },
                    "Configurations": [
                    ]
                },
                {
                    "Classification": "presto-connector-hive",
                    "Properties": {
                        "hive.metastore.glue.datacatalog.enabled": "true"
                    },
                    "Configurations": [
                    ]
                }
            ],
            Tags=[
                {
                    'Key': 'Role',
                    'Value': 'EMR Data Lake'
                },
                {
                    'Key': 'Environment',
                    'Value': env
                }
            ],
            SecurityConfiguration=f'sdlf-{team}-emr-security-config',
            StepConcurrencyLevel=3)

    except Exception as e:
        logger.error("Fatal error", exc_info=True)
        raise e
    return response['JobFlowId']