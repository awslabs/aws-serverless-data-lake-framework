# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT

import os.path

from aws_cdk import (
    ArnFormat,
    CfnOutput,
    CfnParameter,
    Duration,
    RemovalPolicy,
)
from aws_cdk import aws_dynamodb as ddb
from aws_cdk import aws_events as events
from aws_cdk import aws_events_targets as targets
from aws_cdk import aws_iam as iam
from aws_cdk import aws_kms as kms
from aws_cdk import aws_lakeformation as lakeformation
from aws_cdk import aws_lambda as _lambda
from aws_cdk import aws_lambda_event_sources as eventsources
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_sqs as sqs
from aws_cdk import aws_ssm as ssm
from constructs import Construct


class Foundations(Construct):
    external_interface = {}

    def __init__(self, scope: Construct, id: str, org: str, data_domain: str, account_id: str, **kwargs) -> None:
        super().__init__(scope, id)

        dirname = os.path.dirname(__file__)
        # run_in_vpc = False TODO

        # using context values would be better(?) for CDK but we haven't decided yet what the story is around ServiceCatalog and CloudFormation modules
        # perhaps both (context values feeding into CfnParameter) would be a nice-enough solution. Not sure though. TODO
        p_pipelinereference = CfnParameter(
            self,
            "pPipelineReference",
            type="String",
            default="none",
        )
        p_pipelinereference.override_logical_id("pPipelineReference")
        p_childaccountid = CfnParameter(
            self,
            "pChildAccountId",
            description="Child AWS account ID",
            type="String",
            allowed_pattern="(\\d{12}|^$)",
            constraint_description="Must be an AWS account ID",
            default=str(account_id),
        )
        p_childaccountid.override_logical_id("pChildAccountId")
        p_org = CfnParameter(
            self,
            "pOrg",
            description="Name of the organization owning the datalake (all lowercase, no symbols or spaces)",
            type="String",
            allowed_pattern="[a-z0-9]{2,9}",
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
        # p_cloudwatchlogsretentionindays = CfnParameter(self, "pCloudWatchLogsRetentionInDays",
        #     description="The number of days log events are kept in CloudWatch Logs",
        #     type="Number",
        #     allowed_values=[1, 3, 5, 7, 14, 30, 60, 90, 120, 150, 180, 365, 400, 545, 731, 1827, 3653],
        #     default=30,
        # )

        self._external_interface("rOrganization", "Name of the Organization owning the datalake", p_org.value_as_string)
        self._external_interface("rDomain", "Data domain name", p_domain.value_as_string)

        ######## LAKE FORMATION #########
        lakeformation.CfnDataLakeSettings(
            self,
            "rDataLakeSettings",
            create_database_default_permissions=[],
            create_table_default_permissions=[],
            mutation_type="APPEND",
        )

        # https://docs.aws.amazon.com/lake-formation/latest/dg/registration-role.html
        lakeformationdataaccess_role_policy = iam.Policy(
            self,
            "CloudWatchLogs",
            statements=[
                iam.PolicyStatement(
                    actions=["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
                    resources=[
                        scope.format_arn(
                            service="logs",
                            resource="log-group",
                            arn_format=ArnFormat.COLON_RESOURCE_NAME,
                            resource_name="/aws-lakeformation-acceleration/*",
                        ),
                        scope.format_arn(
                            service="logs",
                            resource="log-group",
                            arn_format=ArnFormat.COLON_RESOURCE_NAME,
                            resource_name="/aws-lakeformation-acceleration/*:log-stream:*",
                        ),
                    ],
                ),
            ],
        )

        lakeformationdataaccess_role_resource_name = "rLakeFormationDataAccessRole"
        self.lakeformationdataaccess_role = iam.Role(
            self,
            lakeformationdataaccess_role_resource_name,
            assumed_by=iam.CompositePrincipal(
                iam.ServicePrincipal("lakeformation.amazonaws.com"),
                iam.ServicePrincipal("glue.amazonaws.com"),
            ),
        )
        self.lakeformationdataaccess_role.attach_inline_policy(lakeformationdataaccess_role_policy)

        self._external_interface(
            f"{lakeformationdataaccess_role_resource_name}Arn",
            "Lake Formation Data Access Role",
            self.lakeformationdataaccess_role.role_arn,
        )
        self._external_interface(
            lakeformationdataaccess_role_resource_name,
            "Lake Formation Data Access Role",
            self.lakeformationdataaccess_role.role_name,
        )

        ######## KMS #########
        kms_key_policy = iam.PolicyDocument(
            statements=[
                iam.PolicyStatement(
                    sid="Allow administration of the key",
                    effect=iam.Effect.ALLOW,
                    principals=[iam.AccountRootPrincipal()],
                    actions=["kms:*"],
                    resources=["*"],
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
                iam.PolicyStatement(
                    sid="Allow S3 Events access",
                    effect=iam.Effect.ALLOW,
                    principals=[
                        iam.ServicePrincipal("s3.amazonaws.com"),
                    ],
                    actions=["kms:Decrypt", "kms:GenerateDataKey*"],
                    resources=["*"],
                ),
                iam.PolicyStatement(
                    sid="Allow DynamoDB access",
                    effect=iam.Effect.ALLOW,
                    principals=[iam.AnyPrincipal()],
                    actions=[
                        "kms:CreateGrant",
                        "kms:Decrypt",
                        "kms:DescribeKey",
                        "kms:Encrypt",
                        "kms:GenerateDataKey*",
                        "kms:ReEncrypt*",
                    ],
                    resources=["*"],
                    conditions={
                        "StringEquals": {
                            "kms:CallerAccount": scope.account,
                            "kms:ViaService": f"dynamodb.{scope.region}.amazonaws.com",
                        }
                    },
                ),
                iam.PolicyStatement(
                    sid="Allow ElasticSearch access",
                    effect=iam.Effect.ALLOW,
                    principals=[iam.AnyPrincipal()],
                    actions=[
                        "kms:CreateGrant",
                        "kms:Decrypt",
                        "kms:DescribeKey",
                        "kms:Encrypt",
                        "kms:GenerateDataKey*",
                        "kms:ReEncrypt*",
                    ],
                    resources=["*"],
                    conditions={
                        "StringEquals": {
                            "kms:CallerAccount": scope.account,
                            "kms:ViaService": f"es.{scope.region}.amazonaws.com",
                        },
                        "Bool": {"kms:GrantIsForAWSResource": "true"},
                    },
                ),
                iam.PolicyStatement(
                    sid="Allow LakeFormation access",
                    effect=iam.Effect.ALLOW,
                    principals=[
                        iam.ArnPrincipal(self.lakeformationdataaccess_role.role_arn),
                    ],
                    actions=["kms:Encrypt*", "kms:Decrypt*", "kms:ReEncrypt*", "kms:GenerateDataKey*", "kms:Describe*"],
                    resources=["*"],
                ),
            ]
        )

        kms_key_resource_name = "rKMSKey"
        self.kms_key = kms.Key(
            self,
            kms_key_resource_name,
            removal_policy=RemovalPolicy.RETAIN_ON_UPDATE_OR_DELETE,
            description="SDLF Foundations KMS Key",
            enable_key_rotation=True,
            policy=kms_key_policy,
        )
        self.kms_key.add_alias("alias/sdlf-kms-key").apply_removal_policy(RemovalPolicy.RETAIN_ON_UPDATE_OR_DELETE)

        self._external_interface(kms_key_resource_name, "ARN of the KMS key", self.kms_key.key_arn)

        ######## S3 #########
        ####### Access Logging Bucket ######
        access_logs_bucket_name = (
            f"{p_org.value_as_string}-{p_domain.value_as_string}-{scope.region}-{scope.account}-s3logs"
        )
        access_logs_bucket_resource_name = "rS3AccessLogsBucket"
        self.access_logs_bucket = s3.Bucket(
            self,
            access_logs_bucket_resource_name,
            bucket_name=access_logs_bucket_name,  # TODO
            lifecycle_rules=[
                s3.LifecycleRule(
                    id="InfrequentAccess",
                    transitions=[
                        s3.Transition(
                            storage_class=s3.StorageClass.INFREQUENT_ACCESS,
                            transition_after=Duration.days(60),
                        )
                    ],
                ),
                s3.LifecycleRule(
                    id="DeepArchive",
                    transitions=[
                        s3.Transition(
                            storage_class=s3.StorageClass.DEEP_ARCHIVE,
                            transition_after=Duration.days(60),
                        )
                    ],
                ),
            ],
            encryption=s3.BucketEncryption.KMS,
            encryption_key=self.kms_key,
            bucket_key_enabled=True,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
        )

        self._external_interface(
            access_logs_bucket_resource_name, "S3 Access Logs Bucket", self.access_logs_bucket.bucket_name
        )

        artifacts_bucket_name = (
            f"{p_org.value_as_string}-{p_domain.value_as_string}-{scope.region}-{scope.account}-artifacts"
        )
        artifacts_bucket_resource_name = "rArtifactsBucket"
        artifacts_bucket = s3.Bucket(
            self,
            artifacts_bucket_resource_name,
            bucket_name=artifacts_bucket_name,  # TODO
            server_access_logs_bucket=self.access_logs_bucket,  # automatically add policy statement to access logs bucket policy
            server_access_logs_prefix=artifacts_bucket_name,
            encryption=s3.BucketEncryption.KMS,
            encryption_key=self.kms_key,
            bucket_key_enabled=True,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
        )
        self._external_interface(
            artifacts_bucket_resource_name, "Name of the Artifacts S3 bucket", artifacts_bucket.bucket_name
        )

        raw_bucket = self.data_bucket(
            p_org.value_as_string,
            p_domain.value_as_string,
            scope.region,
            scope.account,
            "raw",
        )
        stage_bucket = self.data_bucket(
            p_org.value_as_string,
            p_domain.value_as_string,
            scope.region,
            scope.account,
            "stage",
        )
        analytics_bucket = self.data_bucket(
            p_org.value_as_string,
            p_domain.value_as_string,
            scope.region,
            scope.account,
            "analytics",
        )

        athena_bucket_name = f"{p_org.value_as_string}-{p_domain.value_as_string}-{scope.region}-{scope.account}-athena"
        athena_bucket_resource_name = "rAthenaBucket"
        athena_bucket = s3.Bucket(
            self,
            athena_bucket_resource_name,
            bucket_name=athena_bucket_name,  # TODO
            server_access_logs_bucket=self.access_logs_bucket,
            server_access_logs_prefix=athena_bucket_name,
            encryption=s3.BucketEncryption.KMS,
            encryption_key=self.kms_key,
            bucket_key_enabled=True,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            versioned=True,
            event_bridge_enabled=True,
        )
        self._external_interface(
            athena_bucket_resource_name, "Name of the Athena results S3 bucket", athena_bucket.bucket_name
        )

        s3_lakeformationdataaccess_role_policy = iam.Policy(
            self,
            "sdlf-lakeformation",
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
                        f"{analytics_bucket.bucket_arn}/*",
                    ],
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
                    conditions={
                        "ForAnyValue:StringLike": {
                            "kms:ResourceAliases": ["alias/sdlf-kms-key", "alias/sdlf-*-kms-data-key"]
                        }
                    },
                ),
            ],
        )
        self.lakeformationdataaccess_role.attach_inline_policy(s3_lakeformationdataaccess_role_policy)

        ######## DYNAMODB #########
        objectmetadata_table_resource_name = "rDynamoObjectMetadata"
        objectmetadata_table = ddb.Table(
            self,
            objectmetadata_table_resource_name,
            removal_policy=RemovalPolicy.DESTROY,
            partition_key=ddb.Attribute(
                name="id",
                type=ddb.AttributeType.STRING,
            ),
            billing_mode=ddb.BillingMode.PAY_PER_REQUEST,
            stream=ddb.StreamViewType.NEW_AND_OLD_IMAGES,
            encryption=ddb.TableEncryption.CUSTOMER_MANAGED,
            encryption_key=self.kms_key,
            point_in_time_recovery=True,
        )
        self._external_interface(
            objectmetadata_table_resource_name,
            "Name of the DynamoDB used to store metadata",
            objectmetadata_table.table_name,
        )

        ######## Lambda & SQS #########
        catalog_dlq = sqs.Queue(
            self,
            "rDeadLetterQueueCatalog",
            removal_policy=RemovalPolicy.DESTROY,
            queue_name="sdlf-catalog-dlq",
            retention_period=Duration.days(14),
            visibility_timeout=Duration.seconds(60),
            encryption_master_key=self.kms_key,
        )

        catalog_queue = sqs.Queue(
            self,
            "rQueueCatalog",
            removal_policy=RemovalPolicy.DESTROY,
            queue_name="sdlf-catalog-queue",
            retention_period=Duration.days(7),
            visibility_timeout=Duration.seconds(60),
            encryption_master_key=self.kms_key,
            dead_letter_queue=sqs.DeadLetterQueue(
                max_receive_count=1,
                queue=catalog_dlq,
            ),
        )

        s3_object_events_rule = events.Rule(
            self,
            "rS3ObjectTriggerRule",
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
                },
            ),
            targets=[
                targets.SqsQueue(
                    catalog_queue,
                    dead_letter_queue=catalog_dlq,
                    retry_attempts=3,
                    max_event_age=Duration.seconds(600),
                )
            ],
        )

        catalog_queue_policy = iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            principals=[
                iam.ServicePrincipal("events.amazonaws.com"),
            ],
            actions=["SQS:SendMessage"],
            resources=[catalog_queue.queue_arn],
            conditions={"ArnEquals": {"aws:SourceArn": s3_object_events_rule.rule_arn}},
        )
        catalog_queue.add_to_resource_policy(catalog_queue_policy)  # TODO may be a cdk grant

        lambdaexecution_role_policy = iam.Policy(
            self,
            "sdlf-catalog",
            statements=[
                iam.PolicyStatement(
                    actions=["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
                    resources=[
                        scope.format_arn(
                            service="logs",
                            resource="log-group",
                            arn_format=ArnFormat.COLON_RESOURCE_NAME,
                            resource_name="/aws/lambda/sdlf-catalog*",
                        )
                    ],
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
                    ],
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
                    actions=[
                        "kms:CreateGrant",
                        "kms:Decrypt",
                        "kms:DescribeKey",
                        "kms:Encrypt",
                        "kms:GenerateDataKey*",
                        "kms:ReEncrypt*",
                    ],
                    resources=[self.kms_key.key_arn],
                ),
            ],
        )

        lambdaexecution_role = iam.Role(
            self,
            "rRoleLambdaExecution",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
        )
        lambdaexecution_role.attach_inline_policy(lambdaexecution_role_policy)

        catalog_function = _lambda.Function(
            self,
            "rLambdaCatalog",
            runtime=_lambda.Runtime.PYTHON_3_12,
            code=_lambda.Code.from_asset(os.path.join(dirname, "lambda/catalog/src")),
            handler="lambda_function.lambda_handler",
            function_name="sdlf-catalog",
            description="Catalogs S3 Put and Delete to ObjectMetaDataCatalog",
            memory_size=256,
            timeout=Duration.seconds(60),
            role=lambdaexecution_role,
            environment={"OBJECTMETADATA_TABLE": objectmetadata_table.table_name},
            environment_encryption=self.kms_key,
            # vpcconfig TODO
        )

        catalog_redrive_function = _lambda.Function(
            self,
            "rLambdaCatalogRedrive",
            runtime=_lambda.Runtime.PYTHON_3_12,
            code=_lambda.Code.from_asset(os.path.join(dirname, "lambda/catalog-redrive/src")),
            handler="lambda_function.lambda_handler",
            function_name="sdlf-catalog-redrive",
            description="Redrives Failed S3 Put/Delete to Catalog Lambda",
            memory_size=256,
            timeout=Duration.seconds(60),
            role=lambdaexecution_role,
            environment={"QUEUE": catalog_queue.queue_name, "DLQ": catalog_dlq.queue_name},
            environment_encryption=self.kms_key,
            # vpcconfig TODO
        )
        logs.LogGroup(
            self,
            "rLambdaCatalogRedriveLogGroup",
            removal_policy=RemovalPolicy.DESTROY,
            log_group_name=f"/aws/lambda/{catalog_redrive_function.function_name}",
            retention=logs.RetentionDays.ONE_MONTH,
            #            retention=Duration.days(p_cloudwatchlogsretentionindays.value_as_number),
            encryption_key=self.kms_key,
        )

        catalog_function.add_event_source(eventsources.SqsEventSource(catalog_queue, batch_size=10))

        # CloudFormation Outputs TODO
        CfnOutput(
            self,
            "oPipelineReference",
            description="CodePipeline reference this stack has been deployed with",
            value=p_pipelinereference.value_as_string,
        )
        CfnOutput(self, "oChildAccountId", description="Child AWS account ID", value=p_childaccountid.value_as_string)
        CfnOutput(
            self,
            "oS3ArtifactsBucket",
            description="Name of the domain's Artifacts S3 bucket",
            value=artifacts_bucket.bucket_name,
        )

    def _external_interface(self, resource_name, description, value):
        ssm.StringParameter(
            self,
            f"{resource_name}Ssm",
            description=description,
            parameter_name=f"/sdlf/storage/{resource_name}",
            string_value=value,
        )
        self.external_interface[resource_name] = value

    def data_bucket(self, org, domain, region, account, bucket_layer):
        data_bucket_name = f"{org}-{domain}-{region}-{account}-{bucket_layer}"
        data_bucket_resource_name = f"r{bucket_layer.capitalize()}Bucket"
        data_bucket = s3.Bucket(
            self,
            data_bucket_resource_name,
            bucket_name=data_bucket_name,  # TODO cfn version supports custom prefix
            server_access_logs_bucket=self.access_logs_bucket,
            server_access_logs_prefix=data_bucket_name,
            encryption=s3.BucketEncryption.KMS,
            encryption_key=self.kms_key,
            bucket_key_enabled=True,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            versioned=True,
            event_bridge_enabled=True,
        )
        lakeformation.CfnResource(
            self,
            f"{data_bucket_resource_name}LakeFormationS3Registration",
            resource_arn=f"{data_bucket.bucket_arn}/",  # the trailing slash is important to Lake Formation somehow
            use_service_linked_role=False,
            role_arn=self.lakeformationdataaccess_role.role_arn,
        )
        self._external_interface(
            data_bucket_resource_name, f"Name of the {bucket_layer.capitalize()} S3 bucket", data_bucket.bucket_name
        )

        return data_bucket
