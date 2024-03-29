import json
import logging
import os
import zipfile
from io import BytesIO
from tempfile import mkdtemp

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3 = boto3.client("s3", config=Config(signature_version="s3v4"))
codepipeline_endpoint_url = "https://codepipeline." + os.getenv("AWS_REGION") + ".amazonaws.com"
codepipeline = boto3.client("codepipeline", endpoint_url=codepipeline_endpoint_url)
kms_endpoint_url = "https://kms." + os.getenv("AWS_REGION") + ".amazonaws.com"
kms = boto3.client("kms", endpoint_url=kms_endpoint_url)


def create_domain_team_role_stack(
    cloudformation, team, artifacts_bucket, kms_key, environment, domain, template_body_url, cloudformation_role
):
    response = {}
    cloudformation_waiter_type = None
    stack_name = f"sdlf-cicd-team-role-{team}"
    try:
        response = cloudformation.create_stack(
            StackName=stack_name,
            TemplateURL=template_body_url,
            Parameters=[
                {
                    "ParameterKey": "pDevOpsArtifactsBucket",
                    "ParameterValue": artifacts_bucket,
                    "UsePreviousValue": False,
                },
                {
                    "ParameterKey": "pDevOpsKMSKey",
                    "ParameterValue": kms_key,
                    "UsePreviousValue": False,
                },
                {
                    "ParameterKey": "pDomain",
                    "ParameterValue": domain,
                    "UsePreviousValue": False,
                },
                {
                    "ParameterKey": "pTeamName",
                    "ParameterValue": team,
                    "UsePreviousValue": False,
                },
                {
                    "ParameterKey": "pEnvironment",
                    "ParameterValue": environment,
                    "UsePreviousValue": False,
                },
                {
                    "ParameterKey": "pEnableLambdaLayerBuilder",
                    "ParameterValue": os.getenv("ENABLE_LAMBDA_LAYER_BUILDER"),
                    "UsePreviousValue": False,
                },
                {
                    "ParameterKey": "pEnableGlueJobDeployer",
                    "ParameterValue": os.getenv("ENABLE_GLUE_JOB_DEPLOYER"),
                    "UsePreviousValue": False,
                },
            ],
            Capabilities=[
                "CAPABILITY_NAMED_IAM",
                "CAPABILITY_AUTO_EXPAND",
            ],
            RoleARN=cloudformation_role,
            Tags=[
                {"Key": "Framework", "Value": "sdlf"},
            ],
        )
        cloudformation_waiter_type = "stack_create_complete"
    except cloudformation.exceptions.AlreadyExistsException:
        try:
            response = cloudformation.update_stack(
                StackName=stack_name,
                TemplateURL=template_body_url,
                Parameters=[
                    {
                        "ParameterKey": "pDevOpsArtifactsBucket",
                        "ParameterValue": artifacts_bucket,
                        "UsePreviousValue": False,
                    },
                    {
                        "ParameterKey": "pDevOpsKMSKey",
                        "ParameterValue": kms_key,
                        "UsePreviousValue": False,
                    },
                    {
                        "ParameterKey": "pDomain",
                        "ParameterValue": domain,
                        "UsePreviousValue": False,
                    },
                    {
                        "ParameterKey": "pTeamName",
                        "ParameterValue": team,
                        "UsePreviousValue": False,
                    },
                    {
                        "ParameterKey": "pEnvironment",
                        "ParameterValue": environment,
                        "UsePreviousValue": False,
                    },
                    {
                        "ParameterKey": "pEnableLambdaLayerBuilder",
                        "ParameterValue": os.getenv("ENABLE_LAMBDA_LAYER_BUILDER"),
                        "UsePreviousValue": False,
                    },
                    {
                        "ParameterKey": "pEnableGlueJobDeployer",
                        "ParameterValue": os.getenv("ENABLE_GLUE_JOB_DEPLOYER"),
                        "UsePreviousValue": False,
                    },
                ],
                Capabilities=[
                    "CAPABILITY_NAMED_IAM",
                    "CAPABILITY_AUTO_EXPAND",
                ],
                RoleARN=cloudformation_role,
                Tags=[
                    {"Key": "Framework", "Value": "sdlf"},
                ],
            )
            cloudformation_waiter_type = "stack_update_complete"
        except ClientError as err:
            if "No updates are to be performed" in err.response["Error"]["Message"]:
                pass
            else:
                raise err

    logger.info("RESPONSE: %s", response)
    return (stack_name, cloudformation_waiter_type)


