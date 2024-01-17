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
ssm_endpoint_url = "https://ssm." + os.getenv("AWS_REGION") + ".amazonaws.com"
ssm = boto3.client("ssm", endpoint_url=ssm_endpoint_url)
codepipeline_endpoint_url = "https://codepipeline." + os.getenv("AWS_REGION") + ".amazonaws.com"
codepipeline = boto3.client("codepipeline", endpoint_url=codepipeline_endpoint_url)
cloudformation_endpoint_url = "https://cloudformation." + os.getenv("AWS_REGION") + ".amazonaws.com"
cloudformation = boto3.client("cloudformation", endpoint_url=cloudformation_endpoint_url)


def delete_domain_cicd_stack(domain, environment, cloudformation_role):
    stack_name = f"sdlf-cicd-domain-{domain}-{environment}"
    cloudformation.delete_stack(
        StackName=stack_name,
        RoleARN=cloudformation_role,
    )
    return (stack_name, "stack_delete_complete")


def create_domain_cicd_stack(domain, environment, template_body_url, child_account, cloudformation_role):
    response = {}
    cloudformation_waiter_type = None
    stack_name = f"sdlf-cicd-domain-{domain}-{environment}"
    try:
        response = cloudformation.create_stack(
            StackName=stack_name,
            TemplateURL=template_body_url,
            Parameters=[
                {
                    "ParameterKey": "pChildAccountId",
                    "ParameterValue": child_account,
                    "UsePreviousValue": False,
                },
                {
                    "ParameterKey": "pDomain",
                    "ParameterValue": domain,
                    "UsePreviousValue": False,
                },
                {
                    "ParameterKey": "pEnvironment",
                    "ParameterValue": environment,
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
                        "ParameterKey": "pChildAccountId",
                        "ParameterValue": child_account,
                        "UsePreviousValue": False,
                    },
                    {
                        "ParameterKey": "pDomain",
                        "ParameterValue": domain,
                        "UsePreviousValue": False,
                    },
                    {
                        "ParameterKey": "pEnvironment",
                        "ParameterValue": environment,
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
        branch = event["CodePipeline.job"]["data"]["actionConfiguration"]["configuration"]["UserParameters"]
        codecommit_branch_env_mapping = {"dev": "dev", "test": "test", "main": "prod"}
        environment = codecommit_branch_env_mapping[branch]
        logger.info("ENVIRONMENT: %s", environment)
        cloudformation_role = os.getenv("CLOUDFORMATION_ROLE")

        for artifact in event["CodePipeline.job"]["data"]["inputArtifacts"]:
            if artifact["name"] == "SourceCicdArtifact":
                cicd_artifact_location = artifact["location"]["s3Location"]
            if artifact["name"] == "SourceMainArtifact":
                main_artifact_location = artifact["location"]["s3Location"]

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

        template_cicd_domain = os.path.join(temp_directory, "template-cicd-domain.yaml")
        template_cicd_domain_key = "template-cicd-sdlf-repositories/template-cicd-domain.yaml"
        s3.upload_file(
            Filename=template_cicd_domain,
            Bucket=artifacts_bucket,
            Key=template_cicd_domain_key,
        )
        template_cicd_domain_url = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": artifacts_bucket, "Key": template_cicd_domain_key},
            ExpiresIn=1200,
        )
        logger.info("template_cicd_domain_url: %s", template_cicd_domain_url)

        main_artifact_key = main_artifact_location["objectKey"]
        zipped_object = BytesIO(
            s3.get_object(
                Bucket=artifacts_bucket,
                Key=main_artifact_key,
            )["Body"].read()
        )
        temp_directory = mkdtemp()
        with zipfile.ZipFile(zipped_object, "r") as zip_ref:
            zip_ref.extractall(temp_directory)

        main_artifact_files = os.listdir(temp_directory)
        logger.info("REPOSITORY FILES: %s", main_artifact_files)

        domain_files = [
            main_artifact_file
            for main_artifact_file in main_artifact_files
            if main_artifact_file.endswith(f"-{environment}.yaml") and main_artifact_file.startswith("datadomain-")
        ]
        logger.info("DATA DOMAIN FILES: %s", domain_files)

        domains = []
        # for each domain, create a CICD stack that will be used to deploy domain resources in the child account
        for domain_file in domain_files:
            domain = domain_file.split("-")[1]
            domains.append(f"{domain}-{environment}")

            child_account = ""
            with open(os.path.join(temp_directory, domain_file), "r", encoding="utf-8") as template_domain:
                while line := template_domain.readline():
                    if "pChildAccountId:" in line:
                        child_account = line.split(":", 1)[-1].strip()
                        if "AWS::AccountId" in child_account:  # same account setup, usually for workshops/demo
                            child_account = context.invoked_function_arn.split(":")[4]
                        break
                    if "TemplateURL:" in line:
                        with open(
                            os.path.join(temp_directory, line.split(":", 1)[-1].strip()),
                            "r",
                            encoding="utf-8",
                        ) as nested_stack:
                            while nested_stack_line := nested_stack.readline():
                                if "pChildAccountId:" in nested_stack_line:
                                    child_account = nested_stack_line.split(":", 1)[-1].strip()
                                    if (
                                        "AWS::AccountId" in child_account
                                    ):  # same account setup, usually for workshops/demo
                                        child_account = context.invoked_function_arn.split(":")[4]
                                    break
                    if child_account:
                        break
            logger.info("pChildAccountId: %s", child_account)

            # create/update stacks for domains defined in git
            cloudformation_waiters = {
                "stack_create_complete": [],
                "stack_update_complete": [],
            }
            stack_details = create_domain_cicd_stack(
                domain,
                environment,
                template_cicd_domain_url,
                child_account,
                cloudformation_role,
            )
            if stack_details[1]:
                cloudformation_waiters[stack_details[1]].append(stack_details[0])
            cloudformation_create_waiter = cloudformation.get_waiter("stack_create_complete")
            cloudformation_update_waiter = cloudformation.get_waiter("stack_update_complete")
            for stack in cloudformation_waiters["stack_create_complete"]:
                cloudformation_create_waiter.wait(StackName=stack, WaiterConfig={"Delay": 30, "MaxAttempts": 10})
            for stack in cloudformation_waiters["stack_update_complete"]:
                cloudformation_update_waiter.wait(StackName=stack, WaiterConfig={"Delay": 30, "MaxAttempts": 10})

        logger.info("DATA DOMAINS: %s", domains)
        # get the list of currently deployed domains, remove the CICD stack for domains that no longer exist in git
        paginator = cloudformation.get_paginator("list_stacks")
        existing_stacks_pages = paginator.paginate(
            StackStatusFilter=["CREATE_COMPLETE", "UPDATE_COMPLETE"],
            PaginationConfig={"MaxItems": 30},
        )
        existing_domains = [
            existing_stack["StackName"].removeprefix("sdlf-cicd-domain-")
            for existing_stack_page in existing_stacks_pages
            for existing_stack in existing_stack_page["StackSummaries"]
            if existing_stack["StackName"].startswith("sdlf-cicd-domain-")
            and existing_stack["StackName"].endswith(f"-{environment}")
        ]

        # remove stacks for domains that are no longer in git
        # note this whole lambda assumes domains aren't defined in files other than foundations-{domain}-{environment}.yaml
        legacy_domains = list(set(existing_domains) - set(domains))
        logger.info("LEGACY DATA DOMAINS: %s", legacy_domains)
        cloudformation_waiters = {
            "stack_delete_complete": [],
        }
        for legacy_domain in legacy_domains:
            stack_details = delete_domain_cicd_stack(legacy_domain, environment, cloudformation_role)
            cloudformation_waiters[stack_details[1]].append(stack_details[0])
        cloudformation_waiter = cloudformation.get_waiter("stack_delete_complete")
        for stack in cloudformation_waiters["stack_delete_complete"]:
            cloudformation_waiter.wait(StackName=stack, WaiterConfig={"Delay": 30, "MaxAttempts": 10})

    except Exception as e:
        message = "Function exception: " + str(e)
        codepipeline.put_job_failure_result(
            jobId=event["CodePipeline.job"]["id"],
            failureDetails={"message": message, "type": "JobFailed"},
        )
        raise

    codepipeline.put_job_success_result(jobId=event["CodePipeline.job"]["id"])
    return "Success"
