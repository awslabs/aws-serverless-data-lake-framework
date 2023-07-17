import logging
import os
import json

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3 = boto3.client("s3", config=Config(signature_version="s3v4"))
ssm = boto3.client("ssm")
codecommit = boto3.client("codecommit")
cloudformation = boto3.client("cloudformation")
eventbridge = boto3.client("events")


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

def delete_team_cicd_stack(domain, environment, team_name, cloudformation_role):
    stack_name = f"sdlf-cicd-teams-{domain}-{environment}-{team_name}"
    cloudformation.delete_stack(
        StackName=stack_name,
        RoleARN=cloudformation_role,
    )
    return (stack_name, "stack_delete_complete")


def create_team_cicd_stack(domain, environment, team_name, template_body_url, child_account, cloudformation_role):
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
            approvalRuleTemplateContent='{"Version": "2018-11-08","DestinationReferences": ["refs/heads/master"],"Statements": [{"Type": "Approvers","NumberOfApprovalsNeeded": 1}]}',
        )
        codecommit.associate_approval_rule_template_with_repository(
            approvalRuleTemplateName=f"{team_name}-approval-to-production", repositoryName=repository
        )
    except codecommit.exceptions.ApprovalRuleTemplateNameAlreadyExistsException:
        pass


def lambda_handler(event, context):
    logger.info("EVENT: %s", event)
    region = event["region"]
    repo_name = event["detail"]["repositoryName"]
    account_id = event["account"]
    branch_name = event["detail"]["referenceName"]
    codecommit_branch_env_mapping = {"dev": "dev", "test": "test", "master": "prod"}
    environment = codecommit_branch_env_mapping[branch_name]
    logger.info("ENVIRONMENT: %s", environment)
    artifacts_bucket = os.getenv("ARTIFACTS_BUCKET")
    main_repository = os.getenv("MAIN_REPOSITORY")
    cicd_repository = os.getenv("CICD_REPOSITORY")
    cloudformation_role = os.getenv("CLOUDFORMATION_ROLE")

    template_cicd_domain = codecommit.get_file(
        repositoryName=cicd_repository, commitSpecifier=branch_name, filePath="template-cicd-domain.yaml"
    )["fileContent"].decode("utf-8")
    template_cicd_team = codecommit.get_file(
        repositoryName=cicd_repository, commitSpecifier=branch_name, filePath="template-cicd-team.yaml"
    )["fileContent"].decode("utf-8")
    template_cicd_domain_key = "template-cicd-sdlf-repositories/template-cicd-domain.yaml"
    s3.put_object(
        Bucket=artifacts_bucket,
        Body=template_cicd_domain,
        Key=template_cicd_domain_key
    )
    template_cicd_domain_url = s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": artifacts_bucket, "Key": template_cicd_domain_key},
        ExpiresIn=1200
    )
    #template_cicd_domain_url = f"https://{artifacts_bucket}.s3.{region}.amazonaws.com/{template_cicd_domain_key}"
    logger.info("template_cicd_domain_url: %s", template_cicd_domain_url)

    template_cicd_team_key = "template-cicd-sdlf-repositories/template-cicd-team.yaml"
    s3.put_object(
        Bucket=artifacts_bucket,
        Body=template_cicd_team,
        Key=template_cicd_team_key
    )
    template_cicd_team_url = s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": artifacts_bucket, "Key": template_cicd_team_key},
        ExpiresIn=1200
    )
    #template_cicd_team_url = f"https://{artifacts_bucket}.s3.{region}.amazonaws.com/{template_cicd_team_key}"
    logger.info("template_cicd_team_url: %s", template_cicd_team_url)

    repo_files = codecommit.get_folder(
        repositoryName=main_repository, commitSpecifier=branch_name, folderPath="/"
    )["files"]
    logger.info("REPOSITORY FILES: %s", repo_files)

    domain_files = [repo_file["absolutePath"] for repo_file in repo_files if repo_file["absolutePath"].endswith(f"-{environment}.yaml") and repo_file["absolutePath"].startswith("foundations-")]
    logger.info("DOMAIN FILES: %s", domain_files)

    team_files = [repo_file["absolutePath"] for repo_file in repo_files if repo_file["absolutePath"].endswith(f"-{environment}.yaml") and repo_file["absolutePath"].startswith("teams-")]
    logger.info("TEAM FILES: %s", team_files)

    domains = []
    # for each domain, create a CICD stack that will deploy the domain resources in the child account
    for domain_file in domain_files:
        domain = domain_file.split("-")[1]
        domains.append(f"{domain}-{environment}")

        template_domain = codecommit.get_file(
            repositoryName=main_repository, commitSpecifier=branch_name, filePath=domain_file
        )["fileContent"].decode("utf-8")
        child_account = ""
        for line in template_domain.split("\n"):
            if "pChildAccountId:" in line:
                child_account = line.split(":", 1)[-1].strip()
                break
        logger.info("pChildAccountId: %s", child_account)

        # create/update stacks for domains defined in git
        cloudformation_waiters = {"stack_create_complete": [], "stack_update_complete": []}
        stack_details = create_domain_cicd_stack(
            domain, environment, template_cicd_domain_url, child_account, cloudformation_role
        )
        if stack_details[1]:
            cloudformation_waiters[stack_details[1]].append(stack_details[0])
        cloudformation_create_waiter = cloudformation.get_waiter("stack_create_complete")
        cloudformation_update_waiter = cloudformation.get_waiter("stack_update_complete")
        for stack in cloudformation_waiters["stack_create_complete"]:
            cloudformation_create_waiter.wait(StackName=stack, WaiterConfig={"Delay": 30, "MaxAttempts": 10})
        for stack in cloudformation_waiters["stack_update_complete"]:
            cloudformation_update_waiter.wait(StackName=stack, WaiterConfig={"Delay": 30, "MaxAttempts": 10})

    logger.info("DOMAINS: %s", domains)
    # get the list of currently deployed domains, remove the CICD stack for domains that no longer exist in git
    paginator = cloudformation.get_paginator('list_stacks')
    existing_stacks_pages = paginator.paginate(
        StackStatusFilter=["CREATE_COMPLETE", "UPDATE_COMPLETE"],
        PaginationConfig={'MaxItems': 30}
    )
    existing_domains = [
        existing_stack["StackName"].removeprefix("sdlf-cicd-domain-")
        for existing_stack_page in existing_stacks_pages
        for existing_stack in existing_stack_page["StackSummaries"]
        if existing_stack["StackName"].startswith("sdlf-cicd-domain-") and existing_stack["StackName"].endswith(f"-{environment}")
    ]

    # remove stacks for domains that are no longer in git
    # note this whole lambda assumes domains aren't defined in files other than foundations-{domain}-{environment}.yaml
    legacy_domains = list(set(existing_domains) - set(domains))
    logger.info("LEGACY DOMAINS: %s", legacy_domains)
    cloudformation_waiters = {
        "stack_delete_complete": [],
    }
    for legacy_domain in legacy_domains:
        stack_details = delete_domain_cicd_stack(domain, environment, cloudformation_role)
        cloudformation_waiters[stack_details[1]].append(stack_details[0])
    cloudformation_waiter = cloudformation.get_waiter("stack_delete_complete")
    for stack in cloudformation_waiters["stack_delete_complete"]:
        cloudformation_waiter.wait(StackName=stack, WaiterConfig={"Delay": 30, "MaxAttempts": 10})


    for team_file in team_files:
        domain = team_file.split("-")[1]
        child_account = ssm.get_parameter(
            Name=f"/SDLF/Misc/Domains/{domain}/{environment}/AccountId",
        )["Parameter"]["Value"]
        template_teams = codecommit.get_file(
            repositoryName=main_repository, commitSpecifier=branch_name, filePath=team_file
        )["fileContent"].decode("utf-8")

        # very naive way of getting the list of teams to deploy
        teams = []
        for line in template_teams.split("\n"):
            if "pTeamName:" in line:
                teams.append(line.split(":", 1)[-1].strip())
        logger.info("TEAMS: %s", teams)
        paginator = cloudformation.get_paginator('list_stacks')
        existing_stacks_pages = paginator.paginate(
            StackStatusFilter=["CREATE_COMPLETE", "UPDATE_COMPLETE"],
            PaginationConfig={'MaxItems': 30}
        )
        existing_teams = [
            existing_stack["StackName"].removeprefix(f"sdlf-cicd-teams-{domain}-{environment}-")
            for existing_stack_page in existing_stacks_pages
            for existing_stack in existing_stack_page["StackSummaries"]
            if existing_stack["StackName"].startswith(f"sdlf-cicd-teams-{domain}-{environment}-")
        ]

        # create a role in the data domain that will be used to deploy a team's pipelines and 
        # create/update stacks for teams defined in git
        cloudformation_waiters = {"stack_create_complete": [], "stack_update_complete": []}
        for team in teams:
            stack_details = create_team_cicd_stack(
                domain, environment, team, template_cicd_team_url, child_account, cloudformation_role
            )
            if stack_details[1]:
                cloudformation_waiters[stack_details[1]].append(stack_details[0])
        cloudformation_create_waiter = cloudformation.get_waiter("stack_create_complete")
        cloudformation_update_waiter = cloudformation.get_waiter("stack_update_complete")
        for stack in cloudformation_waiters["stack_create_complete"]:
            cloudformation_create_waiter.wait(StackName=stack, WaiterConfig={"Delay": 30, "MaxAttempts": 10})
        for stack in cloudformation_waiters["stack_update_complete"]:
            cloudformation_update_waiter.wait(StackName=stack, WaiterConfig={"Delay": 30, "MaxAttempts": 10})

        # remove stacks for teams that are no longer in git
        # note this whole lambda assumes teams aren't defined in files other than teams-{domain}-{environment}.yaml
        legacy_teams = list(set(existing_teams) - set(teams))
        logger.info("LEGACY TEAMS: %s", legacy_teams)
        cloudformation_waiters = {
            "stack_delete_complete": [],
        }
        for legacy_team in legacy_teams:
            stack_details = delete_team_cicd_stack(domain, environment, legacy_team, cloudformation_role)
            cloudformation_waiters[stack_details[1]].append(stack_details[0])
            codecommit.delete_approval_rule_template(approvalRuleTemplateName=f"{domain}-{legacy_team}-approval-to-production")
        cloudformation_waiter = cloudformation.get_waiter("stack_delete_complete")
        for stack in cloudformation_waiters["stack_delete_complete"]:
            cloudformation_waiter.wait(StackName=stack, WaiterConfig={"Delay": 30, "MaxAttempts": 10})

        # create/update stacks for teams defined in git
        cloudformation_waiters = {"stack_create_complete": [], "stack_update_complete": []}
        for team in teams:
            stack_details = create_team_cicd_stack(
                domain, environment, team, template_cicd_team_url, child_account, cloudformation_role
            )
            if stack_details[1]:
                cloudformation_waiters[stack_details[1]].append(stack_details[0])
            create_codecommit_approval_rule(team, main_repository)
        cloudformation_create_waiter = cloudformation.get_waiter("stack_create_complete")
        cloudformation_update_waiter = cloudformation.get_waiter("stack_update_complete")
        for stack in cloudformation_waiters["stack_create_complete"]:
            cloudformation_create_waiter.wait(StackName=stack, WaiterConfig={"Delay": 30, "MaxAttempts": 10})
        for stack in cloudformation_waiters["stack_update_complete"]:
            cloudformation_update_waiter.wait(StackName=stack, WaiterConfig={"Delay": 30, "MaxAttempts": 10})

    # send back event to eventbus for the newly created CodePipeline pipelines to be triggered
    forwarded_event = {
        "Time": event["time"],
        "Source": "custom.aws.codecommit",
        "Resources": event["resources"],
        "DetailType": str(event["detail-type"]),
        "Detail": json.dumps(event["detail"])
    }
    logger.info("FORWARDED EVENT: %s", forwarded_event)
    entries = eventbridge.put_events(
        Entries=[forwarded_event],
    )
    logger.info("FORWARDING RESULT: %s", entries)

    return "Success"