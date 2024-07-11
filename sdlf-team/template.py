# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT

import json
import os.path

from aws_cdk import (
    ArnFormat,
    Duration,
    Stack,
    CfnParameter,
    CfnOutput,
    aws_athena as athena,
    aws_dynamodb as ddb,
    aws_emr as emr,
    aws_events as events,
    aws_events_targets as targets,
    aws_glue_alpha as glue,
    aws_iam as iam,
    aws_kms as kms,
    aws_lakeformation as lakeformation,
    aws_lambda as _lambda,
    aws_logs as logs,
    aws_scheduler as scheduler,
    aws_sns as sns,
    aws_sqs as sqs,
    aws_ssm as ssm,
)
from constructs import Construct


class SdlfTeam(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        dirname = os.path.dirname(__file__)
        run_in_vpc = False

        # using context values would be better(?) for CDK but we haven't decided yet what the story is around ServiceCatalog and CloudFormation modules
        # perhaps both (context values feeding into CfnParameter) would be a nice-enough solution. Not sure though. TODO
        p_pipelinereference = CfnParameter(
            self,
            "pPipelineReference",
            type="String",
            default="none",
        )
        p_org = CfnParameter(
            self,
            "pOrg",
            description="Name of the organization owning the datalake",
            type="String",
            default="{{resolve:ssm:/SDLF/Misc/pOrg:1}}",
        )
        p_domain = CfnParameter(
            self,
            "pDomain",
            description="Data domain name",
            type="String",
            default="{{resolve:ssm:/SDLF/Misc/pDomain:1}}",
        )
        p_environment = CfnParameter(
            self,
            "pEnvironment",
            description="Environment name",
            type="String",
            default="{{resolve:ssm:/SDLF/Misc/pEnv:1}}",
        )
        p_teamname = CfnParameter(
            self,
            "pTeamName",
            description="Name of the team (all lowercase, no symbols or spaces)",
            type="String",
            allowed_pattern="[a-z0-9]{2,12}",
        )
        p_lakeformationdataaccessrole = CfnParameter(
            self,
            "pLakeFormationDataAccessRole",
            description="Name of the team (all lowercase, no symbols or spaces)",
            type="String",
            default="{{resolve:ssm:/SDLF/IAM/LakeFormationDataAccessRoleArn:1}}",
        )
        p_artifactsbucket = CfnParameter(
            self,
            "pArtifactsBucket",
            description="The artifacts bucket used by CodeBuild and CodePipeline",
            type="String",
            default="{{resolve:ssm:/SDLF/S3/ArtifactsBucket:2}}",
        )
        p_athenabucket = CfnParameter(
            self,
            "pAthenaBucket",
            description="Athena bucket",
            type="String",
            default="{{resolve:ssm:/SDLF/S3/AthenaBucket:2}}",
        )
        p_rawbucket = CfnParameter(
            self,
            "pRawBucket",
            description="The raw bucket for the solution",
            type="String",
            default="{{resolve:ssm:/SDLF/S3/RawBucket:2}}",
        )
        p_stagebucket = CfnParameter(
            self,
            "pStageBucket",
            description="The stage bucket for the solution",
            type="String",
            default="{{resolve:ssm:/SDLF/S3/StageBucket:2}}",
        )
        p_analyticsbucket = CfnParameter(
            self,
            "pAnalyticsBucket",
            description="The analytics bucket for the solution",
            type="String",
            default="{{resolve:ssm:/SDLF/S3/AnalyticsBucket:2}}",
        )

        ######## KMS #########
        infra_kms_key_policy = iam.PolicyDocument(
            statements=[
                iam.PolicyStatement(
                    sid="Allow administration of the key",
                    effect=iam.Effect.ALLOW,
                    principals=[iam.AccountRootPrincipal()],
                    actions=["kms:*"],
                    resources=["*"],
                ),
                iam.PolicyStatement(
                    sid="Allow CloudWatch alarms access",
                    effect=iam.Effect.ALLOW,
                    principals=[
                        iam.ServicePrincipal("cloudwatch.amazonaws.com"),
                        iam.ServicePrincipal("events.amazonaws.com"),
                    ],
                    actions=["kms:Decrypt", "kms:GenerateDataKey*"],
                    resources=["*"],
                ),
                iam.PolicyStatement(
                    sid="Allow logs access",
                    effect=iam.Effect.ALLOW,
                    principals=[
                        iam.ServicePrincipal("logs.amazonaws.com", region=self.region),
                    ],
                    actions=[
                        "kms:CreateGrant",
                        "kms:Decrypt",
                        "kms:DescribeKey",
                        "kms:Encrypt",
                        "kms:GenerateDataKey*",
                        "kms:ReEncrypt*",
                    ],
                    resources=["*"],
                ),
                iam.PolicyStatement(
                    sid="Allow SNS access",
                    effect=iam.Effect.ALLOW,
                    actions=["kms:Decrypt", "kms:GenerateDataKey*"],
                    principals=[iam.AnyPrincipal()],
                    resources=["*"],
                    conditions={
                        "StringEquals": {
                            "kms:CallerAccount": self.account,
                            "kms:ViaService": f"sns.{self.region}.amazonaws.com",
                        }
                    },
                ),
            ]
        )

        infra_kms_key = kms.Key(
            self,
            "rKMSInfraKey",
            description=f"SDLF {p_teamname.value_as_string} Infrastructure KMS Key",
            policy=infra_kms_key_policy,
        )
        infra_kms_key.add_alias(f"alias/sdlf-{p_teamname.value_as_string}-kms-infra-key")

        ssm.StringParameter(
            self,
            "rKMSInfraKeySsm",
            description=f"Arn of the {p_teamname.value_as_string} KMS infrastructure key",
            parameter_name=f"/SDLF/KMS/{p_teamname.value_as_string}/InfraKeyId",
            simple_name=False,  # parameter name is a token
            string_value=infra_kms_key.key_arn,
        )

        data_kms_key_policy = iam.PolicyDocument(
            statements=[
                iam.PolicyStatement(
                    sid="Allow administration of the key",
                    effect=iam.Effect.ALLOW,
                    principals=[iam.AccountRootPrincipal()],
                    actions=["kms:*"],
                    resources=["*"],
                ),
                iam.PolicyStatement(
                    sid="Allow Lake Formation permissions",
                    effect=iam.Effect.ALLOW,
                    principals=[
                        iam.ArnPrincipal(p_lakeformationdataaccessrole.value_as_string),
                    ],
                    actions=["kms:Decrypt*", "kms:Describe*", "kms:Encrypt*", "kms:GenerateDataKey*", "kms:ReEncrypt*"],
                    resources=["*"],
                ),
            ]
        )

        data_kms_key = kms.Key(
            self,
            "rKMSDataKey",
            description=f"SDLF {p_teamname.value_as_string} Data KMS Key",
            policy=data_kms_key_policy,
        )
        data_kms_key.add_alias(f"alias/sdlf-{p_teamname.value_as_string}-kms-data-key")

        ssm.StringParameter(
            self,
            "rKMSDataKeySsm",
            description=f"Arn of the {p_teamname.value_as_string} KMS data key",
            parameter_name=f"/SDLF/KMS/{p_teamname.value_as_string}/DataKeyId",
            simple_name=False,  # parameter name is a token
            string_value=data_kms_key.key_arn,
        )

        bus = events.EventBus(self, "rEventBus", event_bus_name=f"sdlf-{p_teamname.value_as_string}")
        ssm.StringParameter(
            self,
            "rEventBusSsm",
            description=f"Name of the {p_teamname.value_as_string} event bus",
            parameter_name=f"/SDLF/EventBridge/{p_teamname.value_as_string}/EventBusName",
            simple_name=False,  # parameter name is a token
            string_value=bus.event_bus_name,
        )

        forwardeventbustrigger_role_policy = iam.Policy(
            self,
            "sdlf-cicd-events-trigger",
            statements=[iam.PolicyStatement(actions=["events:PutEvents"], resources=[bus.event_bus_arn])],
        )

        forwardeventbustrigger_role = iam.Role(
            self,
            "rForwardEventBusTriggerRole",
            assumed_by=iam.ServicePrincipal("events.amazonaws.com"),
        )
        forwardeventbustrigger_role.attach_inline_policy(forwardeventbustrigger_role_policy)

        forwardeventbus_rule = events.Rule(
            self,
            "rForwardEventBusRule",
            event_pattern=events.EventPattern(
                source=events.Match.prefix("aws."), account=[self.account], region=[self.region]
            ),
            targets=[targets.EventBus(bus, role=forwardeventbustrigger_role)],
        )

        schedule_group = scheduler.CfnScheduleGroup(
            self,
            "rScheduleGroup",
            name=f"sdlf-{p_teamname.value_as_string}",
        )
        ssm.StringParameter(
            self,
            "rScheduleGroupSsm",
            description=f"Name of the {p_teamname.value_as_string} schedule group",
            parameter_name=f"/SDLF/EventBridge/{p_teamname.value_as_string}/ScheduleGroupName",
            simple_name=False,  # parameter name is a token
            string_value=schedule_group.name,
        )

        glue.SecurityConfiguration(
            self,
            "rGlueSecurityConfiguration",
            security_configuration_name=f"sdlf-{p_teamname.value_as_string}-glue-security-config",
            cloud_watch_encryption=glue.CloudWatchEncryption(
                mode=glue.CloudWatchEncryptionMode.KMS, kms_key=infra_kms_key
            ),
            job_bookmarks_encryption=glue.JobBookmarksEncryption(
                mode=glue.JobBookmarksEncryptionMode.CLIENT_SIDE_KMS, kms_key=infra_kms_key
            ),
            s3_encryption=glue.S3Encryption(mode=glue.S3EncryptionMode.KMS, kms_key=data_kms_key),
        )
        ssm.StringParameter(
            self,
            "rGlueSecurityConfigurationSsm",
            description=f"Name of the {p_teamname.value_as_string} Glue security configuration",
            parameter_name=f"/SDLF/Glue/{p_teamname.value_as_string}/SecurityConfigurationId",
            simple_name=False,  # parameter name is a token
            string_value=f"sdlf-{p_teamname.value_as_string}-glue-security-config",  # unfortunately AWS::Glue::SecurityConfiguration doesn't provide any return value
        )

        emr_security_configuration = emr.CfnSecurityConfiguration(
            self,
            "rEMRSecurityConfiguration",
            name=f"sdlf-{p_teamname.value_as_string}-emr-security-config",
            security_configuration=json.dumps(
                {
                    "EncryptionConfiguration": {
                        "EnableInTransitEncryption": False,
                        "EnableAtRestEncryption": True,
                        "AtRestEncryptionConfiguration": {
                            "S3EncryptionConfiguration": {
                                "EncryptionMode": "SSE-KMS",
                                "AwsKmsKey": data_kms_key.key_id,
                            },
                            "LocalDiskEncryptionConfiguration": {
                                "EncryptionKeyProviderType": "AwsKms",
                                "AwsKmsKey": data_kms_key.key_id,
                                "EnableEbsEncryption": True,
                            },
                        },
                    },
                    "InstanceMetadataServiceConfiguration": {
                        "MinimumInstanceMetadataServiceVersion": 2,
                        "HttpPutResponseHopLimit": 1,
                    },
                }
            ),
        )
        #### END KMS STACK

        ######## IAM #########
        permissions_boundary = iam.ManagedPolicy(
            self,
            "rTeamIAMManagedPolicy",
            description="Team Permissions Boundary IAM policy. Add/remove permissions based on company policy and associate it to federated role",
            path=f"/sdlf/{p_teamname.value_as_string}/",  # keep this path for the team's permissions boundary policy only
            statements=[
                iam.PolicyStatement(
                    sid="AllowConsoleListBuckets",
                    actions=[
                        "s3:GetBucketLocation",
                        "s3:ListAllMyBuckets",
                    ],
                    resources=[
                        self.format_arn(
                            service="s3",
                            resource="*",
                            region="",
                            account="",
                            arn_format=ArnFormat.NO_RESOURCE_NAME,
                        )
                    ],
                ),
                iam.PolicyStatement(
                    sid="AllowTeamBucketList",
                    actions=["s3:ListBucket"],
                    resources=[
                        self.format_arn(
                            service="s3",
                            resource=p_artifactsbucket.value_as_string,
                            region="",
                            account="",
                            arn_format=ArnFormat.NO_RESOURCE_NAME,
                        ),
                        self.format_arn(
                            service="s3",
                            resource=p_rawbucket.value_as_string,
                            region="",
                            account="",
                            arn_format=ArnFormat.NO_RESOURCE_NAME,
                        ),
                        self.format_arn(
                            service="s3",
                            resource=p_stagebucket.value_as_string,
                            region="",
                            account="",
                            arn_format=ArnFormat.NO_RESOURCE_NAME,
                        ),
                        self.format_arn(
                            service="s3",
                            resource=p_analyticsbucket.value_as_string,
                            region="",
                            account="",
                            arn_format=ArnFormat.NO_RESOURCE_NAME,
                        ),
                    ],
                ),
                iam.PolicyStatement(
                    sid="AllowTeamPrefixActions",
                    actions=["s3:DeleteObject", "s3:GetObject", "s3:PutObject"],
                    resources=[
                        self.format_arn(
                            service="s3",
                            resource=f"{p_artifactsbucket.value_as_string}/{p_teamname.value_as_string}/*",
                            region="",
                            account="",
                            arn_format=ArnFormat.NO_RESOURCE_NAME,
                        ),
                        self.format_arn(
                            service="s3",
                            resource=f"{p_rawbucket.value_as_string}/{p_teamname.value_as_string}/*",
                            region="",
                            account="",
                            arn_format=ArnFormat.NO_RESOURCE_NAME,
                        ),
                        self.format_arn(
                            service="s3",
                            resource=f"{p_stagebucket.value_as_string}/{p_teamname.value_as_string}/*",
                            region="",
                            account="",
                            arn_format=ArnFormat.NO_RESOURCE_NAME,
                        ),
                        self.format_arn(
                            service="s3",
                            resource=f"{p_stagebucket.value_as_string}/pre-stage/{p_teamname.value_as_string}/*",
                            region="",
                            account="",
                            arn_format=ArnFormat.NO_RESOURCE_NAME,
                        ),
                        self.format_arn(
                            service="s3",
                            resource=f"{p_stagebucket.value_as_string}/post-stage/{p_teamname.value_as_string}/*",
                            region="",
                            account="",
                            arn_format=ArnFormat.NO_RESOURCE_NAME,
                        ),
                        self.format_arn(
                            service="s3",
                            resource=f"{p_analyticsbucket.value_as_string}/{p_teamname.value_as_string}/*",
                            region="",
                            account="",
                            arn_format=ArnFormat.NO_RESOURCE_NAME,
                        ),
                    ],
                ),
                iam.PolicyStatement(
                    sid="AllowFullCodeCommitOnTeamRepositories",
                    actions=[
                        "codecommit:AssociateApprovalRuleTemplateWithRepository",
                        "codecommit:Batch*",  # Get, Describe, ApprovalRuleTemplate"
                        "codecommit:Create*",
                        "codecommit:DeleteBranch",
                        "codecommit:DeleteFile",
                        "codecommit:Describe*",
                        "codecommit:DisassociateApprovalRuleTemplateFromRepository",
                        "codecommit:EvaluatePullRequestApprovalRules",
                        "codecommit:Get*",
                        "codecommit:List*",
                        "codecommit:Merge*",
                        "codecommit:OverridePullRequestApprovalRules",
                        "codecommit:Put*",
                        "codecommit:Post*",
                        "codecommit:TagResource",
                        "codecommit:Test*",
                        "codecommit:UntagResource",
                        "codecommit:Update*",
                        "codecommit:Git*",
                    ],
                    resources=[
                        self.format_arn(
                            service="codecommit",
                            resource=f"sdlf-{p_teamname.value_as_string}-*",
                            arn_format=ArnFormat.NO_RESOURCE_NAME,
                        ),
                    ],
                ),
                iam.PolicyStatement(
                    sid="AllowTeamKMSDataKeyUsage",
                    actions=[
                        "kms:CreateGrant",
                        "kms:Decrypt",
                        "kms:DescribeKey",
                        "kms:Encrypt",
                        "kms:GenerateDataKey*",
                        "kms:ReEncrypt*",
                    ],
                    resources=["{{resolve:ssm:/SDLF/KMS/KeyArn}}", infra_kms_key.key_arn, data_kms_key.key_arn],
                ),
                iam.PolicyStatement(
                    actions=["ssm:GetParameter", "ssm:GetParameters"],
                    resources=[
                        self.format_arn(
                            service="ssm",
                            resource="parameter",
                            arn_format=ArnFormat.SLASH_RESOURCE_NAME,
                            resource_name="/SDLF/*",
                        ),
                    ],
                ),
                iam.PolicyStatement(
                    sid="AllowOctagonDynamoAccess",
                    actions=[
                        "dynamodb:BatchGetItem",
                        "dynamodb:BatchWriteItem",
                        "dynamodb:DeleteItem",
                        "dynamodb:DescribeTable",
                        "dynamodb:GetItem",
                        "dynamodb:GetRecords",
                        "dynamodb:PutItem",
                        "dynamodb:Query",
                        "dynamodb:Scan",
                        "dynamodb:UpdateItem",
                    ],
                    resources=[
                        self.format_arn(
                            service="dynamodb",
                            resource="table",
                            arn_format=ArnFormat.SLASH_RESOURCE_NAME,
                            resource_name="octagon-*",
                        )
                    ],
                ),
                iam.PolicyStatement(
                    sid="AllowSQSManagement",
                    actions=[
                        "sqs:DeleteMessage",
                        "sqs:GetQueueAttributes",
                        "sqs:GetQueueUrl",
                        "sqs:List*",
                        "sqs:ReceiveMessage",
                        "sqs:SendMessage",
                    ],
                    resources=[
                        self.format_arn(
                            service="sqs",
                            resource=f"sdlf-{p_teamname.value_as_string}-*",
                            arn_format=ArnFormat.NO_RESOURCE_NAME,
                        ),
                    ],
                ),
                iam.PolicyStatement(
                    actions=["states:StartExecution"],
                    resources=[
                        self.format_arn(
                            service="states",
                            resource="stateMachine",
                            arn_format=ArnFormat.COLON_RESOURCE_NAME,
                            resource_name=f"sdlf-{p_teamname.value_as_string}-*",
                        ),
                    ],
                ),
                iam.PolicyStatement(
                    actions=["iam:PassRole"],
                    resources=[
                        self.format_arn(
                            service="iam",
                            resource="role",
                            region="",
                            arn_format=ArnFormat.SLASH_RESOURCE_NAME,
                            resource_name=f"sdlf-{p_teamname.value_as_string}/sdlf-*",
                        ),
                    ],
                    conditions={"StringEquals": {"iam:PassedToService": "glue.amazonaws.com"}},
                ),
                iam.PolicyStatement(
                    actions=["glue:GetSecurityConfiguration"],  # W13 exception
                    resources=["*"],
                ),
                iam.PolicyStatement(
                    actions=[
                        "glue:GetTable",
                        "glue:StartCrawler",
                        "glue:GetCrawler",
                        "glue:GetJobRun",
                        "glue:GetJobRuns",
                        "glue:StartJobRun",
                        "glue:StartDataQualityRule*",
                        "glue:GetDataQualityRule*",
                    ],
                    resources=[
                        self.format_arn(
                            service="glue",
                            resource="catalog",
                            arn_format=ArnFormat.NO_RESOURCE_NAME,
                        ),
                        self.format_arn(
                            service="glue",
                            resource="database",
                            arn_format=ArnFormat.SLASH_RESOURCE_NAME,
                            resource_name=f"{p_org.value_as_string}_{p_domain.value_as_string}_{p_environment.value_as_string}_{p_teamname.value_as_string}_*",
                        ),
                        self.format_arn(
                            service="glue",
                            resource="table",
                            arn_format=ArnFormat.SLASH_RESOURCE_NAME,
                            resource_name=f"{p_org.value_as_string}_{p_domain.value_as_string}_{p_environment.value_as_string}_{p_teamname.value_as_string}_*",
                        ),
                        self.format_arn(
                            service="glue",
                            resource="crawler",
                            arn_format=ArnFormat.SLASH_RESOURCE_NAME,
                            resource_name=f"sdlf-{p_teamname.value_as_string}-*",
                        ),
                        self.format_arn(
                            service="glue",
                            resource="job",
                            arn_format=ArnFormat.SLASH_RESOURCE_NAME,
                            resource_name=f"sdlf-{p_teamname.value_as_string}-*",
                        ),
                        self.format_arn(
                            service="glue",
                            resource="job",
                            arn_format=ArnFormat.SLASH_RESOURCE_NAME,
                            resource_name=f"{p_org.value_as_string}-{p_domain.value_as_string}-{p_environment.value_as_string}-{p_teamname.value_as_string}-*",
                        ),
                        self.format_arn(
                            service="glue",
                            resource="dataQualityRuleset",
                            arn_format=ArnFormat.SLASH_RESOURCE_NAME,
                            resource_name=f"*",  # glue:StartDataQualityRuleRecommendationRun requires dataQualityRuleset/*
                        ),
                    ],
                ),
                iam.PolicyStatement(
                    actions=["logs:CreateLogGroup"],
                    resources=[
                        self.format_arn(
                            service="logs",
                            resource="*",
                            arn_format=ArnFormat.NO_RESOURCE_NAME,
                        ),
                    ],
                ),
                iam.PolicyStatement(
                    actions=[
                        "logs:CreateLogStream",
                        "logs:DescribeLogStreams",
                        "logs:GetLogEvents",
                        "logs:PutLogEvents",
                        "logs:AssociateKmsKey",
                    ],
                    resources=[
                        self.format_arn(
                            service="logs",
                            resource="log-group",
                            arn_format=ArnFormat.COLON_RESOURCE_NAME,
                            resource_name=f"/aws/lambda/sdlf-{p_teamname.value_as_string}-*",
                        ),
                        self.format_arn(
                            service="logs",
                            resource="log-group",
                            arn_format=ArnFormat.COLON_RESOURCE_NAME,
                            resource_name=f"/aws/codebuild/sdlf-{p_teamname.value_as_string}-*",
                        ),
                        self.format_arn(
                            service="logs",
                            resource="log-group",
                            arn_format=ArnFormat.COLON_RESOURCE_NAME,
                            resource_name=f"/aws-glue/jobs/sdlf-{p_teamname.value_as_string}-*",
                        ),
                    ],
                ),
                iam.PolicyStatement(
                    sid="AllowCloudFormationReadOnlyAccess",
                    actions=[
                        "cloudformation:DescribeStacks",
                        "cloudformation:DescribeStackEvents",
                        "cloudformation:DescribeStackResource",
                        "cloudformation:DescribeStackResources",
                    ],
                    resources=[
                        self.format_arn(
                            service="cloudformation",
                            resource="stack",
                            arn_format=ArnFormat.COLON_RESOURCE_NAME,
                            resource_name=f"sdlf-{p_teamname.value_as_string}:*",
                        ),
                    ],
                ),
                iam.PolicyStatement(
                    actions=[
                        "lambda:InvokeFunction",
                    ],
                    resources=[
                        self.format_arn(
                            service="lambda",
                            resource="function",
                            arn_format=ArnFormat.COLON_RESOURCE_NAME,
                            resource_name=f"sdlf-{p_teamname.value_as_string}-*",
                        ),
                    ],
                ),
                iam.PolicyStatement(
                    actions=["events:PutTargets", "events:PutRule", "events:DescribeRule"],
                    resources=[
                        self.format_arn(
                            service="events",
                            resource="rule",
                            arn_format=ArnFormat.SLASH_RESOURCE_NAME,
                            resource_name="StepFunctions*",  # Step Functions managed rules: https://docs.aws.amazon.com/step-functions/latest/dg/service-integration-iam-templates.html#connect-iam-sync-async
                        ),
                    ],
                ),
                iam.PolicyStatement(
                    actions=[
                        "emr-serverless:CreateApplication",
                        "emr-serverless:GetApplication",
                    ],
                    resources=[
                        self.format_arn(
                            service="emr-serverless",
                            resource="/applications/*",
                            arn_format=ArnFormat.NO_RESOURCE_NAME,
                        ),
                    ],
                ),
            ],
        )
        ssm.StringParameter(
            self,
            "rTeamIAMManagedPolicySsm",
            description="The permissions boundary IAM Managed policy for the team",
            parameter_name=f"/SDLF/IAM/{p_teamname.value_as_string}/TeamPermissionsBoundary",
            simple_name=False,  # parameter name is a token
            string_value=permissions_boundary.managed_policy_arn,
        )

        datalakecrawler_role_policy = iam.Policy(
            self,
            "sdlf-glue-crawler",  # "sdlf-{p_teamname.value_as_string}-glue-crawler",
            statements=[
                iam.PolicyStatement(
                    actions=[
                        "s3:CreateBucket",
                    ],
                    resources=[
                        self.format_arn(
                            service="s3",
                            resource="aws-glue-*",
                            region="",
                            account="",
                            arn_format=ArnFormat.NO_RESOURCE_NAME,
                        ),
                    ],
                ),
                iam.PolicyStatement(
                    actions=["s3:DeleteObject", "s3:GetObject", "s3:PutObject"],
                    resources=[
                        self.format_arn(
                            service="s3",
                            resource="aws-glue-*/*",
                            region="",
                            account="",
                            arn_format=ArnFormat.NO_RESOURCE_NAME,
                        ),
                        self.format_arn(
                            service="s3",
                            resource="*/*aws-glue-*/*",
                            region="",
                            account="",
                            arn_format=ArnFormat.NO_RESOURCE_NAME,
                        ),
                    ],
                ),
                iam.PolicyStatement(
                    actions=[
                        "s3:GetObject",
                    ],
                    resources=[
                        self.format_arn(
                            service="s3",
                            resource="crawler-public*",
                            region="",
                            account="",
                            arn_format=ArnFormat.NO_RESOURCE_NAME,
                        ),
                        self.format_arn(
                            service="s3",
                            resource="aws-glue-*",
                            region="",
                            account="",
                            arn_format=ArnFormat.NO_RESOURCE_NAME,
                        ),
                    ],
                ),
                iam.PolicyStatement(
                    actions=[
                        "s3:ListObjectsV2",
                        "s3:GetObject",
                        "s3:GetObjectVersion",
                        "s3:GetBucketVersioning",
                        "s3:GetBucketAcl",
                        "s3:GetBucketLocation",
                        "s3:PutObject",
                        "s3:PutObjectVersion",
                    ],
                    resources=[
                        self.format_arn(
                            service="s3",
                            resource=f"{p_rawbucket.value_as_string}/{p_teamname.value_as_string}/*",
                            region="",
                            account="",
                            arn_format=ArnFormat.NO_RESOURCE_NAME,
                        ),
                        self.format_arn(
                            service="s3",
                            resource=f"{p_stagebucket.value_as_string}/{p_teamname.value_as_string}/*",
                            region="",
                            account="",
                            arn_format=ArnFormat.NO_RESOURCE_NAME,
                        ),
                        self.format_arn(
                            service="s3",
                            resource=f"{p_stagebucket.value_as_string}/pre-stage/{p_teamname.value_as_string}/*",
                            region="",
                            account="",
                            arn_format=ArnFormat.NO_RESOURCE_NAME,
                        ),
                        self.format_arn(
                            service="s3",
                            resource=f"{p_stagebucket.value_as_string}/post-stage/{p_teamname.value_as_string}/*",
                            region="",
                            account="",
                            arn_format=ArnFormat.NO_RESOURCE_NAME,
                        ),
                        self.format_arn(
                            service="s3",
                            resource=f"{p_analyticsbucket.value_as_string}/{p_teamname.value_as_string}/*",
                            region="",
                            account="",
                            arn_format=ArnFormat.NO_RESOURCE_NAME,
                        ),
                    ],
                ),
                iam.PolicyStatement(
                    actions=[
                        "kms:DescribeKey",
                        "kms:Encrypt",
                        "kms:Decrypt",
                        "kms:ReEncrypt*",
                        "kms:GenerateDataKey*",
                        "kms:CreateGrant",
                    ],
                    resources=[infra_kms_key.key_arn, data_kms_key.key_arn, "{{resolve:ssm:/SDLF/KMS/KeyArn}}"],
                ),
                iam.PolicyStatement(
                    actions=[
                        "lakeformation:GetDataAccess",  # W11 exception
                    ],
                    resources=["*"],
                ),
                iam.PolicyStatement(
                    actions=[
                        "logs:CreateLogGroup",
                        "logs:CreateLogStream",
                        "logs:PutLogEvents",
                        "logs:AssociateKmsKey",
                    ],
                    resources=[
                        self.format_arn(
                            service="logs",
                            resource="log-group",
                            arn_format=ArnFormat.COLON_RESOURCE_NAME,
                            resource_name=f"/aws-glue/crawlers-role/sdlf-{p_teamname.value_as_string}/*",
                        ),
                    ],
                ),
            ],
        )

        datalakecrawler_role = iam.Role(
            self,
            "rDatalakeCrawlerRole",
            path=f"/sdlf-{p_teamname.value_as_string}/",
            assumed_by=iam.ServicePrincipal("glue.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSGlueServiceRole"),
            ],
        )
        datalakecrawler_role.attach_inline_policy(datalakecrawler_role_policy)

        ssm.StringParameter(
            self,
            "rDatalakeCrawlerRoleArnSsm",
            description="The ARN of the Crawler role",
            parameter_name=f"/SDLF/IAM/{p_teamname.value_as_string}/CrawlerRoleArn",
            simple_name=False,  # parameter name is a token
            string_value=datalakecrawler_role.role_arn,
        )

        ######## SNS #########
        topic = sns.Topic(
            self, "rSNSTopic", topic_name=f"sdlf-{p_teamname.value_as_string}-notifications", master_key=infra_kms_key
        )

        sns.TopicPolicy(
            self,
            "rSNSTopicPolicy",  # TODO grant?
            policy_document=iam.PolicyDocument(
                # id=f"sdlf-{p_teamname.value_as_string}-notifications", TODO
                statements=[
                    iam.PolicyStatement(
                        effect=iam.Effect.ALLOW,
                        principals=[
                            iam.ServicePrincipal("cloudwatch.amazonaws.com"),
                            iam.ServicePrincipal("events.amazonaws.com"),
                        ],
                        actions=["sns:Publish"],
                        resources=[topic.topic_arn],
                    )
                ]
            ),
            topics=[topic],
        )

        ssm.StringParameter(
            self,
            "rSNSTopicSsm",
            description="The ARN of the team-specific SNS Topic",
            parameter_name=f"/SDLF/SNS/{p_teamname.value_as_string}/Notifications",
            simple_name=False,  # parameter name is a token
            string_value=topic.topic_arn,
        )

        datasetsdynamodb_role_policy = iam.Policy(
            self,
            "sdlf-dynamodb-lambda",  # f"sdlf-{p_teamname.value_as_string}-dynamodb-lambda",
            statements=[
                iam.PolicyStatement(
                    actions=[
                        "dynamodb:DeleteItem",
                        "dynamodb:UpdateItem",
                    ],
                    resources=[
                        self.format_arn(
                            service="dynamodb",
                            resource="table",
                            arn_format=ArnFormat.SLASH_RESOURCE_NAME,
                            resource_name=f"octagon-Pipelines-{p_environment.value_as_string}",
                        ),
                        self.format_arn(
                            service="dynamodb",
                            resource="table",
                            arn_format=ArnFormat.SLASH_RESOURCE_NAME,
                            resource_name=f"octagon-Datasets-{p_environment.value_as_string}",
                        ),
                    ],
                ),
                iam.PolicyStatement(
                    actions=[
                        "logs:CreateLogGroup",
                        "logs:DescribeLogGroups",
                        "logs:DeleteLogGroup",
                        "logs:TagResource",
                        "logs:PutRetentionPolicy",
                        "logs:DeleteRetentionPolicy",
                        "logs:DescribeLogStreams",
                        "logs:CreateLogStream",
                        "logs:DeleteLogStream",
                        "logs:PutLogEvents",
                    ],
                    resources=[
                        self.format_arn(
                            service="logs",
                            resource="log-group",
                            arn_format=ArnFormat.COLON_RESOURCE_NAME,
                            resource_name=f"/aws/lambda/sdlf-{p_teamname.value_as_string}-datasets-dynamodb",
                        ),
                        self.format_arn(
                            service="logs",
                            resource="log-group",
                            arn_format=ArnFormat.COLON_RESOURCE_NAME,
                            resource_name=f"/aws/lambda/sdlf-{p_teamname.value_as_string}-datasets-dynamodb:*",
                        ),
                    ],
                ),
                iam.PolicyStatement(
                    actions=[
                        "cloudwatch:DeleteAlarms",
                        "cloudwatch:DescribeAlarms",
                        "cloudwatch:PutMetricAlarm",
                        "cloudwatch:PutMetricData",
                        "cloudwatch:SetAlarmState",
                    ],
                    resources=[
                        self.format_arn(
                            service="cloudwatch",
                            resource="alarm",
                            arn_format=ArnFormat.COLON_RESOURCE_NAME,
                            resource_name=f"sdlf-{p_teamname.value_as_string}-*",
                        ),
                    ],
                ),
                iam.PolicyStatement(
                    actions=[
                        "ssm:GetParametersByPath",
                    ],
                    resources=[
                        self.format_arn(
                            service="ssm",
                            resource="parameter",
                            arn_format=ArnFormat.SLASH_RESOURCE_NAME,
                            resource_name=f"/SDLF/Pipelines/{p_teamname.value_as_string}",
                        ),
                        self.format_arn(
                            service="ssm",
                            resource="parameter",
                            arn_format=ArnFormat.SLASH_RESOURCE_NAME,
                            resource_name=f"/SDLF/Datasets/{p_teamname.value_as_string}",
                        ),
                    ],
                ),
            ],
        )

        datasetsdynamodb_role = iam.Role(
            self,
            "rDatasetsDynamodbLambdaRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
        )
        datasetsdynamodb_role.attach_inline_policy(datasetsdynamodb_role_policy)

        datasetsdynamodb_function = _lambda.Function(
            self,
            "rDatasetsDynamodbLambda",
            runtime=_lambda.Runtime.PYTHON_3_12,
            code=_lambda.Code.from_asset(os.path.join(dirname, "lambda/datasets-dynamodb/src")),
            handler="lambda_function.lambda_handler",
            function_name=f"sdlf-{p_teamname.value_as_string}-datasets-dynamodb",
            description=f"Creates/updates DynamoDB entries for {p_teamname.value_as_string} datasets",
            memory_size=192,
            timeout=Duration.seconds(300),
            role=datasetsdynamodb_role,
            environment={"TEAM_NAME": p_teamname.value_as_string, "ENV": p_environment.value_as_string},
            environment_encryption=infra_kms_key,
            # vpcconfig TODO
        )

        logs.LogGroup(
            self,
            "rDatasetsDynamodbLambdaLogGroup",
            log_group_name=f"/aws/lambda/{datasetsdynamodb_function.function_name}",
            retention=logs.RetentionDays.ONE_MONTH,
            #            retention=Duration.days(p_cloudwatchlogsretentionindays.value_as_number),
            encryption_key=infra_kms_key,
        )

        datasetsdynamodb_events_rule = events.Rule(
            self,
            "rDatasetsDynamodbTriggerEventRule",
            description="Run Datasets DynamoDB update",
            event_pattern=events.EventPattern(
                source=["aws.cloudformation"],
                detail_type=["CloudFormation Stack Status Change"],
                resources=events.Match.prefix(
                    self.format_arn(
                        service="cloudformation",
                        resource="stack",
                        arn_format=ArnFormat.SLASH_RESOURCE_NAME,
                        resource_name=f"sdlf-{p_teamname.value_as_string}-datasets-{p_environment.value_as_string}",
                    )
                ),
                detail={
                    "stack-id": [
                        {
                            "prefix": self.format_arn(
                                service="cloudformation",
                                resource="stack",
                                arn_format=ArnFormat.SLASH_RESOURCE_NAME,
                                resource_name=f"sdlf-{p_teamname.value_as_string}-datasets-{p_environment.value_as_string}",
                            )
                        }
                    ],
                    "status-details": {"status": ["CREATE_COMPLETE", "UPDATE_COMPLETE"]},
                },
            ),
            targets=[
                targets.LambdaFunction(
                    datasetsdynamodb_function,
                )  # AWS::Lambda::Permission is added automatically
            ],
        )

        pipelinesdynamodb_role_policy = iam.Policy(
            self,
            "sdlf-pipelinesdynamodb-lambda",  # f"sdlf-{p_teamname.value_as_string}-pipelinesdynamodb-lambda", TODO merge in a single policy
            statements=[
                iam.PolicyStatement(
                    actions=[
                        "dynamodb:DeleteItem",
                        "dynamodb:UpdateItem",
                    ],
                    resources=[
                        self.format_arn(
                            service="dynamodb",
                            resource="table",
                            arn_format=ArnFormat.SLASH_RESOURCE_NAME,
                            resource_name=f"octagon-Pipelines-{p_environment.value_as_string}",
                        ),
                        self.format_arn(
                            service="dynamodb",
                            resource="table",
                            arn_format=ArnFormat.SLASH_RESOURCE_NAME,
                            resource_name=f"octagon-Datasets-{p_environment.value_as_string}",
                        ),
                    ],
                ),
                iam.PolicyStatement(
                    actions=[
                        "logs:CreateLogGroup",
                        "logs:DescribeLogGroups",
                        "logs:DeleteLogGroup",
                        "logs:TagResource",
                        "logs:PutRetentionPolicy",
                        "logs:DeleteRetentionPolicy",
                        "logs:DescribeLogStreams",
                        "logs:CreateLogStream",
                        "logs:DeleteLogStream",
                        "logs:PutLogEvents",
                    ],
                    resources=[
                        self.format_arn(
                            service="logs",
                            resource="log-group",
                            arn_format=ArnFormat.COLON_RESOURCE_NAME,
                            resource_name=f"/aws/lambda/sdlf-{p_teamname.value_as_string}-pipelines-dynamodb",
                        ),
                        self.format_arn(
                            service="logs",
                            resource="log-group",
                            arn_format=ArnFormat.COLON_RESOURCE_NAME,
                            resource_name=f"/aws/lambda/sdlf-{p_teamname.value_as_string}-pipelines-dynamodb:*",
                        ),
                    ],
                ),
                iam.PolicyStatement(
                    actions=[
                        "cloudwatch:DeleteAlarms",
                        "cloudwatch:DescribeAlarms",
                        "cloudwatch:PutMetricAlarm",
                        "cloudwatch:PutMetricData",
                        "cloudwatch:SetAlarmState",
                    ],
                    resources=[
                        self.format_arn(
                            service="cloudwatch",
                            resource="alarm",
                            arn_format=ArnFormat.COLON_RESOURCE_NAME,
                            resource_name=f"sdlf-{p_teamname.value_as_string}-*",
                        ),
                    ],
                ),
                iam.PolicyStatement(
                    actions=[
                        "ssm:GetParametersByPath",
                    ],
                    resources=[
                        self.format_arn(
                            service="ssm",
                            resource="parameter",
                            arn_format=ArnFormat.SLASH_RESOURCE_NAME,
                            resource_name=f"/SDLF/Pipelines/{p_teamname.value_as_string}",
                        ),
                        self.format_arn(
                            service="ssm",
                            resource="parameter",
                            arn_format=ArnFormat.SLASH_RESOURCE_NAME,
                            resource_name=f"/SDLF/Datasets/{p_teamname.value_as_string}",
                        ),
                    ],
                ),
            ],
        )

        pipelinesdynamodb_role = iam.Role(
            self,
            "rPipelinesDynamodbLambdaRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
        )
        pipelinesdynamodb_role.attach_inline_policy(pipelinesdynamodb_role_policy)

        pipelinesdynamodb_function = _lambda.Function(
            self,
            "rPipelinesDynamodbLambda",
            runtime=_lambda.Runtime.PYTHON_3_12,
            code=_lambda.Code.from_asset(os.path.join(dirname, "lambda/pipelines-dynamodb/src")),
            handler="lambda_function.lambda_handler",
            function_name=f"sdlf-{p_teamname.value_as_string}-pipelines-dynamodb",
            description=f"Creates/updates DynamoDB entries for {p_teamname.value_as_string} pipelines",
            memory_size=192,
            timeout=Duration.seconds(300),
            role=pipelinesdynamodb_role,
            environment={"TEAM_NAME": p_teamname.value_as_string, "ENV": p_environment.value_as_string},
            environment_encryption=infra_kms_key,
            # vpcconfig TODO
        )

        logs.LogGroup(
            self,
            "rPipelinesDynamodbLambdaLogGroup",
            log_group_name=f"/aws/lambda/{pipelinesdynamodb_function.function_name}",
            retention=logs.RetentionDays.ONE_MONTH,
            #            retention=Duration.days(p_cloudwatchlogsretentionindays.value_as_number),
            encryption_key=infra_kms_key,
        )

        pipelinesdynamodb_events_rule = events.Rule(
            self,
            "rPipelinesDynamodbTriggerEventRule",
            description="Run Pipelines DynamoDB update",
            event_pattern=events.EventPattern(
                source=["aws.cloudformation"],
                detail_type=["CloudFormation Stack Status Change"],
                resources=events.Match.prefix(
                    self.format_arn(
                        service="cloudformation",
                        resource="stack",
                        arn_format=ArnFormat.SLASH_RESOURCE_NAME,
                        resource_name=f"sdlf-{p_teamname.value_as_string}-pipelines-{p_environment.value_as_string}",
                    )
                ),
                detail={
                    "stack-id": [
                        {
                            "prefix": self.format_arn(
                                service="cloudformation",
                                resource="stack",
                                arn_format=ArnFormat.SLASH_RESOURCE_NAME,
                                resource_name=f"sdlf-{p_teamname.value_as_string}-pipelines-{p_environment.value_as_string}",
                            )
                        }
                    ],
                    "status-details": {"status": ["CREATE_COMPLETE", "UPDATE_COMPLETE"]},
                },
            ),
            targets=[
                targets.LambdaFunction(
                    pipelinesdynamodb_function,
                )  # AWS::Lambda::Permission is added automatically
            ],
        )

        ######## LAKEFORMATION PERMISSIONS #########
        raw_crawler_lakeformation_permissions = lakeformation.CfnPermissions(
            self,
            "rCentralTeamLakeFormationPermissions",
            data_lake_principal=lakeformation.CfnPermissions.DataLakePrincipalProperty(
                data_lake_principal_identifier=datalakecrawler_role.role_arn
            ),
            resource=lakeformation.CfnPermissions.ResourceProperty(
                data_location_resource=lakeformation.CfnPermissions.DataLocationResourceProperty(
                    s3_resource=self.format_arn(
                        service="s3",
                        resource=f"{p_rawbucket.value_as_string}/{p_teamname.value_as_string}/",
                        region="",
                        account="",
                        arn_format=ArnFormat.NO_RESOURCE_NAME,
                    )
                ),
            ),
            permissions=["DATA_LOCATION_ACCESS"],
        )

        stagepre_crawler_lakeformation_permissions = lakeformation.CfnPermissions(
            self,
            "rStagePreTeamLakeFormationPermissions",
            data_lake_principal=lakeformation.CfnPermissions.DataLakePrincipalProperty(
                data_lake_principal_identifier=datalakecrawler_role.role_arn
            ),
            resource=lakeformation.CfnPermissions.ResourceProperty(
                data_location_resource=lakeformation.CfnPermissions.DataLocationResourceProperty(
                    s3_resource=self.format_arn(
                        service="s3",
                        resource=f"{p_stagebucket.value_as_string}/pre-stage/{p_teamname.value_as_string}/",
                        region="",
                        account="",
                        arn_format=ArnFormat.NO_RESOURCE_NAME,
                    )
                ),
            ),
            permissions=["DATA_LOCATION_ACCESS"],
        )

        stagepost_crawler_lakeformation_permissions = lakeformation.CfnPermissions(
            self,
            "rStagePostTeamLakeFormationPermissions",
            data_lake_principal=lakeformation.CfnPermissions.DataLakePrincipalProperty(
                data_lake_principal_identifier=datalakecrawler_role.role_arn
            ),
            resource=lakeformation.CfnPermissions.ResourceProperty(
                data_location_resource=lakeformation.CfnPermissions.DataLocationResourceProperty(
                    s3_resource=self.format_arn(
                        service="s3",
                        resource=f"{p_stagebucket.value_as_string}/post-stage/{p_teamname.value_as_string}/",
                        region="",
                        account="",
                        arn_format=ArnFormat.NO_RESOURCE_NAME,
                    )
                ),
            ),
            permissions=["DATA_LOCATION_ACCESS"],
        )

        analytics_crawler_lakeformation_permissions = lakeformation.CfnPermissions(
            self,
            "rAnalyticsTeamLakeFormationPermissions",
            data_lake_principal=lakeformation.CfnPermissions.DataLakePrincipalProperty(
                data_lake_principal_identifier=datalakecrawler_role.role_arn
            ),
            resource=lakeformation.CfnPermissions.ResourceProperty(
                data_location_resource=lakeformation.CfnPermissions.DataLocationResourceProperty(
                    s3_resource=self.format_arn(
                        service="s3",
                        resource=f"{p_analyticsbucket.value_as_string}/{p_teamname.value_as_string}/",
                        region="",
                        account="",
                        arn_format=ArnFormat.NO_RESOURCE_NAME,
                    )
                ),
            ),
            permissions=["DATA_LOCATION_ACCESS"],
        )

        tag = lakeformation.CfnTag(
            self,
            "rTeamLakeFormationTag",
            catalog_id=self.account,
            # sdlf:team as key and team names as values would be best but impossible here
            tag_key=f"sdlf:team:{p_teamname.value_as_string}",
            tag_values=[p_teamname.value_as_string],
        )

        tag_lakeformation_permissions = lakeformation.CfnPrincipalPermissions(
            self,
            "rTeamLakeFormationTagPermissions",  # allows associating this lf-tag to datasets in sdlf-dataset
            permissions=["ASSOCIATE"],
            permissions_with_grant_option=[],
            principal=lakeformation.CfnPrincipalPermissions.DataLakePrincipalProperty(
                data_lake_principal_identifier=self.format_arn(
                    service="iam",
                    resource="role",
                    region="",
                    arn_format=ArnFormat.SLASH_RESOURCE_NAME,
                    resource_name=f"sdlf-cicd-team-{p_teamname.value_as_string}",
                ),
            ),
            resource=lakeformation.CfnPrincipalPermissions.ResourceProperty(
                lf_tag=lakeformation.CfnPrincipalPermissions.LFTagKeyResourceProperty(
                    catalog_id=self.account, tag_key=tag.tag_key, tag_values=[p_teamname.value_as_string]
                ),
            ),
        )

        tag_tables_lakeformation_permissions = lakeformation.CfnPrincipalPermissions(
            self,
            "rTeamLakeFormationTagTablesPermissions",  # allows sdlf pipelines to grant permissions on tables associated with this lf-tag
            permissions=["ALL"],
            permissions_with_grant_option=["ALL"],
            principal=lakeformation.CfnPrincipalPermissions.DataLakePrincipalProperty(
                data_lake_principal_identifier=self.format_arn(
                    service="iam",
                    resource="role",
                    region="",
                    arn_format=ArnFormat.SLASH_RESOURCE_NAME,
                    resource_name=f"sdlf-cicd-team-{p_teamname.value_as_string}",
                ),
            ),
            resource=lakeformation.CfnPrincipalPermissions.ResourceProperty(
                lf_tag_policy=lakeformation.CfnPrincipalPermissions.LFTagPolicyResourceProperty(
                    catalog_id=self.account,
                    expression=[
                        lakeformation.CfnPrincipalPermissions.LFTagProperty(
                            tag_key=tag.tag_key, tag_values=[p_teamname.value_as_string]
                        )
                    ],
                    resource_type="TABLE",
                ),
            ),
        )

        athena_workgroup = athena.CfnWorkGroup(
            self,
            "rAthenaWorkgroup",
            name=f"sdlf-{p_teamname.value_as_string}",
            description=f"Athena workgroup for team {p_teamname.value_as_string}",
            state="ENABLED",
            work_group_configuration=athena.CfnWorkGroup.WorkGroupConfigurationProperty(
                enforce_work_group_configuration=True,
                engine_version=athena.CfnWorkGroup.EngineVersionProperty(
                    effective_engine_version="Athena engine version 3",
                    selected_engine_version="Athena engine version 3",
                ),
                publish_cloud_watch_metrics_enabled=True,
                result_configuration=athena.CfnWorkGroup.ResultConfigurationProperty(
                    encryption_configuration=athena.CfnWorkGroup.EncryptionConfigurationProperty(
                        encryption_option="SSE_KMS", kms_key=data_kms_key.key_arn
                    ),
                    output_location=f"s3://{p_athenabucket.value_as_string}/{p_teamname.value_as_string}/",
                ),
            ),
        )
        ssm.StringParameter(
            self,
            "rAthenaWorkgroupSsm",
            description="The name of the Athena workgroup",
            parameter_name=f"/SDLF/Athena/{p_teamname.value_as_string}/WorkgroupName",
            simple_name=False,  # parameter name is a token
            string_value=athena_workgroup.name,
        )

        # CloudFormation Outputs TODO
        CfnOutput(
            self,
            "oPipelineReference",
            description="CodePipeline reference this stack has been deployed with",
            value=p_pipelinereference.value_as_string,
        )
