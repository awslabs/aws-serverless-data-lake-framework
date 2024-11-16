# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT

from aws_cdk import (
    CfnOutput,
    CfnParameter,
    RemovalPolicy,
)
from aws_cdk import aws_athena as athena
from aws_cdk import aws_iam as iam
from aws_cdk import aws_kms as kms
from aws_cdk import aws_sns as sns
from aws_cdk import aws_ssm as ssm
from constructs import Construct


class Team(Construct):
    def __init__(self, scope: Construct, id: str, **kwargs) -> None:
        super().__init__(scope, id)

        # using context values would be better(?) for CDK but we haven't decided yet what the story is around ServiceCatalog and CloudFormation modules
        # perhaps both (context values feeding into CfnParameter) would be a nice-enough solution. Not sure though. TODO
        p_pipelinereference = CfnParameter(
            self,
            "pPipelineReference",
            type="String",
            default="none",
        )
        p_pipelinereference.override_logical_id("pPipelineReference")
        p_teamname = CfnParameter(
            self,
            "pTeamName",
            description="Name of the team (all lowercase, no symbols or spaces)",
            type="String",
            allowed_pattern="[a-z0-9]{2,12}",
        )
        p_teamname.override_logical_id("pTeamName")
        p_athenabucket = CfnParameter(
            self,
            "pAthenaBucket",
            description="Athena bucket",
            type="String",
            default="{{resolve:ssm:/SDLF/S3/AthenaBucket:1}}",
        )
        p_athenabucket.override_logical_id("pAthenaBucket")

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
                        iam.ServicePrincipal("logs.amazonaws.com", region=scope.region),
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
                            "kms:CallerAccount": scope.account,
                            "kms:ViaService": f"sns.{scope.region}.amazonaws.com",
                        }
                    },
                ),
            ]
        )

        infra_kms_key = kms.Key(
            self,
            "rKMSInfraKey",
            removal_policy=RemovalPolicy.RETAIN_ON_UPDATE_OR_DELETE,
            description=f"SDLF {p_teamname.value_as_string} Infrastructure KMS Key",
            enable_key_rotation=True,
            policy=infra_kms_key_policy,
        )
        infra_kms_key.add_alias(f"alias/sdlf-{p_teamname.value_as_string}-kms-infra-key").apply_removal_policy(
            RemovalPolicy.RETAIN_ON_UPDATE_OR_DELETE
        )

        ssm.StringParameter(
            self,
            "rKMSInfraKeySsm",
            description=f"Arn of the {p_teamname.value_as_string} KMS infrastructure key",
            parameter_name=f"/SDLF/KMS/{p_teamname.value_as_string}/InfraKeyId",
            simple_name=False,  # parameter name is a token
            string_value=infra_kms_key.key_arn,
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

        ######## LAKEFORMATION PERMISSIONS #########

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
                        encryption_option="SSE_KMS", kms_key=infra_kms_key.key_arn
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