def lambda_handler(event, context):
    try:
        codepipeline_userparameters = json.loads(
            event["CodePipeline.job"]["data"]["actionConfiguration"]["configuration"]["UserParameters"]
        )
        branch = codepipeline_userparameters["branch"]
        codecommit_branch_env_mapping = {"dev": "dev", "test": "test", "main": "prod"}
        environment = codecommit_branch_env_mapping[branch]
        logger.info("ENVIRONMENT: %s", environment)
        domains = codepipeline_userparameters["domains"]
        logger.info("DOMAINS: %s", domains)
        partition = os.getenv("AWS_PARTITION")
        devops_kms_key = os.getenv("DEVOPS_KMS_KEY")

        for artifact in event["CodePipeline.job"]["data"]["inputArtifacts"]:
            if artifact["name"] == "SourceCicdArtifact":
                cicd_artifact_location = artifact["location"]["s3Location"]

        artifacts_bucket = cicd_artifact_location["bucketName"]
        cicd_artifact_key = cicd_artifact_location["objectKey"]
        zipped_object = BytesIO(
            s3.get_object(
                Bucket=artifacts_bucket,
                Key=cicd_artifact_key,
            )["Body"].read()
        )
        temp_directory = mkdtemp()
        with zipfile.ZipFile(zipped_object, "r") as zip_ref:
            zip_ref.extractall(temp_directory)
        logger.info("REPOSITORY FILES: %s", os.listdir(temp_directory))

        template_cicd_domain_team_role = os.path.join(temp_directory, "template-cicd-domain-team-role.yaml")
        template_cicd_domain_team_role_key = "template-cicd-sdlf-repositories/template-cicd-domain-team-role.yaml"
        s3.upload_file(
            Filename=template_cicd_domain_team_role,
            Bucket=artifacts_bucket,
            Key=template_cicd_domain_team_role_key,
        )
        template_cicd_domain_team_role_url = s3.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": artifacts_bucket,
                "Key": template_cicd_domain_team_role_key,
            },
            ExpiresIn=1200,
        )
        logger.info("template_cicd_domain_url: %s", template_cicd_domain_team_role_url)

        # for each domain, create a CICD stack for each team inside that domain, that will be used to deploy team resources in the child account
        for domain, domain_details in domains.items():
            # assume role in child account to be able to deploy a cloudformation stack
            crossaccount_pipeline_role = (
                f"arn:{partition}:iam::{domain_details['child_account']}:role/sdlf-cicd-devops-crossaccount-pipeline"
            )
            sts_endpoint_url = "https://sts." + os.getenv("AWS_REGION") + ".amazonaws.com"
            sts = boto3.client("sts", endpoint_url=sts_endpoint_url)
            crossaccount_role_session = sts.assume_role(
                RoleArn=crossaccount_pipeline_role, RoleSessionName="CrossAccountTeamLambda"
            )
            cloudformation_endpoint_url = "https://cloudformation." + os.getenv("AWS_REGION") + ".amazonaws.com"
            cloudformation = boto3.client(
                "cloudformation",
                aws_access_key_id=crossaccount_role_session["Credentials"]["AccessKeyId"],
                aws_secret_access_key=crossaccount_role_session["Credentials"]["SecretAccessKey"],
                aws_session_token=crossaccount_role_session["Credentials"]["SessionToken"],
                endpoint_url=cloudformation_endpoint_url,
            )

            # from this assumed role, deploy a cloudformation stack
            # this stack creates a role in the data domain that will be used to deploy a team's pipelines and datasets
            crossaccount_cloudformation_role = (
                f"arn:{partition}:iam::{domain_details['child_account']}:role/sdlf-cicd-team"
            )
            cloudformation_waiters = {
                "stack_create_complete": [],
                "stack_update_complete": [],
            }
            for team in domain_details["teams"]:
                stack_details = create_domain_team_role_stack(
                    cloudformation,
                    team,
                    artifacts_bucket,
                    devops_kms_key,
                    environment,
                    domain,
                    template_cicd_domain_team_role_url,
                    crossaccount_cloudformation_role,
                )
                if stack_details[1]:
                    cloudformation_waiters[stack_details[1]].append(stack_details[0])
            cloudformation_create_waiter = cloudformation.get_waiter("stack_create_complete")
            cloudformation_update_waiter = cloudformation.get_waiter("stack_update_complete")
            for stack in cloudformation_waiters["stack_create_complete"]:
                cloudformation_create_waiter.wait(StackName=stack, WaiterConfig={"Delay": 30, "MaxAttempts": 10})
            for stack in cloudformation_waiters["stack_update_complete"]:
                cloudformation_update_waiter.wait(StackName=stack, WaiterConfig={"Delay": 30, "MaxAttempts": 10})

            crossaccount_team_roles = []
            grants_ids = []
            for team in domain_details["teams"]:
                crossaccount_team_role = (
                    f"arn:{partition}:iam::{domain_details['child_account']}:role/sdlf-cicd-team-{team}"
                )
                crossaccount_team_roles.append(crossaccount_team_role)
                # unfortunately kms grants cannot be defined using cloudformation
                grant_id = kms.create_grant(
                    KeyId=devops_kms_key,
                    GranteePrincipal=crossaccount_team_role,
                    Operations=[
                        "DescribeKey",
                        "Decrypt",
                        "Encrypt",
                        "GenerateDataKey",
                        "GenerateDataKeyPair",
                        "GenerateDataKeyPairWithoutPlaintext",
                        "GenerateDataKeyWithoutPlaintext",
                        "ReEncryptFrom",
                        "ReEncryptTo",
                    ],
                )["GrantId"]
                grants_ids.append(grant_id)
            # revoke all grants for the same grantee principal except the ones that were just created
            grants = kms.list_grants(KeyId=devops_kms_key)["Grants"]
            for grant in grants:
                if grant["GranteePrincipal"] in crossaccount_team_roles and grant["GrantId"] not in grants_ids:
                    kms.revoke_grant(KeyId=devops_kms_key, GrantId=grant["GrantId"])

    except Exception as e:
        message = "Function exception: " + str(e)
        codepipeline.put_job_failure_result(
            jobId=event["CodePipeline.job"]["id"],
            failureDetails={"message": message, "type": "JobFailed"},
        )
        raise

    codepipeline.put_job_success_result(jobId=event["CodePipeline.job"]["id"])
    return "Success"
