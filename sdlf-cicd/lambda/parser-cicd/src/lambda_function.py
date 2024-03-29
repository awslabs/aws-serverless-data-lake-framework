import json
import logging
import os
import zipfile
from io import BytesIO
from tempfile import mkdtemp

import boto3
from botocore.client import Config

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3 = boto3.client("s3", config=Config(signature_version="s3v4"))
codepipeline_endpoint_url = "https://codepipeline." + os.getenv("AWS_REGION") + ".amazonaws.com"
codepipeline = boto3.client("codepipeline", endpoint_url=codepipeline_endpoint_url)
cloudformation_endpoint_url = "https://cloudformation." + os.getenv("AWS_REGION") + ".amazonaws.com"
cloudformation = boto3.client("cloudformation", endpoint_url=cloudformation_endpoint_url)


def lambda_handler(event, context):
    try:
        branch = event["CodePipeline.job"]["data"]["actionConfiguration"]["configuration"]["UserParameters"]
        codecommit_branch_env_mapping = {"dev": "dev", "test": "test", "main": "prod"}
        environment = codecommit_branch_env_mapping[branch]
        logger.info("ENVIRONMENT: %s", environment)

        for artifact in event["CodePipeline.job"]["data"]["inputArtifacts"]:
            if artifact["name"] == "SourceMainArtifact":
                main_artifact_location = artifact["location"]["s3Location"]

        main_artifact_key = main_artifact_location["objectKey"]
        zipped_object = BytesIO(
            s3.get_object(
                Bucket=main_artifact_location["bucketName"],
                Key=main_artifact_key,
            )["Body"].read()
        )
        temp_directory = mkdtemp()
        with zipfile.ZipFile(zipped_object, "r") as zip_ref:
            zip_ref.extractall(temp_directory)

        main_artifact_files = os.listdir(temp_directory)
        logger.info("MAIN REPOSITORY FILES: %s", main_artifact_files)

        domain_files = [
            main_artifact_file
            for main_artifact_file in main_artifact_files
            if main_artifact_file.endswith(f"-{environment}.yaml") and main_artifact_file.startswith("datadomain-")
        ]
        logger.info("DATA DOMAIN FILES: %s", domain_files)

        domains = {}
        ###### GET ALL DOMAIN DETAILS: ORG, ACCOUNT ID, LIST OF TEAMS ######
        # note this whole lambda assumes domains aren't defined in files other than datadomain-{domain}-{environment}.yaml and nested stacks
        for domain_file in domain_files:
            domain = domain_file.split("-")[1]
            domains[domain] = dict(org="", child_account="", teams=set())
            with open(os.path.join(temp_directory, domain_file), "r", encoding="utf-8") as template_domain:
                while line := template_domain.readline():
                    if "pChildAccountId:" in line:
                        domains[domain]["child_account"] = line.split(":", 1)[-1].strip()
                        if (
                            "AWS::AccountId" in domains[domain]["child_account"]
                        ):  # same account setup, usually for workshops/demo
                            domains[domain]["child_account"] = context.invoked_function_arn.split(":")[4]
                    elif "pOrg:" in line:
                        domains[domain]["org"] = line.split(":", 1)[-1].strip()
                    elif "pTeamName:" in line:
                        domains[domain]["teams"].add(line.split(":", 1)[-1].strip())
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
                                elif "pOrg:" in nested_stack_line:
                                    domains[domain]["org"] = nested_stack_line.split(":", 1)[-1].strip()
                                elif "pTeamName:" in nested_stack_line:
                                    domains[domain]["teams"].add(nested_stack_line.split(":", 1)[-1].strip())
        logger.info("DATA DOMAIN DETAILS: %s", domains)

        ###### GET LIST OF CURRENTLY-DEPLOYED DOMAINS AND TEAMS ######
        paginator = cloudformation.get_paginator("list_stacks")
        existing_stacks_pages = paginator.paginate(
            StackStatusFilter=["CREATE_COMPLETE", "UPDATE_COMPLETE", "UPDATE_ROLLBACK_COMPLETE"],
        )
        stacks_already_deployed = []
        for existing_stack_page in existing_stacks_pages:
            for existing_stack in existing_stack_page["StackSummaries"]:
                if (
                    existing_stack["StackName"].startswith("sdlf-cicd-teams-")
                    and existing_stack["StackName"].rsplit("-", 2)[1] == environment
                ) or (
                    existing_stack["StackName"].startswith("sdlf-cicd-domain-")
                    and existing_stack["StackName"].endswith(f"-{environment}")
                ):
                    stacks_already_deployed.append(existing_stack["StackName"])
        logger.info("CURRENTLY-DEPLOYED DATA DOMAINS AND TEAMS: %s", stacks_already_deployed)

        ###### GET LIST OF LEGACY DOMAINS AND TEAMS ######
        # domains and teams that are currently deployed, but no longer in git
        # generate a list of stack names that would be created given what is in git
        # all stacks already deployed but not part of this list are stacks to remove
        stacks_to_create = []
        for domain, domain_details in domains.items():
            stacks_to_create.append(f"sdlf-cicd-domain-{domain}-{environment}")
            for team in domain_details["teams"]:
                stacks_to_create.append(f"sdlf-cicd-teams-{domain}-{environment}-{team}")

        stacks_to_remove = list(set(stacks_already_deployed) - set(stacks_to_create))
        logger.info("LEGACY DATA DOMAINS AND TEAMS: %s", stacks_to_remove)

    except Exception as e:
        message = "Function exception: " + str(e)
        codepipeline.put_job_failure_result(
            jobId=event["CodePipeline.job"]["id"],
            failureDetails={"message": message, "type": "JobFailed"},
        )
        raise

    # build combined json-as-string to pass as a CodePipeline output variable
    combined_output = json.dumps(dict(branch=branch, domains=domains, stacks_to_remove=stacks_to_remove), default=list)
    codepipeline.put_job_success_result(
        jobId=event["CodePipeline.job"]["id"],
        outputVariables={
            "Domains": combined_output,
        },
    )
    return "Success"
