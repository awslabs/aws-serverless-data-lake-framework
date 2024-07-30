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
ssm_endpoint_url = "https://ssm." + os.getenv("AWS_REGION") + ".amazonaws.com"
ssm = boto3.client("ssm", endpoint_url=ssm_endpoint_url)
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

git_platform = ssm.get_parameter(Name="/SDLF/Misc/GitPlatform")["Parameter"]["Value"]


def delete_cicd_stack(stack, cloudformation_role):
    cloudformation.delete_stack(
        StackName=stack,
        RoleARN=cloudformation_role,
    )
    return (stack, "stack_delete_complete")


def create_domain_cicd_stack(domain, environment, template_body_url, child_account, cloudformation_role):
    response = {}
    cloudformation_waiter_type = None
    stack_name = f"sdlf-cicd-domain-{domain}-{environment}"
    stack_parameters = [
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
            "ParameterKey": "pMainRepository",
            "ParameterValue": f"/SDLF/{git_platform}/Main{git_platform}",
            "UsePreviousValue": False,
        },
        {
            "ParameterKey": "pCicdRepository",
            "ParameterValue": f"/SDLF/{git_platform}/Cicd{git_platform}",
            "UsePreviousValue": False,
        },
        {
            "ParameterKey": "pFoundationsRepository",
            "ParameterValue": f"/SDLF/{git_platform}/Foundations{git_platform}",
            "UsePreviousValue": False,
        },
        {
            "ParameterKey": "pTeamRepository",
            "ParameterValue": f"/SDLF/{git_platform}/Team{git_platform}",
            "UsePreviousValue": False,
        },
    ]
    stack_arguments = dict(
        StackName=stack_name,
        TemplateURL=template_body_url,
        Parameters=stack_parameters,
        Capabilities=[
            "CAPABILITY_NAMED_IAM",
            "CAPABILITY_AUTO_EXPAND",
        ],
        RoleARN=cloudformation_role,
        Tags=[
            {"Key": "Framework", "Value": "sdlf"},
        ],
    )

    try:
        response = cloudformation.create_stack(**stack_arguments)
        cloudformation_waiter_type = "stack_create_complete"
    except cloudformation.exceptions.AlreadyExistsException:
        try:
            response = cloudformation.update_stack(**stack_arguments)
            cloudformation_waiter_type = "stack_update_complete"
        except ClientError as err:
            if "No updates are to be performed" in err.response["Error"]["Message"]:
                pass
            else:
                raise err

    logger.info("RESPONSE: %s", response)
    return (stack_name, cloudformation_waiter_type)


def delete_domain_team_role_stack(cloudformation, team):
    stack_name = f"sdlf-cicd-team-role-{team}"
    cloudformation.delete_stack(
        StackName=stack_name,
    )
    return (stack_name, "stack_delete_complete")


