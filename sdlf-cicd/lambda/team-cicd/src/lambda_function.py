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
codecommit_endpoint_url = "https://codecommit." + os.getenv("AWS_REGION") + ".amazonaws.com"
codecommit = boto3.client("codecommit", endpoint_url=codecommit_endpoint_url)
codepipeline_endpoint_url = "https://codepipeline." + os.getenv("AWS_REGION") + ".amazonaws.com"
codepipeline = boto3.client("codepipeline", endpoint_url=codepipeline_endpoint_url)
cloudformation_endpoint_url = "https://cloudformation." + os.getenv("AWS_REGION") + ".amazonaws.com"
cloudformation = boto3.client("cloudformation", endpoint_url=cloudformation_endpoint_url)
kms_endpoint_url = "https://kms." + os.getenv("AWS_REGION") + ".amazonaws.com"
kms = boto3.client("kms", endpoint_url=kms_endpoint_url)
sts_endpoint_url = "https://sts." + os.getenv("AWS_REGION") + ".amazonaws.com"
sts = boto3.client("sts", endpoint_url=sts_endpoint_url)


def delete_domain_team_role_stack(cloudformation, team):
    stack_name = f"sdlf-cicd-team-role-{team}"
    cloudformation.delete_stack(
        StackName=stack_name,
    )
    return (stack_name, "stack_delete_complete")


def delete_team_pipeline_cicd_stack(domain, environment, team_name):
    stack_name = f"sdlf-cicd-teams-{domain}-{environment}-{team_name}"
    cloudformation.delete_stack(
        StackName=stack_name,
    )
    return (stack_name, "stack_delete_complete")


