# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT

import os.path

from aws_cdk import (
    ArnFormat,
    # CfnParameter,
    Duration,
    RemovalPolicy,
)
from aws_cdk import aws_iam as iam
from aws_cdk import aws_kms as kms
from aws_cdk import aws_lambda as _lambda
from aws_cdk import aws_logs as logs
from aws_cdk import aws_ssm as ssm
from aws_cdk import aws_stepfunctions as sfn
from constructs import Construct

# from sdlf import pipeline
from pipeline import Pipeline


class StageLambda(Construct):
    external_interface = {}

    def __init__(
        self,
        scope: Construct,
        id: str,
        raw_bucket: str,
        stage_bucket: str,
        transform: str,
        dataset: str,
        pipeline: str,
        stage: str,
        trigger_type: str,
        event_pattern: str,
        org: str,
        data_domain: str,
        infra_kms_key: str,
        data_kms_key: str,
        event_bus: str = "default",
        schedule: str = None,  # only used if schedule or event-schedule
        stage_enabled: bool = True,
        xray_enabled: bool = False,
        # logs_retention =
        iam_prefix: str = "sdlf",
        **kwargs,
    ) -> None:
        super().__init__(scope, id)

        dirname = os.path.dirname(__file__)

        # the idea:
        # if you use pipeline independently,
        # then you need to provide a KMS key, and optionally an event bus and an event schedule
        # if you use sdlf-dataset,
        # you can provide storage_id as a storage id [or storage object] and in that case it will get data from ssm
        # can you still override stuff? I guess so?
        # the key can be provided by sdlf - but in that case dataset is mandatory. {/sdlf/dataset/rInfraKmsKey}
        # if you don't provide a key,
        # either...

        # if arguments are passed to the constructor, their values are fed to CfnParameter() below as default
        # if arguments aren't specified, standard SDLF SSM parameters are checked instead
        # the jury is still out on the usage of CfnParameter(),
        # and there is still work to get the latest SSM parameter values as well as using a prefix to allow multiple deployments TODO
        # trigger_type = trigger_type or "event"
        # schedule = schedule or "cron(*/5 * * * ? *)"
        # event_pattern = event_pattern or ""
        # org = org or "{{resolve:ssm:/sdlf/storage/rOrganization:1}}"
        # data_domain = data_domain or "{{resolve:ssm:/sdlf/storage/rDomain:1}}"

        # infra_kms_key = infra_kms_key or f"{{{{resolve:ssm:/sdlf/dataset/{dataset}/InfraKeyId}}}}"
        # data_kms_key = data_kms_key or f"{{{{resolve:ssm:/sdlf/dataset/{dataset}/DataKeyId}}}}"

        ######## IAM #########
        common_policy = iam.ManagedPolicy(
            self,
            "rLambdaCommonPolicy",
            statements=[
                iam.PolicyStatement(
                    actions=["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
                    resources=[
                        scope.format_arn(
                            service="logs",
                            resource="log-group",
                            arn_format=ArnFormat.COLON_RESOURCE_NAME,
                            resource_name=f"/aws/lambda/sdlf-{dataset}-{pipeline}-{stage}-*",
                        )
                    ],
                ),
                iam.PolicyStatement(
                    actions=["ssm:GetParameter", "ssm:GetParameters"],
                    resources=[
                        scope.format_arn(
                            service="ssm",
                            resource="parameter",
                            arn_format=ArnFormat.SLASH_RESOURCE_NAME,
                            resource_name="sdlf/*",
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
                    actions=[
                        "kms:DescribeKey",
                        "kms:Encrypt",
                        "kms:Decrypt",
                        "kms:ReEncrypt*",
                        "kms:GenerateDataKey*",
                        "kms:CreateGrant",
                    ],
                    resources=[infra_kms_key],
                ),
            ],
        )

        ######## LAMBDA FUNCTIONS #########
        datalakelibrary_layer = _lambda.LayerVersion.from_layer_version_arn(
            self,
            "rDatalakeLibraryLayer",
            ssm.StringParameter.value_from_lookup(self, "/SDLF/Lambda/LatestDatalakeLibraryLayer"),
        )

        transformstep_role_policy = iam.Policy(
            self,
            "rRoleLambdaExecutionProcessingStepPolicy",
            policy_name=f"sdlf-{dataset}-{pipeline}-{stage}-transform",
            statements=[
                iam.PolicyStatement(
                    actions=["s3:ListBucket", "s3:GetBucketVersioning"],
                    resources=[
                        scope.format_arn(
                            service="s3",
                            resource=raw_bucket,
                            region="",
                            account="",
                            arn_format=ArnFormat.NO_RESOURCE_NAME,
                        ),
                        scope.format_arn(
                            service="s3",
                            resource=stage_bucket,
                            region="",
                            account="",
                            arn_format=ArnFormat.NO_RESOURCE_NAME,
                        ),
                    ],
                ),
                iam.PolicyStatement(
                    actions=["s3:GetObject"],
                    resources=[
                        scope.format_arn(
                            service="s3",
                            resource=f"{raw_bucket}/{dataset}/*",
                            region="",
                            account="",
                            arn_format=ArnFormat.NO_RESOURCE_NAME,
                        ),
                        scope.format_arn(
                            service="s3",
                            resource=f"{stage_bucket}/{dataset}/*",
                            region="",
                            account="",
                            arn_format=ArnFormat.NO_RESOURCE_NAME,
                        ),
                    ],
                ),
                iam.PolicyStatement(
                    actions=["s3:PutObject"],
                    resources=[
                        scope.format_arn(
                            service="s3",
                            resource=f"{stage_bucket}/{dataset}/*",
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
                    resources=[data_kms_key],
                ),
            ],
        )

        transformstep_role = iam.Role(
            self,
            "rRoleLambdaExecutionProcessingStep",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            path=f"/sdlf-{dataset}/",
            # permissions_boundary=iam.ManagedPolicy.from_managed_policy_arn(
            #     self,
            #     "rRoleLambdaExecutionProcessingStepPermissionsBoundary",
            #     # managed_policy_arn=f"{{{{resolve:ssm:/SDLF/IAM/{dataset}/TeamPermissionsBoundary}}}}",
            # ),
        )
        transformstep_role.attach_inline_policy(transformstep_role_policy)
        transformstep_role.add_managed_policy(common_policy)

        # Metadata Step Role (fetch metadata, update pipeline execution history...)
        postmetadatastep_role_policy = iam.Policy(
            self,
            "rRoleLambdaExecutionMetadataStepPolicy",
            policy_name=f"sdlf-{dataset}-{pipeline}-{stage}-metadata",
            statements=[
                iam.PolicyStatement(
                    actions=["s3:ListBucket"],
                    resources=[
                        scope.format_arn(
                            service="s3",
                            resource=raw_bucket,
                            region="",
                            account="",
                            arn_format=ArnFormat.NO_RESOURCE_NAME,
                        ),
                        scope.format_arn(
                            service="s3",
                            resource=stage_bucket,
                            region="",
                            account="",
                            arn_format=ArnFormat.NO_RESOURCE_NAME,
                        ),
                    ],
                ),
                iam.PolicyStatement(
                    actions=["s3:GetObject"],
                    resources=[
                        scope.format_arn(
                            service="s3",
                            resource=f"{stage_bucket}/{dataset}/*",
                            region="",
                            account="",
                            arn_format=ArnFormat.NO_RESOURCE_NAME,
                        ),
                    ],
                ),
            ],
        )

        postmetadatastep_role = iam.Role(
            self,
            "rRoleLambdaExecutionMetadataStep",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            path=f"/sdlf-{dataset}/",
            # permissions_boundary=iam.ManagedPolicy.from_managed_policy_arn(
            #     self,
            #     "rRoleLambdaExecutionMetadataStepPermissionsBoundary",
            #     # managed_policy_arn=f"{{{{resolve:ssm:/SDLF/IAM/{dataset}/TeamPermissionsBoundary}}}}",
            # ),
        )
        postmetadatastep_role.attach_inline_policy(postmetadatastep_role_policy)
        postmetadatastep_role.add_managed_policy(common_policy)

        postmetadatastep_function = _lambda.Function(
            self,
            "rLambdaPostMetadataStep",
            runtime=_lambda.Runtime.PYTHON_3_12,
            code=_lambda.Code.from_asset(os.path.join(dirname, "lambda/postupdate-metadata/src")),
            handler="lambda_function.lambda_handler",
            layers=[datalakelibrary_layer],
            function_name=f"sdlf-{dataset}-{pipeline}-{stage}-postupdate",
            description="Post-Update the metadata in the DynamoDB Catalog table",
            memory_size=192,
            timeout=Duration.seconds(300),
            role=postmetadatastep_role,
            environment={
                "DATASET": dataset,
                "PIPELINE": pipeline,
                "PIPELINE_STAGE": stage,
                "ORG": org,
                "DOMAIN": data_domain,
            },
            environment_encryption=kms.Key.from_key_arn(
                self,
                "rLambdaPostMetadataStepEncryption",
                key_arn=infra_kms_key,
            ),
            # vpcconfig TODO
        )

        logs.LogGroup(
            self,
            "rLambdaPostMetadataStepLogGroup",
            removal_policy=RemovalPolicy.DESTROY,
            log_group_name=f"/aws/lambda/{postmetadatastep_function.function_name}",
            retention=logs.RetentionDays.ONE_MONTH,
            #            retention=Duration.days(p_cloudwatchlogsretentionindays.value_as_number),
            encryption_key=kms.Key.from_key_arn(
                self,
                "rLambdaPostMetadataStepLogGroupEncryption",
                key_arn=infra_kms_key,
            ),
        )

        errorstep_role_policy = iam.Policy(
            self,
            "rRoleLambdaExecutionErrorStepPolicy",
            policy_name=f"sdlf-{dataset}-{pipeline}-{stage}-error",
            statements=[
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
                        scope.format_arn(
                            service="sqs",
                            resource=f"sdlf-{dataset}-{pipeline}-dlq-*",
                            arn_format=ArnFormat.NO_RESOURCE_NAME,
                        )
                    ],
                )
            ],
        )

        errorstep_role = iam.Role(
            self,
            "rRoleLambdaExecutionErrorStep",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            path=f"/sdlf-{dataset}/",
            # permissions_boundary=iam.ManagedPolicy.from_managed_policy_arn(
            #     self,
            #     "rRoleLambdaExecutionErrorStepPermissionsBoundary",
            #     # managed_policy_arn=f"{{{{resolve:ssm:/SDLF/IAM/{dataset}/TeamPermissionsBoundary}}}}", TODO
            # ),
        )
        errorstep_role.attach_inline_policy(errorstep_role_policy)
        errorstep_role.add_managed_policy(common_policy)

        errorstep_function = _lambda.Function(
            self,
            "rLambdaErrorStep",
            runtime=_lambda.Runtime.PYTHON_3_12,
            code=_lambda.Code.from_asset(os.path.join(dirname, "lambda/error/src")),
            handler="lambda_function.lambda_handler",
            layers=[datalakelibrary_layer],
            function_name=f"sdlf-{dataset}-{pipeline}-{stage}-error",
            description="Fallback lambda to handle messages which failed processing",
            memory_size=192,
            timeout=Duration.seconds(300),
            role=errorstep_role,
            environment={
                "DATASET": dataset,
                "PIPELINE": pipeline,
                "PIPELINE_STAGE": stage,
                "ORG": org,
                "DOMAIN": data_domain,
            },
            environment_encryption=kms.Key.from_key_arn(
                self,
                "rLambdaErrorStepEncryption",
                key_arn=infra_kms_key,
            ),
            # vpcconfig TODO
        )

        logs.LogGroup(
            self,
            "rLambdaErrorStepLogGroup",
            removal_policy=RemovalPolicy.DESTROY,
            log_group_name=f"/aws/lambda/{errorstep_function.function_name}",
            retention=logs.RetentionDays.ONE_MONTH,
            #            retention=Duration.days(p_cloudwatchlogsretentionindays.value_as_number),
            encryption_key=kms.Key.from_key_arn(
                self,
                "rLambdaErrorStepLogGroupEncryption",
                key_arn=infra_kms_key,
            ),
        )

        ######## STATE MACHINE #########
        statemachine_role = iam.Role(
            self,
            "rStatesExecutionRole",
            assumed_by=iam.PrincipalWithConditions(
                iam.ServicePrincipal("states.amazonaws.com", region=scope.region),
                conditions={"StringEquals": {"aws:SourceAccount": scope.account}},
            ),
            path=f"/sdlf-{dataset}/",
            # permissions_boundary=iam.ManagedPolicy.from_managed_policy_arn(
            #     self,
            #     "rStatesExecutionRolePermissionsBoundary",
            #     managed_policy_arn=f"{{{{resolve:ssm:/sdlf/dataset/TeamPermissionsBoundary}}}}",
            # ), TODO
        )

        statemachine_resource_name = "rStateMachine"
        statemachine = sfn.StateMachine(
            self,
            statemachine_resource_name,
            state_machine_name=f"sdlf-{dataset}-{pipeline}-{stage}-sm",
            role=statemachine_role,
            definition_body=sfn.DefinitionBody.from_file(os.path.join(dirname, "state-machine/stage-lambda.asl.json")),
            definition_substitutions={
                "lPostMetadata": postmetadatastep_function.function_arn,
                "lError": errorstep_function.function_arn,
                "lTransform": transform,
            },
            tracing_enabled=xray_enabled,
        )
        self._external_interface(
            statemachine_resource_name,
            f"ARN of the {stage} {dataset} {pipeline} State Machine",
            statemachine.state_machine_name,
        )

        statemachine_map_role_policy = iam.Policy(
            self,
            "rStatesExecutionMapRolePolicy",
            policy_name="sfn-map",
            statements=[
                iam.PolicyStatement(
                    actions=["states:StartExecution", "states:DescribeExecution", "states:StopExecution"],
                    resources=[
                        statemachine.state_machine_arn,
                        scope.format_arn(
                            service="states",
                            resource="execution",
                            arn_format=ArnFormat.COLON_RESOURCE_NAME,
                            resource_name=f"sdlf-{statemachine.state_machine_name}:*",
                        ),
                    ],
                ),
            ],
        )
        statemachine_role.attach_inline_policy(statemachine_map_role_policy)

        ### Routing/Redrive
        routingstep_role_policy = iam.Policy(
            self,
            "rRoleLambdaExecutionRoutingStepPolicy",
            policy_name=f"sdlf-{dataset}-{pipeline}-{stage}-routing",
            statements=[
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
                        scope.format_arn(
                            service="sqs",
                            resource=f"sdlf-{dataset}-{pipeline}-queue-*",
                            arn_format=ArnFormat.NO_RESOURCE_NAME,
                        ),
                        scope.format_arn(
                            service="sqs",
                            resource=f"sdlf-{dataset}-{pipeline}-dlq-*",
                            arn_format=ArnFormat.NO_RESOURCE_NAME,
                        ),
                    ],
                ),
                iam.PolicyStatement(actions=["states:StartExecution"], resources=[statemachine.state_machine_arn]),
            ],
        )

        routingstep_role = iam.Role(
            self,
            "rRoleLambdaExecutionRoutingStep",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            path=f"/sdlf-{dataset}/",
            # permissions_boundary=iam.ManagedPolicy.from_managed_policy_arn(
            #     self,
            #     "rRoleLambdaExecutionRoutingStepPermissionsBoundary",
            #     # managed_policy_arn=f"{{{{resolve:ssm:/SDLF/IAM/{dataset}/TeamPermissionsBoundary}}}}",
            # ),
        )
        routingstep_role.attach_inline_policy(routingstep_role_policy)
        routingstep_role.add_managed_policy(common_policy)

        routingstep_function_resource_name = "rLambdaRoutingStep"
        routingstep_function = _lambda.Function(
            self,
            routingstep_function_resource_name,
            runtime=_lambda.Runtime.PYTHON_3_12,
            code=_lambda.Code.from_asset(os.path.join(dirname, "lambda/routing/src")),
            handler="lambda_function.lambda_handler",
            layers=[datalakelibrary_layer],
            function_name=f"sdlf-{dataset}-{pipeline}-{stage}-routing",
            description="Checks if items are to be processed and route them to state machine",
            memory_size=192,
            timeout=Duration.seconds(60),
            role=routingstep_role,
            environment={
                "STAGE_TRANSFORM": transform,
                "DATASET": dataset,
                "PIPELINE": pipeline,
                "PIPELINE_STAGE": stage,
                "ORG": org,
                "DOMAIN": data_domain,
            },
            environment_encryption=kms.Key.from_key_arn(
                self,
                "rLambdaRoutingStepEncryption",
                key_arn=infra_kms_key,
            ),
            # vpcconfig TODO
        )
        self._external_interface(
            routingstep_function_resource_name,
            f"ARN of the {stage} {dataset} {pipeline} Routing Lambda",
            routingstep_function.function_arn,
        )

        logs.LogGroup(
            self,
            "rLambdaRoutingStepLogGroup",
            removal_policy=RemovalPolicy.DESTROY,
            log_group_name=f"/aws/lambda/{routingstep_function.function_name}",
            retention=logs.RetentionDays.ONE_MONTH,
            #            retention=Duration.days(p_cloudwatchlogsretentionindays.value_as_number),
            encryption_key=kms.Key.from_key_arn(
                self,
                "rLambdaRoutingStepLogGroupEncryption",
                key_arn=infra_kms_key,
            ),
        )

        statemachine_role_policy = iam.Policy(
            self,
            "rStatesExecutionRolePolicy",
            policy_name=f"sdlf-{dataset}-{pipeline}-{stage}-sm",
            statements=[
                iam.PolicyStatement(
                    actions=["lambda:InvokeFunction"],
                    resources=[
                        transform,
                        postmetadatastep_function.function_arn,
                        errorstep_function.function_arn,
                        routingstep_function.function_arn,
                    ],
                ),
                iam.PolicyStatement(
                    actions=[
                        "xray:PutTraceSegments",  # W11 exception
                        "xray:PutTelemetryRecords",  # W11 exception
                        "xray:GetSamplingRules",  # W11 exception
                        "xray:GetSamplingTargets",  # W11 exception
                    ],
                    resources=["*"],
                ),
            ],
        )
        statemachine_role.attach_inline_policy(statemachine_role_policy)

        Pipeline(
            scope,
            f"{id}Pipeline",
            dataset=dataset,
            pipeline=pipeline,
            stage=stage,
            stage_enabled=True,
            trigger_type=trigger_type,
            trigger_target=routingstep_function.function_arn,
            kms_key=infra_kms_key,
            event_pattern=event_pattern,
            event_bus=event_bus,
        )

        redrivestep_function = _lambda.Function(
            self,
            "rLambdaRedriveStep",
            runtime=_lambda.Runtime.PYTHON_3_12,
            code=_lambda.Code.from_asset(os.path.join(dirname, "lambda/redrive/src")),
            handler="lambda_function.lambda_handler",
            layers=[datalakelibrary_layer],
            function_name=f"sdlf-{dataset}-{pipeline}-{stage}-redrive",
            description="Redrives Failed messages to the routing queue",
            memory_size=192,
            timeout=Duration.seconds(300),
            role=routingstep_role,
            environment={
                "DATASET": dataset,
                "PIPELINE": pipeline,
                "PIPELINE_STAGE": stage,
                "ORG": org,
                "DOMAIN": data_domain,
            },
            environment_encryption=kms.Key.from_key_arn(
                self,
                "rLambdaRedriveStepEncryption",
                key_arn=infra_kms_key,
            ),
            # vpcconfig TODO
        )

        logs.LogGroup(
            self,
            "rLambdaRedriveStepLogGroup",
            removal_policy=RemovalPolicy.DESTROY,
            log_group_name=f"/aws/lambda/{redrivestep_function.function_name}",
            retention=logs.RetentionDays.ONE_MONTH,
            # retention=Duration.days(p_cloudwatchlogsretentionindays.value_as_number),
            encryption_key=kms.Key.from_key_arn(
                self,
                "rLambdaRedriveStepLogGroupEncryption",
                key_arn=infra_kms_key,
            ),
        )

    def _external_interface(self, resource_name, description, value):
        ssm.StringParameter(
            self,
            f"{resource_name}Ssm",
            description=description,
            parameter_name=f"/sdlf/pipeline/{resource_name}",
            string_value=value,
        )
        self.external_interface[resource_name] = value
