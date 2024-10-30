# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT

import json

from aws_cdk import (
    ArnFormat,
    CfnCondition,
    CfnOutput,
    CfnParameter,
    Fn,
    RemovalPolicy,
)
from aws_cdk import aws_dynamodb as ddb
from aws_cdk import aws_emr as emr
from aws_cdk import aws_events as events
from aws_cdk import aws_events_targets as targets
from aws_cdk import aws_glue as glue
from aws_cdk import aws_glue_alpha as glue_a
from aws_cdk import aws_iam as iam
from aws_cdk import aws_kms as kms
from aws_cdk import aws_lakeformation as lakeformation
from aws_cdk import aws_scheduler as scheduler
from aws_cdk import aws_ssm as ssm
from constructs import Construct


class Dataset(Construct):
    external_interface = {}

    def __init__(
        self,
        scope: Construct,
        id: str,
        dataset: str,
        s3_prefix: str,
        org: str = None,
        data_domain: str = None,
        raw_bucket: str = None,
        stage_bucket: str = None,
        analytics_bucket: str = None,
        artifacts_bucket: str = None,
        lakeformation_dataaccess_role: str = None,
        **kwargs,
    ) -> None:
        super().__init__(scope, id)

        # if arguments are passed to the constructor, their values are fed to CfnParameter() below as default
        # if arguments aren't specified, standard SDLF SSM parameters are checked instead
        # the jury is still out on the usage of CfnParameter(),
        # and there is still work to get the latest SSM parameter values as well as using a prefix to allow multiple deployments TODO
        raw_bucket = raw_bucket or "{{resolve:ssm:/sdlf/storage/rRawBucket:1}}"
        stage_bucket = stage_bucket or "{{resolve:ssm:/sdlf/storage/rStageBucket:1}}"
        analytics_bucket = analytics_bucket or "{{resolve:ssm:/sdlf/storage/rAnalyticsBucket:1}}"
        artifacts_bucket = artifacts_bucket or "{{resolve:ssm:/sdlf/storage/rArtifactsBucket:1}}"
        lakeformation_dataaccess_role = (
            lakeformation_dataaccess_role or "{{resolve:ssm:/sdlf/storage/rLakeFormationDataAccessRoleArn:1}}"
        )
        org = org or "{{resolve:ssm:/sdlf/storage/rOrganization:1}}"
        data_domain = data_domain or "{{resolve:ssm:/sdlf/storage/rDomain:1}}"

        p_pipelinereference = CfnParameter(
            self,
            "pPipelineReference",
            type="String",
            default="none",
        )
        p_pipelinereference.override_logical_id("pPipelineReference")
        p_org = CfnParameter(
            self,
            "pOrg",
            description="Name of the organization owning the datalake",
            type="String",
            default=org,
        )
        p_org.override_logical_id("pOrg")
        p_domain = CfnParameter(
            self,
            "pDomain",
            description="Data domain name",
            type="String",
            default=data_domain,
        )
        p_domain.override_logical_id("pDomain")
        p_rawbucket = CfnParameter(
            self,
            "pRawBucket",
            description="The raw bucket for the solution",
            type="String",
            default=raw_bucket,
        )
        p_rawbucket.override_logical_id("pRawBucket")
        p_stagebucket = CfnParameter(
            self,
            "pStageBucket",
            description="The stage bucket for the solution",
            type="String",
            default=stage_bucket,
        )
        p_stagebucket.override_logical_id("pStageBucket")
        p_analyticsbucket = CfnParameter(
            self,
            "pAnalyticsBucket",
            description="The analytics bucket for the solution",
            type="String",
            default=analytics_bucket,
        )
        p_analyticsbucket.override_logical_id("pAnalyticsBucket")
        p_artifactsbucket = CfnParameter(
            self,
            "pArtifactsBucket",
            description="The artifacts bucket  used by CodeBuild and CodePipeline",
            type="String",
            default=artifacts_bucket,
        )
        p_artifactsbucket.override_logical_id("pArtifactsBucket")
        p_lakeformationdataaccessrole = CfnParameter(
            self,
            "pLakeFormationDataAccessRole",
            type="String",
            default=lakeformation_dataaccess_role,
        )
        p_lakeformationdataaccessrole.override_logical_id("pLakeFormationDataAccessRole")
        p_datasetname = CfnParameter(
            self,
            "pDatasetName",
            description="The name of the dataset (all lowercase, no symbols or spaces)",
            type="String",
            allowed_pattern="[a-z0-9]{2,14}",
            default=dataset,
        )
        p_datasetname.override_logical_id("pDatasetName")
        p_s3prefix = CfnParameter(
            self,
            "pS3Prefix",
            description="S3 prefix or full bucket if empty/not provided",
            type="String",
            allowed_pattern="[a-z0-9]*",
            default=s3_prefix,
        )
        p_s3prefix.override_logical_id("pS3Prefix")
        p_cicdrole = CfnParameter(
            self,
            "pCicdRole",
            description="Name of the IAM role used to deploy SDLF constructs",
            type="String",
            default="",
        )
        p_cicdrole.override_logical_id("pCicdRole")

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

        infra_kms_key_resource_name = "rKMSInfraKey"
        infra_kms_key = kms.Key(
            self,
            infra_kms_key_resource_name,
            removal_policy=RemovalPolicy.RETAIN_ON_UPDATE_OR_DELETE,
            description=f"SDLF {p_datasetname.value_as_string} Infrastructure KMS Key",
            enable_key_rotation=True,
            policy=infra_kms_key_policy,
        )
        infra_kms_key.add_alias(f"alias/sdlf-{p_datasetname.value_as_string}-kms-infra-key").apply_removal_policy(
            RemovalPolicy.RETAIN_ON_UPDATE_OR_DELETE
        )

        self._external_interface(
            infra_kms_key_resource_name,
            f"Arn of the {p_datasetname.value_as_string} KMS infrastructure key",
            infra_kms_key.key_arn,
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

        s3_prefix_condition = CfnCondition(
            self, "IsS3Prefix", expression=Fn.condition_not(Fn.condition_equals(p_s3prefix.value_as_string, ""))
        )

        data_kms_key_resource_name = "rKMSDataKey"
        data_kms_key = kms.Key(
            self,
            data_kms_key_resource_name,
            removal_policy=RemovalPolicy.RETAIN_ON_UPDATE_OR_DELETE,
            description=f"SDLF {p_datasetname.value_as_string} Data KMS Key",
            enable_key_rotation=True,
            policy=data_kms_key_policy,
        )
        data_kms_key.node.default_child.cfn_options.condition = s3_prefix_condition
        data_kms_key_alias = data_kms_key.add_alias(f"alias/sdlf-{p_datasetname.value_as_string}-kms-data-key")
        data_kms_key_alias.apply_removal_policy(RemovalPolicy.RETAIN_ON_UPDATE_OR_DELETE)
        data_kms_key_alias.node.default_child.cfn_options.condition = s3_prefix_condition

        # self._external_interface(
        #     data_kms_key_resource_name,
        #     f"Arn of the {p_datasetname.value_as_string} KMS data key",
        #     data_kms_key.key_arn,
        # ) TODO
        ssm.StringParameter(
            self,
            f"{data_kms_key_resource_name}Ssm",
            description=f"Arn of the {p_datasetname.value_as_string} KMS data key",
            parameter_name=f"/sdlf/dataset/{data_kms_key_resource_name}",
            simple_name=False,  # parameter name is a token
            string_value=data_kms_key.key_arn,
        ).node.default_child.cfn_options.condition = s3_prefix_condition

        ######## GLUE #########
        glue_security_configuration_resource_name = "rGlueSecurityConfiguration"
        self.glue_security_configuration = glue_a.SecurityConfiguration(
            self,
            glue_security_configuration_resource_name,
            security_configuration_name=f"sdlf-{p_datasetname.value_as_string}-glue-security-config",
            cloud_watch_encryption=glue_a.CloudWatchEncryption(
                mode=glue_a.CloudWatchEncryptionMode.KMS, kms_key=infra_kms_key
            ),
            job_bookmarks_encryption=glue_a.JobBookmarksEncryption(
                mode=glue_a.JobBookmarksEncryptionMode.CLIENT_SIDE_KMS, kms_key=infra_kms_key
            ),
            s3_encryption=glue_a.S3Encryption(
                mode=glue_a.S3EncryptionMode.KMS, kms_key=data_kms_key
            ),  # TODO handle with if
        )
        self._external_interface(
            glue_security_configuration_resource_name,
            f"Name of the {p_datasetname.value_as_string} Glue security configuration",
            self.glue_security_configuration.security_configuration_name,
        )

        emr_security_configuration_resource_name = "rEMRSecurityConfiguration"
        emr_security_configuration = emr.CfnSecurityConfiguration(
            self,
            emr_security_configuration_resource_name,
            name=f"sdlf-{p_datasetname.value_as_string}-emr-security-config",
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
        self._external_interface(
            emr_security_configuration_resource_name,
            f"Name of the {p_datasetname.value_as_string} EMR security configuration",
            emr_security_configuration.name,
        )

        datalakecrawler_role_policy = iam.Policy(
            self,
            "sdlf-{p_datasetname.value_as_string}-glue-crawler",
            statements=[
                iam.PolicyStatement(
                    actions=[
                        "s3:CreateBucket",
                    ],
                    resources=[
                        scope.format_arn(
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
                        scope.format_arn(
                            service="s3",
                            resource="aws-glue-*/*",
                            region="",
                            account="",
                            arn_format=ArnFormat.NO_RESOURCE_NAME,
                        ),
                        scope.format_arn(
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
                        scope.format_arn(
                            service="s3",
                            resource="crawler-public*",
                            region="",
                            account="",
                            arn_format=ArnFormat.NO_RESOURCE_NAME,
                        ),
                        scope.format_arn(
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
                        scope.format_arn(
                            service="s3",
                            resource=f"{p_rawbucket.value_as_string}/{p_s3prefix.value_as_string}/*",
                            region="",
                            account="",
                            arn_format=ArnFormat.NO_RESOURCE_NAME,
                        ),
                        scope.format_arn(
                            service="s3",
                            resource=f"{p_stagebucket.value_as_string}/{p_s3prefix.value_as_string}/*",
                            region="",
                            account="",
                            arn_format=ArnFormat.NO_RESOURCE_NAME,
                        ),
                        scope.format_arn(
                            service="s3",
                            resource=f"{p_stagebucket.value_as_string}/{p_s3prefix.value_as_string}/*",
                            region="",
                            account="",
                            arn_format=ArnFormat.NO_RESOURCE_NAME,
                        ),
                        scope.format_arn(
                            service="s3",
                            resource=f"{p_analyticsbucket.value_as_string}/{p_s3prefix.value_as_string}/*",
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
                    resources=[infra_kms_key.key_arn, data_kms_key.key_arn, "{{resolve:ssm:/sdlf/storage/rKMSKey}}"],
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
                        scope.format_arn(
                            service="logs",
                            resource="log-group",
                            arn_format=ArnFormat.COLON_RESOURCE_NAME,
                            resource_name=f"/aws-glue/crawlers-role/sdlf-{p_datasetname.value_as_string}/*",
                        ),
                    ],
                ),
            ],
        )

        datalakecrawler_role_resource_name = "rDatalakeCrawlerRole"
        self.datalakecrawler_role = iam.Role(
            self,
            datalakecrawler_role_resource_name,
            path=f"/sdlf-{p_datasetname.value_as_string}/",
            assumed_by=iam.ServicePrincipal("glue.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSGlueServiceRole"),
            ],
        )
        self.datalakecrawler_role.attach_inline_policy(datalakecrawler_role_policy)
        self._external_interface(
            datalakecrawler_role_resource_name,
            "The ARN of the Crawler role",
            self.datalakecrawler_role.role_arn,
        )

        lf_tag = lakeformation.CfnTag(
            self,
            "rLakeFormationTag",
            catalog_id=scope.account,
            tag_key="sdlf:dataset",
            tag_values=[p_datasetname.value_as_string],
        )

        lf_tag_pair_property = lakeformation.CfnTagAssociation.LFTagPairProperty(
            catalog_id=scope.account,
            tag_key=lf_tag.tag_key,
            tag_values=[p_datasetname.value_as_string],
        )

        self.data_catalog(
            scope,
            p_org.value_as_string,
            p_domain.value_as_string,
            p_datasetname.value_as_string,
            "raw",
            p_rawbucket.value_as_string,
            p_s3prefix.value_as_string,
            lf_tag_pair_property,
        )

        self.data_catalog(
            scope,
            p_org.value_as_string,
            p_domain.value_as_string,
            p_datasetname.value_as_string,
            "stage",
            p_stagebucket.value_as_string,
            p_s3prefix.value_as_string,
            lf_tag_pair_property,
        )

        self.data_catalog(
            scope,
            p_org.value_as_string,
            p_domain.value_as_string,
            p_datasetname.value_as_string,
            "analytics",
            p_analyticsbucket.value_as_string,
            p_s3prefix.value_as_string,
            lf_tag_pair_property,
        )

        # TODO
        # tag_lakeformation_permissions = lakeformation.CfnPrincipalPermissions(
        #     self,
        #     "rTeamLakeFormationTagPermissions",  # allows associating this lf-tag to datasets in sdlf-dataset
        #     permissions=["ASSOCIATE"],
        #     permissions_with_grant_option=[],
        #     principal=lakeformation.CfnPrincipalPermissions.DataLakePrincipalProperty(
        #         data_lake_principal_identifier=scope.format_arn(
        #             service="iam",
        #             resource="role",
        #             region="",
        #             arn_format=ArnFormat.SLASH_RESOURCE_NAME,
        #             resource_name=f"sdlf-cicd-team-{p_teamname.value_as_string}",
        #         ),
        #     ),
        #     resource=lakeformation.CfnPrincipalPermissions.ResourceProperty(
        #         lf_tag=lakeformation.CfnPrincipalPermissions.LFTagKeyResourceProperty(
        #             catalog_id=scope.account, tag_key=tag.tag_key, tag_values=[p_teamname.value_as_string]
        #         ),
        #     ),
        # )

        # TODO
        # tag_tables_lakeformation_permissions = lakeformation.CfnPrincipalPermissions(
        #     self,
        #     "rTeamLakeFormationTagTablesPermissions",  # allows sdlf pipelines to grant permissions on tables associated with this lf-tag
        #     permissions=["ALL"],
        #     permissions_with_grant_option=["ALL"],
        #     principal=lakeformation.CfnPrincipalPermissions.DataLakePrincipalProperty(
        #         data_lake_principal_identifier=scope.format_arn(
        #             service="iam",
        #             resource="role",
        #             region="",
        #             arn_format=ArnFormat.SLASH_RESOURCE_NAME,
        #             resource_name=f"sdlf-cicd-team-{p_teamname.value_as_string}",
        #         ),
        #     ),
        #     resource=lakeformation.CfnPrincipalPermissions.ResourceProperty(
        #         lf_tag_policy=lakeformation.CfnPrincipalPermissions.LFTagPolicyResourceProperty(
        #             catalog_id=scope.account,
        #             expression=[
        #                 lakeformation.CfnPrincipalPermissions.LFTagProperty(
        #                     tag_key=tag.tag_key, tag_values=[p_teamname.value_as_string]
        #                 )
        #             ],
        #             resource_type="TABLE",
        #         ),
        #     ),
        # )

        ######## EVENTBRIDGE #########
        bus_resource_name = "rEventBus"
        bus = events.EventBus(self, bus_resource_name, event_bus_name=f"sdlf-{p_datasetname.value_as_string}")
        self._external_interface(
            bus_resource_name,
            f"Name of the {p_datasetname.value_as_string} event bus",
            bus.event_bus_name,
        )

        schedule_group_resource_name = "rScheduleGroup"
        schedule_group = scheduler.CfnScheduleGroup(
            self,
            schedule_group_resource_name,
            name=f"sdlf-{p_datasetname.value_as_string}",
        )
        self._external_interface(
            schedule_group_resource_name,
            f"Name of the {p_datasetname.value_as_string} schedule group",
            schedule_group.name,
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

        events.Rule(
            self,
            "rForwardEventBusRule",
            event_pattern=events.EventPattern(
                source=events.Match.prefix("aws."), account=[scope.account], region=[scope.region]
            ),
            targets=[targets.EventBus(bus, role=forwardeventbustrigger_role)],
        )

        ######## IAM #########
        permissions_boundary_resource_name = "rIamManagedPolicy"
        permissions_boundary = iam.ManagedPolicy(
            self,
            permissions_boundary_resource_name,
            description="Team Permissions Boundary IAM policy. Add/remove permissions based on company policy and associate it to federated role",
            path=f"/sdlf/{p_datasetname.value_as_string}/",  # keep this path for the dataset's permissions boundary policy only
            statements=[
                iam.PolicyStatement(
                    sid="AllowConsoleListBuckets",
                    actions=[
                        "s3:GetBucketLocation",
                        "s3:ListAllMyBuckets",
                    ],
                    resources=[
                        scope.format_arn(
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
                        scope.format_arn(
                            service="s3",
                            resource=p_artifactsbucket.value_as_string,
                            region="",
                            account="",
                            arn_format=ArnFormat.NO_RESOURCE_NAME,
                        ),
                        scope.format_arn(
                            service="s3",
                            resource=p_rawbucket.value_as_string,
                            region="",
                            account="",
                            arn_format=ArnFormat.NO_RESOURCE_NAME,
                        ),
                        scope.format_arn(
                            service="s3",
                            resource=p_stagebucket.value_as_string,
                            region="",
                            account="",
                            arn_format=ArnFormat.NO_RESOURCE_NAME,
                        ),
                        scope.format_arn(
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
                        scope.format_arn(
                            service="s3",
                            resource=f"{p_artifactsbucket.value_as_string}/{p_s3prefix.value_as_string}/*",
                            region="",
                            account="",
                            arn_format=ArnFormat.NO_RESOURCE_NAME,
                        ),
                        scope.format_arn(
                            service="s3",
                            resource=f"{p_rawbucket.value_as_string}/{p_s3prefix.value_as_string}/*",
                            region="",
                            account="",
                            arn_format=ArnFormat.NO_RESOURCE_NAME,
                        ),
                        scope.format_arn(
                            service="s3",
                            resource=f"{p_stagebucket.value_as_string}/{p_s3prefix.value_as_string}/*",
                            region="",
                            account="",
                            arn_format=ArnFormat.NO_RESOURCE_NAME,
                        ),
                        scope.format_arn(
                            service="s3",
                            resource=f"{p_stagebucket.value_as_string}/{p_s3prefix.value_as_string}/*",
                            region="",
                            account="",
                            arn_format=ArnFormat.NO_RESOURCE_NAME,
                        ),
                        scope.format_arn(
                            service="s3",
                            resource=f"{p_analyticsbucket.value_as_string}/{p_s3prefix.value_as_string}/*",
                            region="",
                            account="",
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
                    resources=["{{resolve:ssm:/sdlf/storage/rKMSKey}}", infra_kms_key.key_arn, data_kms_key.key_arn],
                ),
                iam.PolicyStatement(
                    actions=["ssm:GetParameter", "ssm:GetParameters"],
                    resources=[
                        scope.format_arn(
                            service="ssm",
                            resource="parameter",
                            arn_format=ArnFormat.SLASH_RESOURCE_NAME,
                            resource_name="/sdlf/*",
                        ),
                    ],
                ),
                iam.PolicyStatement(
                    sid="AllowDynamoAccess",
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
                        scope.format_arn(
                            service="dynamodb",
                            resource="table",
                            arn_format=ArnFormat.SLASH_RESOURCE_NAME,
                            resource_name="sdlf-*",
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
                        scope.format_arn(
                            service="sqs",
                            resource=f"sdlf-{p_datasetname.value_as_string}-*",
                            arn_format=ArnFormat.NO_RESOURCE_NAME,
                        ),
                    ],
                ),
                iam.PolicyStatement(
                    actions=["states:StartExecution"],
                    resources=[
                        scope.format_arn(
                            service="states",
                            resource="stateMachine",
                            arn_format=ArnFormat.COLON_RESOURCE_NAME,
                            resource_name=f"sdlf-{p_datasetname.value_as_string}-*",
                        ),
                    ],
                ),
                iam.PolicyStatement(
                    actions=["iam:PassRole"],
                    resources=[
                        scope.format_arn(
                            service="iam",
                            resource="role",
                            region="",
                            arn_format=ArnFormat.SLASH_RESOURCE_NAME,
                            resource_name=f"sdlf-{p_datasetname.value_as_string}/sdlf-*",
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
                        scope.format_arn(
                            service="glue",
                            resource="catalog",
                            arn_format=ArnFormat.NO_RESOURCE_NAME,
                        ),
                        scope.format_arn(
                            service="glue",
                            resource="database",
                            arn_format=ArnFormat.SLASH_RESOURCE_NAME,
                            resource_name=f"{p_org.value_as_string}_{p_domain.value_as_string}_{p_datasetname.value_as_string}_*",
                        ),
                        scope.format_arn(
                            service="glue",
                            resource="table",
                            arn_format=ArnFormat.SLASH_RESOURCE_NAME,
                            resource_name=f"{p_org.value_as_string}_{p_domain.value_as_string}_{p_datasetname.value_as_string}_*",
                        ),
                        scope.format_arn(
                            service="glue",
                            resource="crawler",
                            arn_format=ArnFormat.SLASH_RESOURCE_NAME,
                            resource_name=f"sdlf-{p_datasetname.value_as_string}-*",
                        ),
                        scope.format_arn(
                            service="glue",
                            resource="job",
                            arn_format=ArnFormat.SLASH_RESOURCE_NAME,
                            resource_name=f"sdlf-{p_datasetname.value_as_string}-*",
                        ),
                        scope.format_arn(
                            service="glue",
                            resource="job",
                            arn_format=ArnFormat.SLASH_RESOURCE_NAME,
                            resource_name=f"{p_org.value_as_string}-{p_domain.value_as_string}-{p_datasetname.value_as_string}-*",
                        ),
                        scope.format_arn(
                            service="glue",
                            resource="dataQualityRuleset",
                            arn_format=ArnFormat.SLASH_RESOURCE_NAME,
                            resource_name="*",  # glue:StartDataQualityRuleRecommendationRun requires dataQualityRuleset/*
                        ),
                    ],
                ),
                iam.PolicyStatement(
                    actions=["logs:CreateLogGroup"],
                    resources=[
                        scope.format_arn(
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
                        scope.format_arn(
                            service="logs",
                            resource="log-group",
                            arn_format=ArnFormat.COLON_RESOURCE_NAME,
                            resource_name=f"/aws/lambda/sdlf-{p_datasetname.value_as_string}-*",
                        ),
                        scope.format_arn(
                            service="logs",
                            resource="log-group",
                            arn_format=ArnFormat.COLON_RESOURCE_NAME,
                            resource_name=f"/aws/codebuild/sdlf-{p_datasetname.value_as_string}-*",
                        ),
                        scope.format_arn(
                            service="logs",
                            resource="log-group",
                            arn_format=ArnFormat.COLON_RESOURCE_NAME,
                            resource_name=f"/aws-glue/jobs/sdlf-{p_datasetname.value_as_string}-*",
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
                        scope.format_arn(
                            service="cloudformation",
                            resource="stack",
                            arn_format=ArnFormat.COLON_RESOURCE_NAME,
                            resource_name=f"sdlf-{p_datasetname.value_as_string}:*",
                        ),
                    ],
                ),
                iam.PolicyStatement(
                    actions=[
                        "lambda:InvokeFunction",
                    ],
                    resources=[
                        scope.format_arn(
                            service="lambda",
                            resource="function",
                            arn_format=ArnFormat.COLON_RESOURCE_NAME,
                            resource_name=f"sdlf-{p_datasetname.value_as_string}-*",
                        ),
                    ],
                ),
                iam.PolicyStatement(
                    actions=["events:PutTargets", "events:PutRule", "events:DescribeRule"],
                    resources=[
                        scope.format_arn(
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
                        scope.format_arn(
                            service="emr-serverless",
                            resource="/applications/*",
                            arn_format=ArnFormat.NO_RESOURCE_NAME,
                        ),
                    ],
                ),
            ],
        )
        self._external_interface(
            permissions_boundary_resource_name,
            "The permissions boundary IAM Managed policy for the team",
            permissions_boundary.managed_policy_arn,
        )

        peh_table_resource_name = "rDynamoPipelineExecutionHistory"
        peh_table = ddb.Table(
            self,
            peh_table_resource_name,
            removal_policy=RemovalPolicy.DESTROY,
            partition_key=ddb.Attribute(
                name="id",
                type=ddb.AttributeType.STRING,
            ),
            billing_mode=ddb.BillingMode.PAY_PER_REQUEST,
            table_name=f"sdlf-PipelineExecutionHistory-{p_datasetname.value_as_string}",
            encryption=ddb.TableEncryption.CUSTOMER_MANAGED,
            encryption_key=infra_kms_key,
            point_in_time_recovery=True,
            time_to_live_attribute="ttl",
        )
        peh_table.add_global_secondary_index(
            index_name="pipeline-last-updated-index",
            partition_key=ddb.Attribute(
                name="pipeline",
                type=ddb.AttributeType.STRING,
            ),
            sort_key=ddb.Attribute(
                name="last_updated_timestamp",
                type=ddb.AttributeType.STRING,
            ),
            projection_type=ddb.ProjectionType.ALL,
        )
        peh_table.add_global_secondary_index(
            index_name="execution_date-status-index",
            partition_key=ddb.Attribute(
                name="execution_date",
                type=ddb.AttributeType.STRING,
            ),
            sort_key=ddb.Attribute(
                name="status",
                type=ddb.AttributeType.STRING,
            ),
            projection_type=ddb.ProjectionType.ALL,
        )
        peh_table.add_global_secondary_index(
            index_name="pipeline-execution_date-index",
            partition_key=ddb.Attribute(
                name="pipeline",
                type=ddb.AttributeType.STRING,
            ),
            sort_key=ddb.Attribute(
                name="execution_date",
                type=ddb.AttributeType.STRING,
            ),
            projection_type=ddb.ProjectionType.ALL,
        )
        peh_table.add_global_secondary_index(
            index_name="execution_date-last_updated-index",
            partition_key=ddb.Attribute(
                name="execution_date",
                type=ddb.AttributeType.STRING,
            ),
            sort_key=ddb.Attribute(
                name="last_updated_timestamp",
                type=ddb.AttributeType.STRING,
            ),
            projection_type=ddb.ProjectionType.ALL,
        )
        peh_table.add_global_secondary_index(
            index_name="status-last_updated-index",
            partition_key=ddb.Attribute(
                name="status",
                type=ddb.AttributeType.STRING,
            ),
            sort_key=ddb.Attribute(
                name="last_updated_timestamp",
                type=ddb.AttributeType.STRING,
            ),
            projection_type=ddb.ProjectionType.ALL,
        )
        peh_table.add_global_secondary_index(
            index_name="pipeline-status_last_updated-index",
            partition_key=ddb.Attribute(
                name="pipeline",
                type=ddb.AttributeType.STRING,
            ),
            sort_key=ddb.Attribute(
                name="status_last_updated_timestamp",
                type=ddb.AttributeType.STRING,
            ),
            projection_type=ddb.ProjectionType.ALL,
        )
        peh_table.add_global_secondary_index(
            index_name="dataset-status_last_updated_timestamp-index",
            partition_key=ddb.Attribute(
                name="dataset",
                type=ddb.AttributeType.STRING,
            ),
            sort_key=ddb.Attribute(
                name="status_last_updated_timestamp",
                type=ddb.AttributeType.STRING,
            ),
            projection_type=ddb.ProjectionType.ALL,
        )
        self._external_interface(
            peh_table_resource_name,
            "Name of the DynamoDB used to store pipeline history metadata",
            peh_table.table_name,
        )

        manifests_table_resource_name = "rDynamoManifests"
        manifests_table = ddb.Table(
            self,
            manifests_table_resource_name,
            removal_policy=RemovalPolicy.DESTROY,
            partition_key=ddb.Attribute(
                name="dataset_name",
                type=ddb.AttributeType.STRING,
            ),
            sort_key=ddb.Attribute(
                name="datafile_name",
                type=ddb.AttributeType.STRING,
            ),
            billing_mode=ddb.BillingMode.PAY_PER_REQUEST,
            table_name=f"sdlf-Manifests-{p_datasetname.value_as_string}",
            encryption=ddb.TableEncryption.CUSTOMER_MANAGED,
            encryption_key=infra_kms_key,
            point_in_time_recovery=True,
            time_to_live_attribute="ttl",
        )
        self._external_interface(
            manifests_table_resource_name,
            "Name of the DynamoDB used to store manifest process metadata",
            manifests_table.table_name,
        )

        # CloudFormation Outputs TODO
        CfnOutput(
            self,
            "oPipelineReference",
            description="CodePipeline reference this stack has been deployed with",
            value=p_pipelinereference.value_as_string,
        )

    def _external_interface(self, resource_name, description, value):
        ssm.StringParameter(
            self,
            f"{resource_name}Ssm",
            description=description,
            parameter_name=f"/sdlf/dataset/{resource_name}",
            string_value=value,
        )
        self.external_interface[resource_name] = value

    def data_catalog(self, scope, org, domain, dataset, bucket_layer, bucket, s3_prefix, lf_tag_pair_property):
        glue_catalog_resource_name = f"r{bucket_layer.capitalize()}GlueDataCatalog"
        glue_catalog = glue_a.Database(
            self,
            glue_catalog_resource_name,
            database_name=f"{org}_{domain}_{dataset}_{bucket_layer}",
            description=f"{dataset} {bucket_layer} metadata catalog",
        )
        self._external_interface(
            glue_catalog_resource_name,
            f"{dataset} {bucket_layer} metadata catalog",
            glue_catalog.database_arn,
        )

        lakeformation.CfnTagAssociation(
            self,
            f"{glue_catalog_resource_name}LakeFormationTag",
            lf_tags=[lf_tag_pair_property],
            resource=lakeformation.CfnTagAssociation.ResourceProperty(
                database=lakeformation.CfnTagAssociation.DatabaseResourceProperty(
                    catalog_id=scope.account, name=glue_catalog.database_name
                )
            ),
        )

        glue_crawler_resource_name = f"r{bucket_layer.capitalize()}GlueCrawler"
        glue_crawler = glue.CfnCrawler(
            self,
            glue_crawler_resource_name,
            name=f"sdlf-{dataset}-{bucket_layer}-crawler",
            role=self.datalakecrawler_role.role_arn,
            crawler_security_configuration=self.glue_security_configuration.security_configuration_name,
            database_name=glue_catalog.database_name,
            targets=glue.CfnCrawler.TargetsProperty(
                s3_targets=[
                    glue.CfnCrawler.S3TargetProperty(
                        path=f"s3://{bucket}/{s3_prefix}",
                    )
                ]
            ),
        )

        lakeformation.CfnPermissions(
            self,
            f"{glue_crawler_resource_name}GlueLakeFormationPermissions",
            data_lake_principal=lakeformation.CfnPermissions.DataLakePrincipalProperty(
                data_lake_principal_identifier=self.datalakecrawler_role.role_arn,
            ),
            resource=lakeformation.CfnPermissions.ResourceProperty(
                database_resource=lakeformation.CfnPermissions.DatabaseResourceProperty(name=glue_catalog.database_name)
            ),
            permissions=["CREATE_TABLE", "ALTER", "DROP"],
        )

        lakeformation.CfnPermissions(
            self,
            f"{glue_crawler_resource_name}S3LakeFormationPermissions",
            data_lake_principal=lakeformation.CfnPermissions.DataLakePrincipalProperty(
                data_lake_principal_identifier=self.datalakecrawler_role.role_arn
            ),
            resource=lakeformation.CfnPermissions.ResourceProperty(
                data_location_resource=lakeformation.CfnPermissions.DataLocationResourceProperty(
                    s3_resource=scope.format_arn(
                        service="s3",
                        resource=f"{bucket}/{s3_prefix}/",
                        region="",
                        account="",
                        arn_format=ArnFormat.NO_RESOURCE_NAME,
                    )
                ),
            ),
            permissions=["DATA_LOCATION_ACCESS"],
        )
        self._external_interface(
            glue_crawler_resource_name,
            f"{dataset} {bucket_layer.capitalize()} Glue crawler",
            glue_crawler.name,
        )

        return glue_catalog
