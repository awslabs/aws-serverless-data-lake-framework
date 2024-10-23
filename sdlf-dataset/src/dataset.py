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
    aws_dynamodb as ddb,
    aws_emr as emr,
    aws_events as events,
    aws_events_targets as targets,
    aws_glue as glue,
    aws_glue_alpha as glue_a,
    aws_iam as iam,
    aws_kms as kms,
    aws_lakeformation as lakeformation,
    aws_scheduler as scheduler,
    aws_ssm as ssm,
)
from constructs import Construct


class Dataset(Construct):
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
        p_org = CfnParameter(
            self,
            "pOrg",
            description="Name of the organization owning the datalake",
            type="String",
            default="{{resolve:ssm:/SDLF/Misc/pOrg:1}}",
        )
        p_org.override_logical_id("pOrg")
        p_domain = CfnParameter(
            self,
            "pDomain",
            description="Data domain name",
            type="String",
            default="{{resolve:ssm:/SDLF/Misc/pDomain:1}}",
        )
        p_domain.override_logical_id("pDomain")
        p_environment = CfnParameter(
            self,
            "pEnvironment",
            description="Environment name",
            type="String",
            default="{{resolve:ssm:/SDLF/Misc/pEnv:1}}",
        )
        p_environment.override_logical_id("pEnvironment")
        p_rawbucket = CfnParameter(
            self,
            "pRawBucket",
            description="The raw bucket for the solution",
            type="String",
            default="{{resolve:ssm:/SDLF/S3/RawBucket:1}}",
        )
        p_rawbucket.override_logical_id("pRawBucket")
        p_stagebucket = CfnParameter(
            self,
            "pStageBucket",
            description="The stage bucket for the solution",
            type="String",
            default="{{resolve:ssm:/SDLF/S3/StageBucket:1}}",
        )
        p_stagebucket.override_logical_id("pStageBucket")
        p_analyticsbucket = CfnParameter(
            self,
            "pAnalyticsBucket",
            description="The analytics bucket for the solution",
            type="String",
            default="{{resolve:ssm:/SDLF/S3/AnalyticsBucket:1}}",
        )
        p_analyticsbucket.override_logical_id("pAnalyticsBucket")
        p_artifactsbucket = CfnParameter(
            self,
            "pArtifactsBucket",
            description="The artifacts bucket  used by CodeBuild and CodePipeline",
            type="String",
            default="{{resolve:ssm:/SDLF/S3/ArtifactsBucket:1}}",
        )
        p_artifactsbucket.override_logical_id("pArtifactsBucket")
        p_lakeformationdataaccessrole = CfnParameter(
            self,
            "pLakeFormationDataAccessRole",
            type="String",
            default="{{resolve:ssm:/SDLF/IAM/LakeFormationDataAccessRoleArn:1}}",
        )
        p_lakeformationdataaccessrole.override_logical_id("pLakeFormationDataAccessRole")
        p_datasetname = CfnParameter(
            self,
            "pDatasetName",
            description="The name of the dataset (all lowercase, no symbols or spaces)",
            type="String",
            allowed_pattern="[a-z0-9]{2,14}",
        )
        p_datasetname.override_logical_id("pDatasetName")
        p_s3prefix = CfnParameter(
            self,
            "pS3Prefix",
            description="S3 prefix or full bucket if empty/not provided",
            type="String",
            allowed_pattern="[a-z0-9]*",
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
        p_pipelinedetails = CfnParameter(
            self,
            "pPipelineDetails",
            type="String",
            default="""
                {
                    "main": {
                    "B": {
                        "glue_capacity": {
                            "NumberOfWorkers": 10,
                            "WorkerType": "G.1X"
                        },
                        "glue_extra_arguments": {
                            "--enable-auto-scaling": "true"
                        }
                    }
                    }
                }
            """,
        )
        p_pipelinedetails.override_logical_id("pPipelineDetails")

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
            description=f"SDLF {p_datasetname.value_as_string} Infrastructure KMS Key",
            enable_key_rotation=True,
            policy=infra_kms_key_policy,
        )
        infra_kms_key.add_alias(f"alias/sdlf-{p_datasetname.value_as_string}-kms-infra-key").apply_removal_policy(
            RemovalPolicy.RETAIN_ON_UPDATE_OR_DELETE
        )

        ssm.StringParameter(
            self,
            "rKMSInfraKeySsm",
            description=f"Arn of the {p_datasetname.value_as_string} KMS infrastructure key",
            parameter_name=f"/SDLF/KMS/{p_datasetname.value_as_string}/InfraKeyId",
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

        s3_prefix_condition = CfnCondition(
            self, "IsS3Prefix", expression=Fn.condition_not(Fn.condition_equals(p_s3prefix.value_as_string, ""))
        )

        data_kms_key = kms.Key(
            self,
            "rKMSDataKey",
            removal_policy=RemovalPolicy.RETAIN_ON_UPDATE_OR_DELETE,
            description=f"SDLF {p_datasetname.value_as_string} Data KMS Key",
            enable_key_rotation=True,
            policy=data_kms_key_policy,
        )
        data_kms_key.node.default_child.cfn_options.condition = s3_prefix_condition
        data_kms_key_alias = data_kms_key.add_alias(f"alias/sdlf-{p_datasetname.value_as_string}-kms-data-key")
        data_kms_key_alias.apply_removal_policy(RemovalPolicy.RETAIN_ON_UPDATE_OR_DELETE)
        data_kms_key_alias.node.default_child.cfn_options.condition = s3_prefix_condition

        ssm.StringParameter(
            self,
            "rKMSDataKeySsm",
            description=f"Arn of the {p_datasetname.value_as_string} KMS data key",
            parameter_name=f"/SDLF/KMS/{p_datasetname.value_as_string}/DataKeyId",
            simple_name=False,  # parameter name is a token
            string_value=data_kms_key.key_arn,
        ).node.default_child.cfn_options.condition = s3_prefix_condition

        ######## GLUE #########
        self.glue_security_configuration = glue_a.SecurityConfiguration(
            self,
            "rGlueSecurityConfiguration",
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
        ssm.StringParameter(
            self,
            "rGlueSecurityConfigurationSsm",
            description=f"Name of the {p_datasetname.value_as_string} Glue security configuration",
            parameter_name=f"/SDLF/Glue/{p_datasetname.value_as_string}/SecurityConfigurationId",
            simple_name=False,  # parameter name is a token
            string_value=self.glue_security_configuration.security_configuration_name,
        )

        emr_security_configuration = emr.CfnSecurityConfiguration(
            self,
            "rEMRSecurityConfiguration",
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

        self.datalakecrawler_role = iam.Role(
            self,
            "rDatalakeCrawlerRole",
            path=f"/sdlf-{p_datasetname.value_as_string}/",
            assumed_by=iam.ServicePrincipal("glue.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSGlueServiceRole"),
            ],
        )
        self.datalakecrawler_role.attach_inline_policy(datalakecrawler_role_policy)

        ssm.StringParameter(
            self,
            "rDatalakeCrawlerRoleArnSsm",
            description="The ARN of the Crawler role",
            parameter_name=f"/SDLF/IAM/{p_datasetname.value_as_string}/CrawlerRoleArn",
            simple_name=False,  # parameter name is a token
            string_value=self.datalakecrawler_role.role_arn,
        )

        raw_glue_catalog = self.data_catalog(
            scope,
            p_org.value_as_string,
            p_domain.value_as_string,
            p_environment.value_as_string,
            p_datasetname.value_as_string,
            "raw",
            p_rawbucket.value_as_string,
            p_s3prefix.value_as_string,
        )

        stage_glue_catalog = self.data_catalog(
            scope,
            p_org.value_as_string,
            p_domain.value_as_string,
            p_environment.value_as_string,
            p_datasetname.value_as_string,
            "stage",
            p_stagebucket.value_as_string,
            p_s3prefix.value_as_string,
        )

        analytics_glue_catalog = self.data_catalog(
            scope,
            p_org.value_as_string,
            p_domain.value_as_string,
            p_environment.value_as_string,
            p_datasetname.value_as_string,
            "analytics",
            p_analyticsbucket.value_as_string,
            p_s3prefix.value_as_string,
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
        lf_tag_association = lakeformation.CfnTagAssociation(
            self,
            "rGlueDataCatalogLakeFormationTag",
            lf_tags=[lf_tag_pair_property],
            resource=lakeformation.CfnTagAssociation.ResourceProperty(
                database=lakeformation.CfnTagAssociation.DatabaseResourceProperty(
                    catalog_id=scope.account, name=stage_glue_catalog.database_name
                )
            ),
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
        bus = events.EventBus(self, "rEventBus", event_bus_name=f"sdlf-{p_datasetname.value_as_string}")
        ssm.StringParameter(
            self,
            "rEventBusSsm",
            description=f"Name of the {p_datasetname.value_as_string} event bus",
            parameter_name=f"/SDLF/EventBridge/{p_datasetname.value_as_string}/EventBusName",
            simple_name=False,  # parameter name is a token
            string_value=bus.event_bus_name,
        )

        schedule_group = scheduler.CfnScheduleGroup(
            self,
            "rScheduleGroup",
            name=f"sdlf-{p_datasetname.value_as_string}",
        )
        ssm.StringParameter(
            self,
            "rScheduleGroupSsm",
            description=f"Name of the {p_datasetname.value_as_string} schedule group",
            parameter_name=f"/SDLF/EventBridge/{p_datasetname.value_as_string}/ScheduleGroupName",
            simple_name=False,  # parameter name is a token
            string_value=schedule_group.name,
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
                source=events.Match.prefix("aws."), account=[scope.account], region=[scope.region]
            ),
            targets=[targets.EventBus(bus, role=forwardeventbustrigger_role)],
        )

        ######## IAM #########
        permissions_boundary = iam.ManagedPolicy(
            self,
            "rIamManagedPolicy",
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
                    resources=["{{resolve:ssm:/SDLF/KMS/KeyArn}}", infra_kms_key.key_arn, data_kms_key.key_arn],
                ),
                iam.PolicyStatement(
                    actions=["ssm:GetParameter", "ssm:GetParameters"],
                    resources=[
                        scope.format_arn(
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
                        scope.format_arn(
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
                            resource_name=f"{p_org.value_as_string}_{p_domain.value_as_string}_{p_environment.value_as_string}_{p_datasetname.value_as_string}_*",
                        ),
                        scope.format_arn(
                            service="glue",
                            resource="table",
                            arn_format=ArnFormat.SLASH_RESOURCE_NAME,
                            resource_name=f"{p_org.value_as_string}_{p_domain.value_as_string}_{p_environment.value_as_string}_{p_datasetname.value_as_string}_*",
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
                            resource_name=f"{p_org.value_as_string}-{p_domain.value_as_string}-{p_environment.value_as_string}-{p_datasetname.value_as_string}-*",
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
        ssm.StringParameter(
            self,
            "rIamManagedPolicySsm",
            description="The permissions boundary IAM Managed policy for the team",
            parameter_name=f"/SDLF/IAM/{p_datasetname.value_as_string}/TeamPermissionsBoundary",
            simple_name=False,  # parameter name is a token
            string_value=permissions_boundary.managed_policy_arn,
        )

        peh_table = ddb.Table(
            self,
            "rDynamoPipelineExecutionHistory",
            removal_policy=RemovalPolicy.DESTROY,
            partition_key=ddb.Attribute(
                name="id",
                type=ddb.AttributeType.STRING,
            ),
            billing_mode=ddb.BillingMode.PAY_PER_REQUEST,
            table_name=f"octagon-PipelineExecutionHistory-{p_datasetname.value_as_string}-{p_environment.value_as_string}",
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
        ssm.StringParameter(
            self,
            "rDynamoPipelineExecutionHistorySsm",
            description="Name of the DynamoDB used to store manifest process metadata",
            parameter_name=f"/SDLF/Dynamo/{p_datasetname.value_as_string}/PipelineExecutionHistory",
            simple_name=False,  # parameter name is a token
            string_value=peh_table.table_name,
        )

        manifests_table = ddb.Table(
            self,
            "rDynamoManifests",
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
            table_name=f"octagon-Manifests-{p_datasetname.value_as_string}-{p_environment.value_as_string}",
            encryption=ddb.TableEncryption.CUSTOMER_MANAGED,
            encryption_key=infra_kms_key,
            point_in_time_recovery=True,
            time_to_live_attribute="ttl",
        )
        ssm.StringParameter(
            self,
            "rDynamoManifestsSsm",
            description="Name of the DynamoDB used to store manifest process metadata",
            parameter_name=f"/SDLF/Dynamo/{p_datasetname.value_as_string}/Manifests",
            simple_name=False,  # parameter name is a token
            string_value=manifests_table.table_name,
        )

        ssm.StringParameter(
            self,
            "rDatasetSsm",
            description=f"Placeholder {p_datasetname.value_as_string}",
            parameter_name=f"/SDLF/Datasets/{p_datasetname.value_as_string}",
            simple_name=False,  # parameter name is a token
            string_value=p_pipelinedetails.value_as_string,  # bit of a hack for datasets lambda
        )

        # CloudFormation Outputs TODO
        CfnOutput(
            self,
            "oPipelineReference",
            description="CodePipeline reference this stack has been deployed with",
            value=p_pipelinereference.value_as_string,
        )
        CfnOutput(
            self,
            "oPipelineTransforms",
            description="Transforms to put in DynamoDB",
            value=p_pipelinedetails.value_as_string,
        )

    def data_catalog(self, scope, org, domain, environment, dataset, bucket_layer, bucket, s3_prefix):
        glue_catalog = glue_a.Database(
            self,
            f"r{bucket_layer.capitalize()}GlueDataCatalog",
            database_name=f"{org}_{domain}_{environment}_{dataset}_{bucket_layer}",
            description=f"{dataset} {bucket_layer} metadata catalog",
        )
        ssm.StringParameter(
            self,
            f"r{bucket_layer.capitalize()}GlueDataCatalogSsm",
            description=f"{dataset} {bucket_layer} metadata catalog",
            parameter_name=f"/SDLF/Glue/{dataset}/{bucket_layer.capitalize()}DataCatalog",
            simple_name=False,  # parameter name is a token
            string_value=glue_catalog.database_arn,
        )

        glue_crawler = glue.CfnCrawler(
            self,
            f"r{bucket_layer.capitalize()}GlueCrawler",
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
            f"r{bucket_layer.capitalize()}GlueCrawlerLakeFormationPermissions",
            data_lake_principal=lakeformation.CfnPermissions.DataLakePrincipalProperty(
                data_lake_principal_identifier=self.datalakecrawler_role.role_arn,
            ),
            resource=lakeformation.CfnPermissions.ResourceProperty(
                database_resource=lakeformation.CfnPermissions.DatabaseResourceProperty(
                    name=glue_catalog.database_name
                )
            ),
            permissions=["CREATE_TABLE", "ALTER", "DROP"],
        )

        lakeformation.CfnPermissions(
            self,
            f"r{bucket_layer.capitalize()}LakeFormationPermissions",
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

        ssm.StringParameter(
            self,
            f"r{bucket_layer.capitalize()}GlueCrawlerSsm",
            description=f"{dataset} {bucket_layer.capitalize()} Glue crawler",
            parameter_name=f"/SDLF/Glue/{dataset}/{bucket_layer.capitalize()}GlueCrawler",
            simple_name=False,  # parameter name is a token
            string_value=glue_crawler.name,
        )

        return glue_catalog