def create_team_repository_cicd_stack(domain, team_name, template_body_url, cloudformation_role):
    response = {}
    cloudformation_waiter_type = None
    stack_name = f"sdlf-cicd-teams-{domain}-{team_name}-repository"
    try:
        response = cloudformation.create_stack(
            StackName=stack_name,
            TemplateURL=template_body_url,
            Parameters=[
                {
                    "ParameterKey": "pDomain",
                    "ParameterValue": domain,
                    "UsePreviousValue": False,
                },
                {
                    "ParameterKey": "pTeamName",
                    "ParameterValue": team_name,
                    "UsePreviousValue": False,
                },
            ],
            Capabilities=[
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
                        "ParameterKey": "pDomain",
                        "ParameterValue": domain,
                        "UsePreviousValue": False,
                    },
                    {
                        "ParameterKey": "pTeamName",
                        "ParameterValue": team_name,
                        "UsePreviousValue": False,
                    },
                ],
                Capabilities=[
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


def create_team_pipeline_cicd_stack(
    domain,
    environment,
    team_name,
    crossaccount_team_role,
    template_body_url,
    child_account,
    cloudformation_role,
):
    response = {}
    cloudformation_waiter_type = None
    stack_name = f"sdlf-cicd-teams-{domain}-{environment}-{team_name}"
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
                {
                    "ParameterKey": "pTeamName",
                    "ParameterValue": team_name,
                    "UsePreviousValue": False,
                },
                {
                    "ParameterKey": "pCrossAccountTeamRole",
                    "ParameterValue": crossaccount_team_role,
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
                    {
                        "ParameterKey": "pTeamName",
                        "ParameterValue": team_name,
                        "UsePreviousValue": False,
                    },
                    {
                        "ParameterKey": "pCrossAccountTeamRole",
                        "ParameterValue": crossaccount_team_role,
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


def create_codecommit_approval_rule(team_name, repository):
    # unfortunately codecommit approval rule cannot be defined using cloudformation
    try:
        codecommit.create_approval_rule_template(
            approvalRuleTemplateName=f"{team_name}-approval-to-production",
            approvalRuleTemplateContent='{"Version": "2018-11-08","DestinationReferences": ["refs/heads/main"],"Statements": [{"Type": "Approvers","NumberOfApprovalsNeeded": 1}]}',
        )
        codecommit.associate_approval_rule_template_with_repository(
            approvalRuleTemplateName=f"{team_name}-approval-to-production",
            repositoryName=repository,
        )
    except codecommit.exceptions.ApprovalRuleTemplateNameAlreadyExistsException:
        pass


def prepare_cloudformation_template(artifacts_bucket, artifact_key, template_name, template_key):
    zipped_object = BytesIO(
        s3.get_object(
            Bucket=artifacts_bucket,
            Key=artifact_key,
        )["Body"].read()
    )
    temp_directory = mkdtemp()
    with zipfile.ZipFile(zipped_object, "r") as zip_ref:
        zip_ref.extractall(temp_directory)
    logger.info("ARTIFACT FILES: %s", os.listdir(temp_directory))
    template = os.path.join(temp_directory, template_name)
    template_key = "template-cicd-sdlf-repositories/" + template_key
    s3.upload_file(
        Filename=template,
        Bucket=artifacts_bucket,
        Key=template_key,
    )
    template_url = s3.generate_presigned_url(
        "get_object",
        Params={
            "Bucket": artifacts_bucket,
            "Key": template_key,
        },
        ExpiresIn=1200,
    )
    logger.info("template_url: %s", template_url)
    return template_url


def lambda_handler(event, context):
    try:
        branch = event["CodePipeline.job"]["data"]["actionConfiguration"]["configuration"]["UserParameters"]
        codecommit_branch_env_mapping = {"dev": "dev", "test": "test", "main": "prod"}
        environment = codecommit_branch_env_mapping[branch]
        logger.info("ENVIRONMENT: %s", environment)
        partition = os.getenv("AWS_PARTITION")
        devops_kms_key = os.getenv("DEVOPS_KMS_KEY")
        cloudformation_role = os.getenv("CLOUDFORMATION_ROLE")

        for artifact in event["CodePipeline.job"]["data"]["inputArtifacts"]:
            if artifact["name"] == "SourceCicdArtifact":
                cicd_artifact_location = artifact["location"]["s3Location"]
            if artifact["name"] == "SourceMainArtifact":
                main_artifact_location = artifact["location"]["s3Location"]
            if artifact["name"] == "TemplatePackage":
                package_artifact_location = artifact["location"]["s3Location"]

        artifacts_bucket = cicd_artifact_location["bucketName"]
        package_artifact_key = package_artifact_location["objectKey"]
        cicd_artifact_key = cicd_artifact_location["objectKey"]
        template_cicd_team_repository_url = prepare_cloudformation_template(
            artifacts_bucket, package_artifact_key, "packaged-template.yaml", "template-cicd-team-repository.yaml"
        )
        template_cicd_team_pipeline_url = prepare_cloudformation_template(
            artifacts_bucket, cicd_artifact_key, "template-cicd-team-pipeline.yaml", "template-cicd-team-pipeline.yaml"
        )

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

        domains = {}
        ###### GET LIST OF TEAMS ######
        for domain_file in domain_files:
            domain = domain_file.split("-")[1]
            domains[domain] = {"child_account": "", "teams": []}
            with open(os.path.join(temp_directory, domain_file), "r", encoding="utf-8") as template_domain:
                while line := template_domain.readline():
                    if "pChildAccountId:" in line:
                        domains[domain]["child_account"] = line.split(":", 1)[-1].strip()
                        if (
                            "AWS::AccountId" in domains[domain]["child_account"]
                        ):  # same account setup, usually for workshops/demo
                            domains[domain]["child_account"] = context.invoked_function_arn.split(":")[4]
                    elif "pTeamName:" in line:
                        domains[domain]["teams"].append(line.split(":", 1)[-1].strip())
                    elif "TemplateURL:" in line:  # teams can be declared in nested stacks
                        with open(
                            os.path.join(temp_directory, line.split(":", 1)[-1].strip()),
                            "r",
                            encoding="utf-8",
                        ) as nested_stack:
                            while nested_stack_line := nested_stack.readline():
                                if "pChildAccountId:" in nested_stack_line:
                                    domains[domain]["child_account"] = nested_stack_line.split(":", 1)[-1].strip()
                                    if (
                                        "AWS::AccountId" in domains[domain]["child_account"]
                                    ):  # same account setup, usually for workshops/demo
                                        domains[domain]["child_account"] = context.invoked_function_arn.split(":")[4]
                                elif "pTeamName:" in nested_stack_line:
                                    domains[domain]["teams"].append(nested_stack_line.split(":", 1)[-1].strip())
        logger.info("DATA DOMAIN DETAILS: %s", domains)

        ###### CLEANUP OLD TEAMS ######
        for domain, domain_details in domains.items():
            paginator = cloudformation.get_paginator("list_stacks")
            existing_stacks_pages = paginator.paginate(
                StackStatusFilter=["CREATE_COMPLETE", "UPDATE_COMPLETE"],
                PaginationConfig={"MaxItems": 30},
            )
            existing_teams = [
                existing_stack["StackName"].removeprefix(f"sdlf-cicd-teams-{domain}-{environment}-")
                for existing_stack_page in existing_stacks_pages
                for existing_stack in existing_stack_page["StackSummaries"]
                if existing_stack["StackName"].startswith(f"sdlf-cicd-teams-{domain}-{environment}-")
            ]

            # remove stacks for teams that are no longer in git
            legacy_teams = list(set(existing_teams) - set(domain_details["teams"]))
            logger.info("LEGACY TEAMS: %s", legacy_teams)
            cloudformation_waiters = {
                "stack_delete_complete": [],
            }

            # revoke grants for teams that will be removed
            for legacy_team in legacy_teams:
                grants = kms.list_grants(KeyId=devops_kms_key)["Grants"]
                grant_id = None
                for grant in grants:
                    if grant["GranteePrincipal"].endswith(f":role/sdlf-cicd-team-{legacy_team}"):
                        grant_id = grant["GrantId"]
                        break
                if grant_id:
                    kms.revoke_grant(KeyId=devops_kms_key, GrantId=grant_id)
                codecommit.delete_approval_rule_template(
                    approvalRuleTemplateName=f"{domain}-{legacy_team}-approval-to-production"
                )
                stack_details = delete_team_pipeline_cicd_stack(domain, environment, legacy_team)
                cloudformation_waiters[stack_details[1]].append(stack_details[0])

            cloudformation_waiter = cloudformation.get_waiter("stack_delete_complete")
            for stack in cloudformation_waiters["stack_delete_complete"]:
                cloudformation_waiter.wait(StackName=stack, WaiterConfig={"Delay": 30, "MaxAttempts": 10})

            # assume role in child account to be able to delete a cloudformation stack
            crossaccount_pipeline_role = (
                f"arn:{partition}:iam::{domain_details['child_account']}:role/sdlf-cicd-devops-crossaccount-pipeline"
            )
            crossaccount_role_session = sts.assume_role(
                RoleArn=crossaccount_pipeline_role, RoleSessionName="CrossAccountTeamLambda"
            )
            crossaccount_cloudformation = boto3.client(
                "cloudformation",
                aws_access_key_id=crossaccount_role_session["Credentials"]["AccessKeyId"],
                aws_secret_access_key=crossaccount_role_session["Credentials"]["SecretAccessKey"],
                aws_session_token=crossaccount_role_session["Credentials"]["SessionToken"],
                endpoint_url=cloudformation_endpoint_url,
            )
            cloudformation_waiters = {
                "stack_delete_complete": [],
            }
            for legacy_team in legacy_teams:
                # from this assumed role, delete a cloudformation stack
                stack_details = delete_domain_team_role_stack(crossaccount_cloudformation, legacy_team)
                cloudformation_waiters[stack_details[1]].append(stack_details[0])

            cloudformation_waiter = cloudformation.get_waiter("stack_delete_complete")
            for stack in cloudformation_waiters["stack_delete_complete"]:
                cloudformation_waiter.wait(StackName=stack, WaiterConfig={"Delay": 30, "MaxAttempts": 10})
            ###### END CLEANUP OLD TEAMS ######

        ###### CREATE STACKS FOR TEAMS ######
        for domain, domain_details in domains.items():
            # create team repository if it hasn't been created already
            cloudformation_waiters = {
                "stack_create_complete": [],
                "stack_update_complete": [],
            }
            for team in domain_details["teams"]:
                stack_details = create_team_repository_cicd_stack(
                    domain,
                    team,
                    template_cicd_team_repository_url,
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

            for team in domain_details["teams"]:
                repository_name = f"sdlf-main-{domain}-{team}"
                env_branches = ["dev", "test"]
                for env_branch in env_branches:
                    try:
                        codecommit.create_branch(
                            repositoryName=repository_name,
                            branchName=env_branch,
                            commitId=codecommit.get_branch(
                                repositoryName=repository_name,
                                branchName="main",
                            )["branch"]["commitId"],
                        )
                        logger.info(
                            "Branch %s created in repository %s",
                            env_branch,
                            repository_name,
                        )
                    except codecommit.exceptions.BranchNameExistsException:
                        logger.info(
                            "Branch %s already created in repository %s",
                            env_branch,
                            repository_name,
                        )

            # and create a CICD stack per team that will be used to deploy team resources in the child account
            cloudformation_waiters = {
                "stack_create_complete": [],
                "stack_update_complete": [],
            }
            for team in domain_details["teams"]:
                crossaccount_team_role = (
                    f"arn:{partition}:iam::{domain_details['child_account']}:role/sdlf-cicd-team-{team}"
                )
                stack_details = create_team_pipeline_cicd_stack(
                    domain,
                    environment,
                    team,
                    crossaccount_team_role,
                    template_cicd_team_pipeline_url,
                    domain_details["child_account"],
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

    except Exception as e:
        message = "Function exception: " + str(e)
        codepipeline.put_job_failure_result(
            jobId=event["CodePipeline.job"]["id"],
            failureDetails={"message": message, "type": "JobFailed"},
        )
        raise

    codepipeline.put_job_success_result(jobId=event["CodePipeline.job"]["id"])
    return "Success"