def create_team_repository_cicd_stack(domain, team_name, template_body_url, cloudformation_role):
    response = {}
    cloudformation_waiter_type = None
    stack_name = f"sdlf-cicd-teams-{domain}-{team_name}-repository"
    stack_parameters = [
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
    ]
    stack_arguments = dict(
        StackName=stack_name,
        TemplateURL=template_body_url,
        Parameters=stack_parameters,
        Capabilities=[
            "CAPABILITY_AUTO_EXPAND",
        ],
        RoleARN=cloudformation_role,
        Tags=[
            {"Key": "Framework", "Value": "sdlf"},
        ],
    )

    try:
        response = cloudformation.create_stack(**stack_arguments)
        cloudformation_waiter_type = "stack_create_complete"
    except cloudformation.exceptions.AlreadyExistsException:
        try:
            response = cloudformation.update_stack(**stack_arguments)
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
    stack_parameters = [
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
        {
            "ParameterKey": "pCicdRepository",
            "ParameterValue": f"/SDLF/{git_platform}/Cicd{git_platform}",
            "UsePreviousValue": False,
        },
        {
            "ParameterKey": "pDatalakeLibraryRepository",
            "ParameterValue": f"/SDLF/{git_platform}/DatalakeLibrary{git_platform}",
            "UsePreviousValue": False,
        },
        {
            "ParameterKey": "pPipelineRepository",
            "ParameterValue": f"/SDLF/{git_platform}/Pipeline{git_platform}",
            "UsePreviousValue": False,
        },
        {
            "ParameterKey": "pStageARepository",
            "ParameterValue": f"/SDLF/{git_platform}/StageA{git_platform}",
            "UsePreviousValue": False,
        },
        {
            "ParameterKey": "pStageLambdaRepository",
            "ParameterValue": f"/SDLF/{git_platform}/StageLambda{git_platform}",
            "UsePreviousValue": False,
        },
        {
            "ParameterKey": "pStageBRepository",
            "ParameterValue": f"/SDLF/{git_platform}/StageB{git_platform}",
            "UsePreviousValue": False,
        },
        {
            "ParameterKey": "pStageGlueRepository",
            "ParameterValue": f"/SDLF/{git_platform}/StageGlue{git_platform}",
            "UsePreviousValue": False,
        },
        {
            "ParameterKey": "pDatasetRepository",
            "ParameterValue": f"/SDLF/{git_platform}/Dataset{git_platform}",
            "UsePreviousValue": False,
        },
    ]
    stack_arguments = dict(
        StackName=stack_name,
        TemplateURL=template_body_url,
        Parameters=stack_parameters,
        Capabilities=[
            "CAPABILITY_NAMED_IAM",
            "CAPABILITY_AUTO_EXPAND",
        ],
        RoleARN=cloudformation_role,
        Tags=[
            {"Key": "Framework", "Value": "sdlf"},
        ],
    )

    try:
        response = cloudformation.create_stack(**stack_arguments)
        cloudformation_waiter_type = "stack_create_complete"
    except cloudformation.exceptions.AlreadyExistsException:
        try:
            response = cloudformation.update_stack(**stack_arguments)
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
        codepipeline_userparameters = json.loads(
            event["CodePipeline.job"]["data"]["actionConfiguration"]["configuration"]["UserParameters"]
        )
        branch = codepipeline_userparameters["branch"]
        codecommit_branch_env_mapping = {"dev": "dev", "test": "test", "main": "prod"}
        environment = codecommit_branch_env_mapping[branch]
        logger.info("ENVIRONMENT: %s", environment)
        domains = codepipeline_userparameters["domains"]
        logger.info("DOMAINS: %s", domains)
        stacks_to_remove = codepipeline_userparameters["stacks_to_remove"]
        logger.info("STACKS TO REMOVE: %s", stacks_to_remove)
        partition = os.getenv("AWS_PARTITION")
        devops_kms_key = os.getenv("DEVOPS_KMS_KEY")
        main_repository_prefix = os.getenv("MAIN_REPOSITORY_PREFIX")
        cloudformation_role = os.getenv("CLOUDFORMATION_ROLE")

        for artifact in event["CodePipeline.job"]["data"]["inputArtifacts"]:
            if artifact["name"] == "SourceCicdArtifact":
                cicd_artifact_location = artifact["location"]["s3Location"]
            if artifact["name"] == "TemplatePackage":
                package_artifact_location = artifact["location"]["s3Location"]

        artifacts_bucket = cicd_artifact_location["bucketName"]
        package_artifact_key = package_artifact_location["objectKey"]
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

        template_cicd_team_repository_url = prepare_cloudformation_template(
            artifacts_bucket, package_artifact_key, "packaged-template.yaml", "template-cicd-team-repository.yaml"
        )
        template_cicd_team_pipeline_url = prepare_cloudformation_template(
            artifacts_bucket, cicd_artifact_key, "template-cicd-team-pipeline.yaml", "template-cicd-team-pipeline.yaml"
        )

        ###### CLEAN UP LEGACY TEAMS AND DOMAINS ######
        grants = kms.list_grants(KeyId=devops_kms_key)["Grants"]
        for stack in stacks_to_remove:
            if stack.startswith("sdlf-cicd-teams-"):
                grant_id = None
                stack_team = stack.rsplit("-")[0]
                stack_domain = stack.rsplit("-")[2]
                child_accountid = ssm.get_parameter(Name=f"/SDLF/Misc/Domains/{stack_domain}/{environment}/AccountId")[
                    "Parameter"
                ]["Value"]
                # KMS grants cannot be created with CloudFormation and have been created using boto3 ; clean up has to be done the same way
                for grant in grants:
                    if grant["GranteePrincipal"].endswith(
                        f":role/sdlf-cicd-team-{stack_team}"
                    ):  # TODO can probably access the element directly instead of looping
                        grant_id = grant["GrantId"]
                        break
                if grant_id:
                    kms.revoke_grant(KeyId=devops_kms_key, GrantId=grant_id)
                # CodeCommit approval rule template cannot be created with CloudFormation and have been created using boto3 ; clean up has to be done the same way
                codecommit.delete_approval_rule_template(
                    approvalRuleTemplateName=f"{stack_domain}-{stack_team}-approval-to-production"
                )
                cloudformation_waiters = {
                    "stack_delete_complete": [],
                }
                stack_details = delete_cicd_stack(stack, cloudformation_role)
                cloudformation_waiters[stack_details[1]].append(stack_details[0])

                # a team CICD role has been created in the child account: assume role in child account to be able to delete the cloudformation stack
                crossaccount_pipeline_role = (
                    f"arn:{partition}:iam::{child_accountid}:role/sdlf-cicd-devops-crossaccount-pipeline"
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
                # from this assumed role, delete a cloudformation stack
                cloudformation_waiters = {
                    "stack_delete_complete": [],
                }
                stack_details = delete_domain_team_role_stack(crossaccount_cloudformation, stack_team)
                cloudformation_waiters[stack_details[1]].append(stack_details[0])
                cloudformation_waiter = cloudformation.get_waiter("stack_delete_complete")
                for stack_in_deletion in cloudformation_waiters["stack_delete_complete"]:
                    cloudformation_waiter.wait(
                        StackName=stack_in_deletion, WaiterConfig={"Delay": 30, "MaxAttempts": 10}
                    )
            else:
                stack_details = delete_cicd_stack(stack, cloudformation_role)
                cloudformation_waiters[stack_details[1]].append(stack_details[0])
                cloudformation_waiter = cloudformation.get_waiter("stack_delete_complete")
                for stack_in_deletion in cloudformation_waiters["stack_delete_complete"]:
                    cloudformation_waiter.wait(
                        StackName=stack_in_deletion, WaiterConfig={"Delay": 30, "MaxAttempts": 10}
                    )

        ###### CREATE/UPDATE TEAMS AND DOMAINS ######
        # for each domain, create a CICD stack that will be used to deploy domain resources in the child account
        for domain, domain_details in domains.items():
            # create/update stacks for domains defined in git
            cloudformation_waiters = {
                "stack_create_complete": [],
                "stack_update_complete": [],
            }
            stack_details = create_domain_cicd_stack(
                domain,
                environment,
                template_cicd_domain_url,
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

            if git_platform == "CodeCommit":
                for team in domain_details["teams"]:
                    repository_name = f"{main_repository_prefix}{domain}-{team}"
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
