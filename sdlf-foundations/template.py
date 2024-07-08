# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT

import os.path

from aws_cdk import (
    ArnFormat,
    Duration,
    Stack,
    CfnParameter,
    CfnOutput,
    aws_dynamodb as ddb,
    aws_events as events,
    aws_events_targets as targets,
    aws_iam as iam,
    aws_kms as kms,
    aws_lakeformation as lakeformation,
    aws_lambda as _lambda,
    aws_lambda_event_sources as eventsources,
    aws_logs as logs,
    aws_s3 as s3,
    aws_sqs as sqs,
    aws_ssm as ssm,
)
from constructs import Construct

class SdlfFoundations(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        dirname = os.path.dirname(__file__)
        run_in_vpc = False

        # using context values would be better(?) for CDK but we haven't decided yet what the story is around ServiceCatalog and CloudFormation modules
        # perhaps both (context values feeding into CfnParameter) would be a nice-enough solution. Not sure though. TODO
        p_pipelinereference = CfnParameter(self, "pPipelineReference",
            type="String",
            default="none",
        )
        p_childaccountid = CfnParameter(self, "pChildAccountId",
            description="Child AWS account ID",
            type="String",
            allowed_pattern="(\\d{12}|^$)",
            constraint_description="Must be an AWS account ID",
        )
        p_org = CfnParameter(self, "pOrg",
            description="Name of the organization owning the datalake (all lowercase, no symbols or spaces)",
            type="String",
            allowed_pattern="[a-z0-9]{2,9}",
        )
        p_domain = CfnParameter(self, "pDomain",
            description="Data domain name",
            type="String",
        )
        p_environment = CfnParameter(self, "pEnvironment",
            description="Environment name",
            type="String",
        )
        # p_cloudwatchlogsretentionindays = CfnParameter(self, "pCloudWatchLogsRetentionInDays",
        #     description="The number of days log events are kept in CloudWatch Logs",
        #     type="Number",
        #     allowed_values=[1, 3, 5, 7, 14, 30, 60, 90, 120, 150, 180, 365, 400, 545, 731, 1827, 3653],
        #     default=30,
        # )

        ssm.StringParameter(self, "rOrganizationSsm",
            description="Name of the Organization owning the datalake",
            parameter_name="/SDLF/Misc/pOrg",
            string_value=p_org.value_as_string,
        )
        ssm.StringParameter(self, "rDomainSsm",
            description="Data domain name",
            parameter_name="/SDLF/Misc/pDomain",
            string_value=p_domain.value_as_string,
        )
        ssm.StringParameter(self, "rEnvironmentSsm",
            description="Environment name",
            parameter_name="/SDLF/Misc/pEnv",
            string_value=p_environment.value_as_string,
        )


        datalakeadmin_role_managed_policies = [
            iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSGlueServiceRole"),
            iam.ManagedPolicy.from_aws_managed_policy_name("AmazonS3FullAccess"),
            iam.ManagedPolicy.from_aws_managed_policy_name("AWSLakeFormationDataAdmin")
        ]
        if run_in_vpc:
            datalakeadmin_role_managed_policies.append(iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaVPCAccessExecutionRole"))

        datalakeadmin_role_policy = iam.Policy(self, "sdlf-lakeformation-admin",
            statements=[
                iam.PolicyStatement(
                    actions=["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents", "logs:AssociateKmsKey"],
                    resources=[
                        self.format_arn(
                            service="logs",
                            resource="log-group",
                            arn_format=ArnFormat.COLON_RESOURCE_NAME,
                            resource_name="/aws/lambda/sdlf-glue-replication"
                        ),
                        self.format_arn(
                            service="logs",
                            resource="log-group",
                            arn_format=ArnFormat.COLON_RESOURCE_NAME,
                            resource_name="/aws/glue/*"
                        ),
                        self.format_arn(
                            service="logs",
                            resource="log-group",
                            arn_format=ArnFormat.COLON_RESOURCE_NAME,
                            resource_name="/aws/codebuild/sdlf-*"
                        ),
                        self.format_arn(
                            service="logs",
                            resource="log-group",
                            arn_format=ArnFormat.COLON_RESOURCE_NAME,
                            resource_name="sdlf-*"
                        )
                    ]
                ),
                iam.PolicyStatement(
                    sid="DynamoDBAccess",
                    actions=[
                        "dynamodb:BatchGetItem",
                        "dynamodb:BatchWriteItem",
                        "dynamodb:DeleteItem",
                        "dynamodb:DescribeTable",
                        "dynamodb:GetItem",
                        "dynamodb:Query",
                        "dynamodb:PutItem",
                        "dynamodb:Scan",
                        "dynamodb:UpdateItem"
                    ],
                    resources=[
                        self.format_arn(
                            service="dynamodb",
                            resource="table",
                            arn_format=ArnFormat.SLASH_RESOURCE_NAME,
                            resource_name="octagon-*"
                        )
                    ]
                ),
                iam.PolicyStatement(
                    sid="SSMAccess",
                    actions=[
                        "ssm:GetParameter",
                        "ssm:GetParameters",
                    ],
                    resources=[
                        self.format_arn(
                            service="ssm",
                            resource="parameter",
                            arn_format=ArnFormat.SLASH_RESOURCE_NAME,
                            resource_name="/SDLF/IAM/DataLakeAdminRoleArn"
                        ),
                        self.format_arn(
                            service="ssm",
                            resource="parameter",
                            arn_format=ArnFormat.SLASH_RESOURCE_NAME,
                            resource_name="/SDLF/Dynamo/DataSchemas"
                        )
                    ]
                )
            ]
        )

        datalakeadmin_role = iam.Role(self, "rDataLakeAdminRole",
            assumed_by=iam.CompositePrincipal(
                iam.ServicePrincipal("lambda.amazonaws.com"),
                iam.ServicePrincipal("glue.amazonaws.com"),
            ),
            managed_policies=datalakeadmin_role_managed_policies,
        )
        datalakeadmin_role.attach_inline_policy(datalakeadmin_role_policy)

        ssm.StringParameter(self, "rDataLakeAdminRoleSsm",
            description="Lake Formation Data Lake Admin Role",
            parameter_name="/SDLF/IAM/DataLakeAdminRoleArn",
            string_value=datalakeadmin_role.role_arn,
        )

        ######## LAKE FORMATION #########
        lakeformation.CfnDataLakeSettings(self, "rDataLakeSettings",
            admins=[
                lakeformation.CfnDataLakeSettings.DataLakePrincipalProperty(
                    data_lake_principal_identifier=datalakeadmin_role.role_arn
                ),
            ],
            create_database_default_permissions=[],
            create_table_default_permissions=[],
            mutation_type="REPLACE"
        )

        # https://docs.aws.amazon.com/lake-formation/latest/dg/registration-role.html
        lakeformationdataaccess_role_policy = iam.Policy(self, "CloudWatchLogs",
            statements=[
                iam.PolicyStatement(
                    actions=["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
                    resources=[
                        self.format_arn(
                            service="logs",
                            resource="log-group",
                            arn_format=ArnFormat.COLON_RESOURCE_NAME,
                            resource_name="/aws-lakeformation-acceleration/*"
                        ),
                        self.format_arn(
                            service="logs",
                            resource="log-group",
                            arn_format=ArnFormat.COLON_RESOURCE_NAME,
                            resource_name="/aws-lakeformation-acceleration/*:log-stream:*"
                        ),
                    ]
                ),
            ]
        )

        lakeformationdataaccess_role = iam.Role(self, "rLakeFormationDataAccessRole",
            assumed_by=iam.CompositePrincipal(
                iam.ServicePrincipal("lakeformation.amazonaws.com"),
                iam.ServicePrincipal("glue.amazonaws.com"),
            ),
        )
        lakeformationdataaccess_role.attach_inline_policy(lakeformationdataaccess_role_policy)

        ssm.StringParameter(self, "rLakeFormationDataAccessRoleSsm",
            description="Lake Formation Data Access Role",
            parameter_name="/SDLF/IAM/LakeFormationDataAccessRoleArn",
            string_value=lakeformationdataaccess_role.role_arn,
        )
        ssm.StringParameter(self, "rLakeFormationDataAccessRoleNameSsm",
            description="Lake Formation Data Access Role",
            parameter_name="/SDLF/IAM/LakeFormationDataAccessRole",
            string_value=lakeformationdataaccess_role.role_name,
        )


        ######## KMS #########
        kms_key_policy = iam.PolicyDocument(
            statements=[
                iam.PolicyStatement(
                    sid="Allow administration of the key",
                    effect=iam.Effect.ALLOW,
                    principals=[iam.AccountRootPrincipal()],
                    actions=["kms:*"],
                    resources=["*"]
                ),
                iam.PolicyStatement(
                    sid="Allow CloudTrail/CloudWatch alarms access",
                    effect=iam.Effect.ALLOW,
                    principals=[
                        iam.ServicePrincipal("cloudtrail.amazonaws.com"),
                        iam.ServicePrincipal("cloudwatch.amazonaws.com"),
                        iam.ServicePrincipal("events.amazonaws.com"),
                    ],
                    actions=["kms:Decrypt", "kms:GenerateDataKey*"],
                    resources=["*"]
                ),
                iam.PolicyStatement(
                    sid="Allow logs access",
                    effect=iam.Effect.ALLOW,
                    principals=[
                        iam.ServicePrincipal("logs.amazonaws.com", region=self.region),
                    ],
                    actions=["kms:CreateGrant", "kms:Decrypt", "kms:DescribeKey", "kms:Encrypt", "kms:GenerateDataKey*", "kms:ReEncrypt*"],
                    resources=["*"]
                ),
                iam.PolicyStatement(
                    sid="Allow SNS access",
                    effect=iam.Effect.ALLOW,
                    actions=["kms:Decrypt", "kms:GenerateDataKey*"],
                    principals=[iam.AnyPrincipal()],
                    resources=["*"],
                    conditions={ "StringEquals": {"kms:CallerAccount": self.account, "kms:ViaService": f"sns.{self.region}.amazonaws.com"}}
                ),
                iam.PolicyStatement(
                    sid="Allow S3 Events access",
                    effect=iam.Effect.ALLOW,
                    principals=[
                        iam.ServicePrincipal("s3.amazonaws.com"),
                    ],
                    actions=["kms:Decrypt", "kms:GenerateDataKey*"],
                    resources=["*"]
                ),
                iam.PolicyStatement(
                    sid="Allow DynamoDB access",
                    effect=iam.Effect.ALLOW,
                    principals=[iam.AnyPrincipal()],
                    actions=["kms:CreateGrant", "kms:Decrypt", "kms:DescribeKey", "kms:Encrypt", "kms:GenerateDataKey*", "kms:ReEncrypt*"],
                    resources=["*"],
                    conditions={ "StringEquals": {"kms:CallerAccount": self.account, "kms:ViaService": f"dynamodb.{self.region}.amazonaws.com"}}
                ),
                iam.PolicyStatement(
                    sid="Allow ElasticSearch access",
                    effect=iam.Effect.ALLOW,
                    principals=[iam.AnyPrincipal()],
                    actions=["kms:CreateGrant", "kms:Decrypt", "kms:DescribeKey", "kms:Encrypt", "kms:GenerateDataKey*", "kms:ReEncrypt*"],
                    resources=["*"],
                    conditions={ "StringEquals": {"kms:CallerAccount": self.account, "kms:ViaService": f"es.{self.region}.amazonaws.com"}, "Bool": {"kms:GrantIsForAWSResource": "true"}}
                ),
                iam.PolicyStatement(
                    sid="Allow LakeFormation access",
                    effect=iam.Effect.ALLOW,
                    principals=[
                        iam.ArnPrincipal(lakeformationdataaccess_role.role_arn),
                    ],
                    actions=["kms:Encrypt*", "kms:Decrypt*", "kms:ReEncrypt*", "kms:GenerateDataKey*", "kms:Describe*"],
                    resources=["*"]
                ),
            ]
        )

        kms_key = kms.Key(self, "rKMSKey",
            description="SDLF Foundations KMS Key",
            policy=kms_key_policy,
        )
        kms_key.add_alias("alias/sdlf-kms-key")

        ssm.StringParameter(self, "rKMSKeySsm",
            description="ARN of the KMS key",
            parameter_name="/SDLF/KMS/KeyArn",
            string_value=kms_key.key_arn,
        )

        ######## S3 #########
        ####### Access Logging Bucket ######
        access_logs_bucket_name = f"{p_org.value_as_string}-{p_domain.value_as_string}-{p_environment.value_as_string}-{self.region}-{self.account}-s3logs"
        access_logs_bucket = s3.Bucket(self, "rS3AccessLogsBucket",
            bucket_name=access_logs_bucket_name, # TODO
            lifecycle_rules=[
                s3.LifecycleRule(
                    id="InfrequentAccess",
                    transitions=[
                        s3.Transition(
                            storage_class=s3.StorageClass.INFREQUENT_ACCESS,
                            transition_after=Duration.days(60),
                        )
                    ]
                ),
                s3.LifecycleRule(
                    id="DeepArchive",
                    transitions=[
                        s3.Transition(
                            storage_class=s3.StorageClass.DEEP_ARCHIVE,
                            transition_after=Duration.days(60),
                        )
                    ]
                )
            ],
            encryption=s3.BucketEncryption.KMS,
            encryption_key=kms_key,
            bucket_key_enabled=True,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
        )
        ssm.StringParameter(self, "rS3AccessLogsBucketSsm",
            description="S3 Access Logs Bucket",
            parameter_name="/SDLF/S3/AccessLogsBucket",
            string_value=access_logs_bucket.bucket_name,
        )

        artifacts_bucket_name = f"{p_org.value_as_string}-{p_domain.value_as_string}-{p_environment.value_as_string}-{self.region}-{self.account}-artifacts"
        artifacts_bucket = s3.Bucket(self, "rArtifactsBucket",
            bucket_name=artifacts_bucket_name, # TODO
            server_access_logs_bucket=access_logs_bucket, # automatically add policy statement to access logs bucket policy
            server_access_logs_prefix=artifacts_bucket_name,
            encryption=s3.BucketEncryption.KMS,
            encryption_key=kms_key,
            bucket_key_enabled=True,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
        )
        ssm.StringParameter(self, "rS3ArtifactBucketSsm",
            description="Name of the Artifacts S3 bucket",
            parameter_name="/SDLF/S3/ArtifactsBucket",
            string_value=artifacts_bucket.bucket_name,
        )

        raw_bucket_name = f"{p_org.value_as_string}-{p_domain.value_as_string}-{p_environment.value_as_string}-{self.region}-{self.account}-raw"
        raw_bucket = s3.Bucket(self, "rRawBucket",
            bucket_name=raw_bucket_name, # TODO
            server_access_logs_bucket=access_logs_bucket,
            server_access_logs_prefix=raw_bucket_name,
            encryption=s3.BucketEncryption.KMS,
            encryption_key=kms_key,
            bucket_key_enabled=True,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            versioned=True,
            event_bridge_enabled=True,
        )
        lakeformation.CfnResource(self, "rRawBucketLakeFormationS3Registration",
            resource_arn=f"{raw_bucket.bucket_arn}/", # the trailing slash is important to Lake Formation somehow
            use_service_linked_role=False,
            role_arn=lakeformationdataaccess_role.role_arn,
        )
        ssm.StringParameter(self, "rS3RawBucketSsm",
            description="Name of the Raw S3 bucket",
            parameter_name="/SDLF/S3/RawBucket",
            string_value=raw_bucket.bucket_name,
        )
        ssm.StringParameter(self, "rS3CentralBucketSsm",
            description="Name of the Central S3 bucket (deprecrated, use /SDLF/S3/RawBucket instead)",
            parameter_name="/SDLF/S3/CentralBucket",
            string_value=raw_bucket.bucket_name,
        )

        stage_bucket_name = f"{p_org.value_as_string}-{p_domain.value_as_string}-{p_environment.value_as_string}-{self.region}-{self.account}-stage"
        stage_bucket = s3.Bucket(self, "rStageBucket",
            bucket_name=stage_bucket_name, # TODO
            server_access_logs_bucket=access_logs_bucket,
            server_access_logs_prefix=stage_bucket_name,
            encryption=s3.BucketEncryption.KMS,
            encryption_key=kms_key,
            bucket_key_enabled=True,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            versioned=True,
            event_bridge_enabled=True,
        )
        lakeformation.CfnResource(self, "rStageBucketLakeFormationS3Registration",
            resource_arn=f"{stage_bucket.bucket_arn}/", # the trailing slash is important to Lake Formation somehow
            use_service_linked_role=False,
            role_arn=lakeformationdataaccess_role.role_arn,
        )
        ssm.StringParameter(self, "rS3StageBucketSsm",
            description="Name of the Stage S3 bucket",
            parameter_name="/SDLF/S3/StageBucket",
            string_value=stage_bucket.bucket_name,
        )

        analytics_bucket_name = f"{p_org.value_as_string}-{p_domain.value_as_string}-{p_environment.value_as_string}-{self.region}-{self.account}-analytics"
        analytics_bucket = s3.Bucket(self, "rAnalyticsBucket",
            bucket_name=analytics_bucket_name, # TODO
            server_access_logs_bucket=access_logs_bucket,
            server_access_logs_prefix=analytics_bucket_name,
            encryption=s3.BucketEncryption.KMS,
            encryption_key=kms_key,
            bucket_key_enabled=True,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            versioned=True,
            event_bridge_enabled=True,
        )
        lakeformation.CfnResource(self, "rAnalyticsBucketLakeFormationS3Registration",
            resource_arn=f"{analytics_bucket.bucket_arn}/", # the trailing slash is important to Lake Formation somehow
            use_service_linked_role=False,
            role_arn=lakeformationdataaccess_role.role_arn,
        )
        ssm.StringParameter(self, "rS3AnalyticsBucketSsm",
            description="Name of the Analytics S3 bucket",
            parameter_name="/SDLF/S3/AnalyticsBucket",
            string_value=analytics_bucket.bucket_name,
        )

        athena_bucket_name = f"{p_org.value_as_string}-{p_domain.value_as_string}-{p_environment.value_as_string}-{self.region}-{self.account}-athena"
        athena_bucket = s3.Bucket(self, "rAthenaBucket",
            bucket_name=athena_bucket_name, # TODO
            server_access_logs_bucket=access_logs_bucket,
            server_access_logs_prefix=athena_bucket_name,
            encryption=s3.BucketEncryption.KMS,
            encryption_key=kms_key,
            bucket_key_enabled=True,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            versioned=True,
            event_bridge_enabled=True,
        )
        ssm.StringParameter(self, "rS3AthenaBucketSsm",
            description="Name of the Athena results S3 bucket",
            parameter_name="/SDLF/S3/AthenaBucket",
            string_value=athena_bucket.bucket_name,
        )

        s3_lakeformationdataaccess_role_policy = iam.Policy(self, "sdlf-lakeformation",
            statements=[
                iam.PolicyStatement(
                    actions=[
                        "s3:GetObject*",
                        "s3:GetBucket*",
                        "s3:List*",
                        "s3:DeleteObject*",
                        "s3:PutObject",
                        "s3:PutObjectLegalHold",
                        "s3:PutObjectRetention",
                        "s3:PutObjectTagging",
                        "s3:PutObjectVersionTagging",
                        "s3:Abort*",
                    ],
                    resources=[
                        raw_bucket.bucket_arn,
                        stage_bucket.bucket_arn,
                        analytics_bucket.bucket_arn,
                        f"{raw_bucket.bucket_arn}/*",
                        f"{stage_bucket.bucket_arn}/*",
                        f"{analytics_bucket.bucket_arn}/*"
                    ]
                ),
                iam.PolicyStatement(
                    actions=[
                        "kms:Encrypt*",
                        "kms:Decrypt*",
                        "kms:ReEncrypt*",
                        "kms:GenerateDataKey*",
                        "kms:Describe*",
                    ],
                    resources=["*"],
                    conditions={ "ForAnyValue:StringLike": {"kms:ResourceAliases": ["alias/sdlf-kms-key", "alias/sdlf-*-kms-data-key"]} }
                ),
            ]
        )
        lakeformationdataaccess_role.attach_inline_policy(s3_lakeformationdataaccess_role_policy)

        ######## Lambda & SQS #########
        catalog_dlq = sqs.Queue(self, "rDeadLetterQueueCatalog",
            queue_name="sdlf-catalog-dlq",
            retention_period=Duration.days(14),
            visibility_timeout=Duration.seconds(60),
            encryption_master_key=kms_key,
        )

        catalog_queue = sqs.Queue(self, "rQueueCatalog",
            queue_name="sdlf-catalog-queue",
            retention_period=Duration.days(7),
            visibility_timeout=Duration.seconds(60),
            encryption_master_key=kms_key,
            dead_letter_queue=sqs.DeadLetterQueue(
                max_receive_count=1,
                queue=catalog_dlq,
            )
        )

        s3_object_events_rule = events.Rule(self, "rS3ObjectTriggerRule",
            event_pattern=events.EventPattern(
                source=["aws.s3"],
                detail_type=["Object Created", "Object Deleted"],
                detail={
                    "bucket": {
                        "name": [
                            raw_bucket.bucket_name,
                            stage_bucket.bucket_name,
                            analytics_bucket.bucket_name,
                        ]
                    }
                }
            ),
            targets=[
                targets.SqsQueue(
                    catalog_queue,
                    dead_letter_queue=catalog_dlq,
                    retry_attempts=3,
                    max_event_age=Duration.seconds(600),
                )
            ]
        )

        catalog_queue_policy = iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            principals=[
                iam.ServicePrincipal("events.amazonaws.com"),
            ],
            actions=["SQS:SendMessage"],
            resources=[catalog_queue.queue_arn],
            conditions={"ArnEquals": {"aws:SourceArn": s3_object_events_rule.rule_arn}}
        )
        catalog_queue.add_to_resource_policy(catalog_queue_policy) # TODO may be a cdk grant

        lambdaexecution_role_policy = iam.Policy(self, "sdlf-catalog",
            statements=[
                iam.PolicyStatement(
                    actions=["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
                    resources=[
                        self.format_arn(
                            service="logs",
                            resource="log-group",
                            arn_format=ArnFormat.COLON_RESOURCE_NAME,
                            resource_name="/aws/lambda/sdlf-catalog*"
                        )
                    ]
                ),
                iam.PolicyStatement(
                    actions=[
                        "sqs:DeleteMessage",
                        "sqs:GetQueueAttributes",
                        "sqs:GetQueueUrl",
                        "sqs:ListQueues",
                        "sqs:ListDeadLetterSourceQueues",
                        "sqs:ListQueueTags",
                        "sqs:ReceiveMessage",
                        "sqs:SendMessage",
                    ],
                    resources=[
                        catalog_queue.queue_arn,
                        catalog_dlq.queue_arn,
                    ]
                ),
                iam.PolicyStatement(
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
                        "dynamodb:UpdateItem"
                    ],
                    resources=[
                        self.format_arn(
                            service="dynamodb",
                            resource="table",
                            arn_format=ArnFormat.SLASH_RESOURCE_NAME,
                            resource_name="octagon-*"
                        )
                    ]
                ),
                iam.PolicyStatement(
                    actions=[
                        "kms:CreateGrant",
                        "kms:Decrypt",
                        "kms:DescribeKey",
                        "kms:Encrypt",
                        "kms:GenerateDataKey*",
                        "kms:ReEncrypt*",
                    ],
                    resources=[
                        kms_key.key_arn
                    ]
                ),
                iam.PolicyStatement(
                    actions=[
                        "ssm:GetParameter",
                        "ssm:GetParameters",
                    ],
                    resources=[
                        self.format_arn(
                            service="ssm",
                            resource="parameter",
                            arn_format=ArnFormat.SLASH_RESOURCE_NAME,
                            resource_name="/SDLF/EventBridge/*"
                        ),
                    ]
                )
            ]
        )

        lambdaexecution_role = iam.Role(self, "rRoleLambdaExecution",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
        )
        lambdaexecution_role.attach_inline_policy(lambdaexecution_role_policy)

        catalog_function = _lambda.Function(self, "rLambdaCatalog",
            runtime = _lambda.Runtime.PYTHON_3_12,
            code = _lambda.Code.from_asset(os.path.join(dirname, "lambda/catalog/src")),
            handler = "lambda_function.lambda_handler",
            function_name="sdlf-catalog",
            description="Catalogs S3 Put and Delete to ObjectMetaDataCatalog",
            memory_size=256,
            timeout=Duration.seconds(60),
            role=lambdaexecution_role,
            environment={
                "ENV": p_environment.value_as_string
            },
            environment_encryption=kms_key
            # vpcconfig TODO
        )

        catalog_redrive_function = _lambda.Function(self, "rLambdaCatalogRedrive",
            runtime = _lambda.Runtime.PYTHON_3_12,
            code = _lambda.Code.from_asset(os.path.join(dirname, "lambda/catalog-redrive/src")),
            handler = "lambda_function.lambda_handler",
            function_name="sdlf-catalog-redrive",
            description="Redrives Failed S3 Put/Delete to Catalog Lambda",
            memory_size=256,
            timeout=Duration.seconds(60),
            role=lambdaexecution_role,
            environment={
                "QUEUE": catalog_queue.queue_name,
                "DLQ": catalog_dlq.queue_name
            },
            environment_encryption=kms_key
            # vpcconfig TODO
        )
        logs.LogGroup(self, "rLambdaCatalogRedriveLogGroup",
            log_group_name=f"/aws/lambda/{catalog_redrive_function.function_name}",
            retention=logs.RetentionDays.ONE_MONTH,
#            retention=Duration.days(p_cloudwatchlogsretentionindays.value_as_number),
            encryption_key=kms_key
        )

        catalog_function.add_event_source(eventsources.SqsEventSource(catalog_queue, batch_size=10))


        ######## DYNAMODB #########
        objectmetadata_table = ddb.Table(self, "rDynamoOctagonObjectMetadata",
            partition_key=ddb.Attribute(
                name="id",
                type=ddb.AttributeType.STRING,
            ),
            billing_mode=ddb.BillingMode.PAY_PER_REQUEST,
            table_name=f"octagon-ObjectMetadata-{p_environment.value_as_string}",
            stream=ddb.StreamViewType.NEW_AND_OLD_IMAGES,
            encryption=ddb.TableEncryption.CUSTOMER_MANAGED,
            encryption_key=kms_key,
            point_in_time_recovery= True,
        )
        ssm.StringParameter(self, "rDynamoObjectMetadataSsm",
            description="Name of the DynamoDB used to store metadata",
            parameter_name="/SDLF/Dynamo/ObjectCatalog",
            string_value=objectmetadata_table.table_name,
        )

        datasets_table = ddb.Table(self, "rDynamoOctagonDatasets",
            partition_key=ddb.Attribute(
                name="name",
                type=ddb.AttributeType.STRING,
            ),
            billing_mode=ddb.BillingMode.PAY_PER_REQUEST,
            table_name=f"octagon-Datasets-{p_environment.value_as_string}",
            encryption=ddb.TableEncryption.CUSTOMER_MANAGED,
            encryption_key=kms_key,
            point_in_time_recovery= True,
        )
        ssm.StringParameter(self, "rDynamoTransformMappingSsm",
            description="Name of the DynamoDB used to store mappings to transformation (same as /SDLF/Dynamo/Datasets)",
            parameter_name="/SDLF/Dynamo/TransformMapping",
            string_value=datasets_table.table_name,
        )
        ssm.StringParameter(self, "rDynamoDatasetsSsm",
            description="Name of the DynamoDB used to store datasets metadata",
            parameter_name="/SDLF/Dynamo/Datasets",
            string_value=datasets_table.table_name,
        )

        artifacts_table = ddb.Table(self, "rDynamoOctagonArtifacts",
            partition_key=ddb.Attribute(
                name="id",
                type=ddb.AttributeType.STRING,
            ),
            billing_mode=ddb.BillingMode.PAY_PER_REQUEST,
            table_name=f"octagon-Artifacts-{p_environment.value_as_string}",
            encryption=ddb.TableEncryption.CUSTOMER_MANAGED,
            encryption_key=kms_key,
            point_in_time_recovery= True,
            time_to_live_attribute="ttl",
        )
        artifacts_table.add_global_secondary_index(
            index_name="date-pipeline-artifact-type-index",
            partition_key=ddb.Attribute(
                name="date",
                type=ddb.AttributeType.STRING,
            ),
            sort_key=ddb.Attribute(
                name="pipeline_and_target_type",
                type=ddb.AttributeType.STRING,
            ),
            projection_type=ddb.ProjectionType.ALL,
        )
        artifacts_table.add_global_secondary_index(
            index_name="dataset-date-index",
            partition_key=ddb.Attribute(
                name="dataset",
                type=ddb.AttributeType.STRING,
            ),
            sort_key=ddb.Attribute(
                name="date",
                type=ddb.AttributeType.STRING,
            ),
            projection_type=ddb.ProjectionType.ALL,
        )
        artifacts_table.add_global_secondary_index(
            index_name="date-dataset-index",
            partition_key=ddb.Attribute(
                name="date",
                type=ddb.AttributeType.STRING,
            ),
            sort_key=ddb.Attribute(
                name="dataset",
                type=ddb.AttributeType.STRING,
            ),
            projection_type=ddb.ProjectionType.ALL,
        )
        artifacts_table.add_global_secondary_index(
            index_name="pipeline-date-index",
            partition_key=ddb.Attribute(
                name="pipeline",
                type=ddb.AttributeType.STRING,
            ),
            sort_key=ddb.Attribute(
                name="date",
                type=ddb.AttributeType.STRING,
            ),
            projection_type=ddb.ProjectionType.ALL,
        )
        artifacts_table.add_global_secondary_index(
            index_name="pipelineSessionId-index",
            partition_key=ddb.Attribute(
                name="pipelineSessionId",
                type=ddb.AttributeType.STRING,
            ),
            projection_type=ddb.ProjectionType.ALL,
        )

        metrics_table = ddb.Table(self, "rDynamoOctagonMetrics",
            partition_key=ddb.Attribute(
                name="root",
                type=ddb.AttributeType.STRING,
            ),
            sort_key=ddb.Attribute(
                name="metric",
                type=ddb.AttributeType.STRING,
            ),
            billing_mode=ddb.BillingMode.PAY_PER_REQUEST,
            table_name=f"octagon-Metrics-{p_environment.value_as_string}",
            encryption=ddb.TableEncryption.CUSTOMER_MANAGED,
            encryption_key=kms_key,
            point_in_time_recovery= True,
            time_to_live_attribute="ttl",
        )
        metrics_table.add_global_secondary_index(
            index_name="last_updated_date-metric-index",
            partition_key=ddb.Attribute(
                name="last_updated_date",
                type=ddb.AttributeType.STRING,
            ),
            sort_key=ddb.Attribute(
                name="metric",
                type=ddb.AttributeType.STRING,
            ),
            projection_type=ddb.ProjectionType.ALL,
        )
        metrics_table.add_global_secondary_index(
            index_name="type-metric-index",
            partition_key=ddb.Attribute(
                name="type",
                type=ddb.AttributeType.STRING,
            ),
            sort_key=ddb.Attribute(
                name="metric",
                type=ddb.AttributeType.STRING,
            ),
            projection_type=ddb.ProjectionType.ALL,
        )
        metrics_table.add_global_secondary_index(
            index_name="root-last_updated_date-index",
            partition_key=ddb.Attribute(
                name="root",
                type=ddb.AttributeType.STRING,
            ),
            sort_key=ddb.Attribute(
                name="last_updated_date",
                type=ddb.AttributeType.STRING,
            ),
            projection_type=ddb.ProjectionType.ALL,
        )

        configuration_table = ddb.Table(self, "rDynamoOctagonConfiguration",
            partition_key=ddb.Attribute(
                name="key",
                type=ddb.AttributeType.STRING,
            ),
            billing_mode=ddb.BillingMode.PAY_PER_REQUEST,
            table_name=f"octagon-Configuration-{p_environment.value_as_string}",
            encryption=ddb.TableEncryption.CUSTOMER_MANAGED,
            encryption_key=kms_key,
            point_in_time_recovery= True,
        )
        configuration_table.add_global_secondary_index(
            index_name="type-index",
            partition_key=ddb.Attribute(
                name="type",
                type=ddb.AttributeType.STRING,
            ),
            projection_type=ddb.ProjectionType.ALL,
        )

        teams_table = ddb.Table(self, "rDynamoOctagonTeams",
            partition_key=ddb.Attribute(
                name="team",
                type=ddb.AttributeType.STRING,
            ),
            billing_mode=ddb.BillingMode.PAY_PER_REQUEST,
            table_name=f"octagon-Teams-{p_environment.value_as_string}",
            encryption=ddb.TableEncryption.CUSTOMER_MANAGED,
            encryption_key=kms_key,
            point_in_time_recovery= True,
        )
        ssm.StringParameter(self, "rDynamoTeamMetadataSsm",
            description="Name of the DynamoDB used to store teams metadata",
            parameter_name="/SDLF/Dynamo/TeamMetadata",
            string_value=teams_table.table_name,
        )

        pipelines_table = ddb.Table(self, "rDynamoOctagonPipelines",
            partition_key=ddb.Attribute(
                name="name",
                type=ddb.AttributeType.STRING,
            ),
            billing_mode=ddb.BillingMode.PAY_PER_REQUEST,
            table_name=f"octagon-Pipelines-{p_environment.value_as_string}",
            encryption=ddb.TableEncryption.CUSTOMER_MANAGED,
            encryption_key=kms_key,
            point_in_time_recovery= True,
        )
        ssm.StringParameter(self, "rDynamoPipelinesSsm",
            description="Name of the DynamoDB used to store pipelines metadata",
            parameter_name="/SDLF/Dynamo/Pipelines",
            string_value=pipelines_table.table_name,
        )

        events_table = ddb.Table(self, "rDynamoOctagonEvents",
            partition_key=ddb.Attribute(
                name="id",
                type=ddb.AttributeType.STRING,
            ),
            billing_mode=ddb.BillingMode.PAY_PER_REQUEST,
            table_name=f"octagon-Events-{p_environment.value_as_string}",
            encryption=ddb.TableEncryption.CUSTOMER_MANAGED,
            encryption_key=kms_key,
            point_in_time_recovery= True,
            time_to_live_attribute="ttl",
        )
        events_table.add_global_secondary_index(
            index_name="date-reason-index",
            partition_key=ddb.Attribute(
                name="date",
                type=ddb.AttributeType.STRING,
            ),
            sort_key=ddb.Attribute(
                name="reason",
                type=ddb.AttributeType.STRING,
            ),
            projection_type=ddb.ProjectionType.ALL,
        )
        events_table.add_global_secondary_index(
            index_name="pipeline-date_reason-index",
            partition_key=ddb.Attribute(
                name="pipeline",
                type=ddb.AttributeType.STRING,
            ),
            sort_key=ddb.Attribute(
                name="date_and_reason",
                type=ddb.AttributeType.STRING,
            ),
            projection_type=ddb.ProjectionType.ALL,
        )
        events_table.add_global_secondary_index(
            index_name="reason-date-index",
            partition_key=ddb.Attribute(
                name="reason",
                type=ddb.AttributeType.STRING,
            ),
            sort_key=ddb.Attribute(
                name="date",
                type=ddb.AttributeType.STRING,
            ),
            projection_type=ddb.ProjectionType.ALL,
        )

        peh_table = ddb.Table(self, "rDynamoOctagonExecutionHistory",
            partition_key=ddb.Attribute(
                name="id",
                type=ddb.AttributeType.STRING,
            ),
            billing_mode=ddb.BillingMode.PAY_PER_REQUEST,
            table_name=f"octagon-PipelineExecutionHistory-{p_environment.value_as_string}",
            encryption=ddb.TableEncryption.CUSTOMER_MANAGED,
            encryption_key=kms_key,
            point_in_time_recovery= True,
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

        schemas_table = ddb.Table(self, "rDynamoOctagonSchemas",
            partition_key=ddb.Attribute(
                name="name",
                type=ddb.AttributeType.STRING,
            ),
            billing_mode=ddb.BillingMode.PAY_PER_REQUEST,
            table_name=f"octagon-DataSchemas-{p_environment.value_as_string}",
            stream=ddb.StreamViewType.NEW_AND_OLD_IMAGES,
            encryption=ddb.TableEncryption.CUSTOMER_MANAGED,
            encryption_key=kms_key,
            point_in_time_recovery= True,
        )
        ssm.StringParameter(self, "rDynamoDataSchemasSsm",
            description="Name of the DynamoDB used to store data schemas",
            parameter_name="/SDLF/Dynamo/DataSchemas",
            string_value=schemas_table.table_name,
        )

        manifests_table = ddb.Table(self, "rDynamoOctagonManifests",
            partition_key=ddb.Attribute(
                name="dataset_name",
                type=ddb.AttributeType.STRING,
            ),
            sort_key=ddb.Attribute(
                name="datafile_name",
                type=ddb.AttributeType.STRING,
            ),
            billing_mode=ddb.BillingMode.PAY_PER_REQUEST,
            table_name=f"octagon-Manifests-{p_environment.value_as_string}",
            encryption=ddb.TableEncryption.CUSTOMER_MANAGED,
            encryption_key=kms_key,
            point_in_time_recovery= True,
            time_to_live_attribute="ttl",
        )
        ssm.StringParameter(self, "rDynamoManifestsSsm",
            description="Name of the DynamoDB used to store manifest process metadata",
            parameter_name="/SDLF/Dynamo/Manifests",
            string_value=manifests_table.table_name,
        )

        ######## GLUE REPLICATION #########
        ######## LAMBDA #########
        replicate_function = _lambda.Function(self, "rLambdaReplicate",
            runtime = _lambda.Runtime.PYTHON_3_12,
            code = _lambda.Code.from_asset(os.path.join(dirname, "lambda/replicate/src")),
            handler = "lambda_function.lambda_handler",
            function_name="sdlf-glue-replication",
            description="Replicates Glue Catalog Metadata and Data Quality to Octagon Schemas Table",
            memory_size=128,
            timeout=Duration.seconds(300),
            role=datalakeadmin_role,
            environment={
                "ENV": p_environment.value_as_string
            },
            environment_encryption=kms_key
            # vpcconfig TODO
        )

        logs.LogGroup(self, "rLambdaReplicateLogGroup",
            log_group_name=f"/aws/lambda/{replicate_function.function_name}",
            retention=logs.RetentionDays.ONE_MONTH,
#            retention=Duration.days(p_cloudwatchlogsretentionindays.value_as_number), # TODO
            encryption_key=kms_key
        )

        gluecatalog_events_rule = events.Rule(self, "rLambdaEventsRule",
            event_pattern=events.EventPattern(
                source=["aws.glue"],
                detail_type=["Glue Data Catalog Database State Change", "Glue Data Catalog Table State Change"],
            ),
            targets=[
                targets.LambdaFunction(
                    replicate_function,
                ) # AWS::Lambda::Permission is added automatically
            ]
        )

        # CloudFormation Outputs TODO
        CfnOutput(self, "oPipelineReference",
            description="CodePipeline reference this stack has been deployed with",
            value=p_pipelinereference.value_as_string
        )
        CfnOutput(self, "oChildAccountId",
            description="Child AWS account ID",
            value=p_childaccountid.value_as_string
        )
        CfnOutput(self, "oS3ArtifactsBucket",
            description="Name of the domain's Artifacts S3 bucket",
            value=artifacts_bucket.bucket_name
        )
