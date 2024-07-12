# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT

import os.path

from aws_cdk import (
    ArnFormat,
    Duration,
    RemovalPolicy,
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
    aws_scheduler_alpha as scheduler,
    aws_sns as sns,
    aws_sqs as sqs,
    aws_ssm as ssm,
    aws_stepfunctions as sfn,
)
from constructs import Construct


class SdlfStageLambda(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        dirname = os.path.dirname(__file__)

        # using context values would be better(?) for CDK but we haven't decided yet what the story is around ServiceCatalog and CloudFormation modules
        # perhaps both (context values feeding into CfnParameter) would be a nice-enough solution. Not sure though. TODO
        p_pipelinereference = CfnParameter(
            self,
            "pPipelineReference",
            type="String",
            default="none",
        )
        p_rawbucket = CfnParameter(
            self, "pRawBucket", description="Raw bucket", type="String", default="{{resolve:ssm:/SDLF/S3/RawBucket:2}}"
        )
        p_stagebucket = CfnParameter(
            self,
            "pStageBucket",
            description="Stage Bucket",
            type="String",
            default="{{resolve:ssm:/SDLF/S3/StageBucket:2}}",
        )
        p_teamname = CfnParameter(
            self,
            "pTeamName",
            description="Name of the team (all lowercase, no symbols or spaces)",
            type="String",
            allowed_pattern="[a-z0-9]{2,12}",
        )
        p_pipeline = CfnParameter(
            self,
            "pPipeline",
            description="The name of the pipeline (all lowercase, no symbols or spaces)",
            type="String",
            allowed_pattern="[a-z0-9]*",
        )
        p_stagename = CfnParameter(
            self,
            "pStageName",
            description="Name of the stage (all lowercase, hyphen allowed, no other symbols or spaces)",
            type="String",
            allowed_pattern="[a-zA-Z0-9\\-]{1,12}",
        )
        p_enabletracing = CfnParameter(
            self,
            "pEnableTracing",
            description="Flag for whether XRay tracing is enabled",
            type="String",
        )

        ######## IAM #########
        common_policy = iam.ManagedPolicy(
            self,
            "rLambdaCommonPolicy",
            path=f"/sdlf-{p_teamname.value_as_string}/",
            statements=[
                iam.PolicyStatement(
                    actions=["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
                    resources=[
                        self.format_arn(
                            service="logs",
                            resource="log-group",
                            arn_format=ArnFormat.COLON_RESOURCE_NAME,
                            resource_name=f"/aws/lambda/sdlf-{p_teamname.value_as_string}-{p_pipeline.value_as_string}-*",
                        )
                    ],
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
                    actions=[
                        "kms:DescribeKey",
                        "kms:Encrypt",
                        "kms:Decrypt",
                        "kms:ReEncrypt*",
                        "kms:GenerateDataKey*",
                        "kms:CreateGrant",
                    ],
                    resources=[f"{{{{resolve:ssm:/SDLF/KMS/{p_teamname.value_as_string}/InfraKeyId}}}}"],
                ),
            ],
        )

        ######## LAMBDA FUNCTIONS #########
        transformstep_role_policy = iam.Policy(
            self,
            "sdlf-transform-lambda",  # f"sdlf-{p_teamname.value_as_string}-{p_pipeline.value_as_string}-process-{p_stagename.value_as_string}",
            statements=[
                iam.PolicyStatement(
                    actions=["s3:ListBucket", "s3:GetBucketVersioning"],
                    resources=[
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
                    ],
                ),
                iam.PolicyStatement(
                    actions=["s3:GetObject"],
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
                    ],
                ),
                iam.PolicyStatement(
                    actions=["s3:PutObject"],
                    resources=[
                        self.format_arn(
                            service="s3",
                            resource=f"{p_stagebucket.value_as_string}/{p_teamname.value_as_string}/*",
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
                    resources=[f"{{{{resolve:ssm:/SDLF/KMS/{p_teamname.value_as_string}/DataKeyId}}}}"],
                ),
            ],
        )

        transformstep_role = iam.Role(
            self,
            "rRoleLambdaExecutionProcessingStep",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            path=f"/sdlf-{p_teamname.value_as_string}/",
            permissions_boundary=iam.ManagedPolicy.from_managed_policy_arn(
                self,
                "chaipa4",
                managed_policy_arn=f"{{{{resolve:ssm:/SDLF/IAM/{p_teamname.value_as_string}/TeamPermissionsBoundary}}}}",
            ),
        )
        transformstep_role.attach_inline_policy(transformstep_role_policy)
        transformstep_role.add_managed_policy(common_policy)

        transformstep_function = _lambda.Function(
            self,
            "rLambdaTransformStep",
            runtime=_lambda.Runtime.PYTHON_3_12,
            code=_lambda.Code.from_asset(os.path.join(dirname, "lambda/process-object/src")),
            handler="lambda_function.lambda_handler",
            function_name=f"sdlf-{p_teamname.value_as_string}-{p_pipeline.value_as_string}-process-{p_stagename.value_as_string}",
            description="Processing pipeline",
            memory_size=1536,
            timeout=Duration.seconds(600),
            role=transformstep_role,
            environment_encryption=kms.Key.from_key_arn(
                self, "chaipakms", key_arn=f"{{{{resolve:ssm:/SDLF/KMS/{p_teamname.value_as_string}/InfraKeyId}}}}"
            ),
            # vpcconfig TODO
        )

        logs.LogGroup(
            self,
            "rLambdaTransformStepLogGroup",
            removal_policy=RemovalPolicy.DESTROY,
            log_group_name=f"/aws/lambda/{transformstep_function.function_name}",
            retention=logs.RetentionDays.ONE_MONTH,
            #            retention=Duration.days(p_cloudwatchlogsretentionindays.value_as_number),
            encryption_key=kms.Key.from_key_arn(
                self, "chaipakms2", key_arn=f"{{{{resolve:ssm:/SDLF/KMS/{p_teamname.value_as_string}/InfraKeyId}}}}"
            ),
        )

        # Metadata Step Role (fetch metadata, update pipeline execution history...)
        postmetadatastep_role_policy = iam.Policy(
            self,
            "sdlf-metadata-lambda",  # f"sdlf-{p_teamname.value_as_string}-{p_pipeline.value_as_string}-metadata-{p_stagename.value_as_string}",
            statements=[
                iam.PolicyStatement(
                    actions=["s3:ListBucket"],
                    resources=[
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
                    ],
                ),
                iam.PolicyStatement(
                    actions=["s3:GetObject"],
                    resources=[
                        self.format_arn(
                            service="s3",
                            resource=f"{p_stagebucket.value_as_string}/{p_teamname.value_as_string}/*",
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
            path=f"/sdlf-{p_teamname.value_as_string}/",
            permissions_boundary=iam.ManagedPolicy.from_managed_policy_arn(
                self,
                "chaipa1",
                managed_policy_arn=f"{{{{resolve:ssm:/SDLF/IAM/{p_teamname.value_as_string}/TeamPermissionsBoundary}}}}",
            ),
        )
        postmetadatastep_role.attach_inline_policy(postmetadatastep_role_policy)
        postmetadatastep_role.add_managed_policy(common_policy)

        postmetadatastep_function = _lambda.Function(
            self,
            "rLambdaPostMetadataStep",
            runtime=_lambda.Runtime.PYTHON_3_12,
            code=_lambda.Code.from_asset(os.path.join(dirname, "lambda/postupdate-metadata/src")),
            handler="lambda_function.lambda_handler",
            function_name=f"sdlf-{p_teamname.value_as_string}-{p_pipeline.value_as_string}-postupdate-{p_stagename.value_as_string}",
            description="Post-Update the metadata in the DynamoDB Catalog table",
            memory_size=192,
            timeout=Duration.seconds(300),
            role=postmetadatastep_role,
            environment_encryption=kms.Key.from_key_arn(
                self, "chaipakms3", key_arn=f"{{{{resolve:ssm:/SDLF/KMS/{p_teamname.value_as_string}/InfraKeyId}}}}"
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
                self, "chaipakms4", key_arn=f"{{{{resolve:ssm:/SDLF/KMS/{p_teamname.value_as_string}/InfraKeyId}}}}"
            ),
        )

        errorstep_role_policy = iam.Policy(
            self,
            "sdlf-error-lambda",  # f"sdlf-{p_teamname.value_as_string}-{p_pipeline.value_as_string}-error-{p_stagename.value_as_string}",
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
                        self.format_arn(
                            service="sqs",
                            resource=f"sdlf-{p_teamname.value_as_string}-{p_pipeline.value_as_string}-dlq-*",
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
            path=f"/sdlf-{p_teamname.value_as_string}/",
            permissions_boundary=iam.ManagedPolicy.from_managed_policy_arn(
                self,
                "chaipa2",
                managed_policy_arn=f"{{{{resolve:ssm:/SDLF/IAM/{p_teamname.value_as_string}/TeamPermissionsBoundary}}}}",
            ),
        )
        errorstep_role.attach_inline_policy(errorstep_role_policy)
        errorstep_role.add_managed_policy(common_policy)

        errorstep_function = _lambda.Function(
            self,
            "rLambdaErrorStep",
            runtime=_lambda.Runtime.PYTHON_3_12,
            code=_lambda.Code.from_asset(os.path.join(dirname, "lambda/error/src")),
            handler="lambda_function.lambda_handler",
            function_name=f"sdlf-{p_teamname.value_as_string}-{p_pipeline.value_as_string}-error-{p_stagename.value_as_string}",
            description="Fallback lambda to handle messages which failed processing",
            memory_size=192,
            timeout=Duration.seconds(300),
            role=errorstep_role,
            environment_encryption=kms.Key.from_key_arn(
                self, "chaipakms5", key_arn=f"{{{{resolve:ssm:/SDLF/KMS/{p_teamname.value_as_string}/InfraKeyId}}}}"
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
                self, "chaipakms6", key_arn=f"{{{{resolve:ssm:/SDLF/KMS/{p_teamname.value_as_string}/InfraKeyId}}}}"
            ),
        )

        ######## CLOUDWATCH #########
        #   rUpdateSubscriptionFilterRoutingStep:
        #     Type: AWS::Logs::SubscriptionFilter
        #     Condition: DeployElasticSearch
        #     Properties:
        #       LogGroupName: !Ref rLambdaRoutingStepLogGroup
        #       DestinationArn: !Ref pKibanaStream
        #       RoleArn: !Ref pKibanaStreamRole
        #       FilterPattern: "[log_type, log_timestamp, log_id, log_message]"

        #   rLambdaRoutingStepCloudWatchAlarm:
        #     Type: AWS::CloudWatch::Alarm
        #     Properties:
        #       AlarmDescription: !Sub ${pStageName} ${pTeamName} ${pPipeline} Routing Lambda Alarm
        #       AlarmActions:
        #         - !Sub "{{resolve:ssm:/SDLF/SNS/${pTeamName}/Notifications}}"
        #       MetricName: Errors
        #       EvaluationPeriods: 5
        #       Period: 60
        #       ComparisonOperator: GreaterThanThreshold
        #       Namespace: AWS/Lambda
        #       Statistic: Sum
        #       Threshold: 5
        #       Unit: Count
        #       Dimensions:
        #         - Name: FunctionName
        #           Value: !Ref rLambdaRoutingStep
        #   rUpdateSubscriptionFilterRedriveStep:
        #     Type: AWS::Logs::SubscriptionFilter
        #     Condition: DeployElasticSearch
        #     Properties:
        #       LogGroupName: !Ref rLambdaRedriveStepLogGroup
        #       DestinationArn: !Ref pKibanaStream
        #       RoleArn: !Ref pKibanaStreamRole
        #       FilterPattern: "[log_type, log_timestamp, log_id, log_message]"
        #   rUpdateSubscriptionFilterTransformStep:
        #     Type: AWS::Logs::SubscriptionFilter
        #     Condition: DeployElasticSearch
        #     Properties:
        #       LogGroupName: !Ref rLambdaTransformStepLogGroup
        #       DestinationArn: !Ref pKibanaStream
        #       RoleArn: !Ref pKibanaStreamRole
        #       FilterPattern: "[log_type, log_timestamp, log_id, log_message]"
        #   rUpdateSubscriptionFilterPostMetadataStep:
        #     Type: AWS::Logs::SubscriptionFilter
        #     Condition: DeployElasticSearch
        #     Properties:
        #       LogGroupName: !Ref rLambdaPostMetadataStepLogGroup
        #       DestinationArn: !Ref pKibanaStream
        #       RoleArn: !Ref pKibanaStreamRole
        #       FilterPattern: "[log_type, log_timestamp, log_id, log_message]"
        #   rUpdateSubscriptionFilterErrorStep:
        #     Type: AWS::Logs::SubscriptionFilter
        #     Condition: DeployElasticSearch
        #     Properties:
        #       LogGroupName: !Ref rLambdaErrorStepLogGroup
        #       DestinationArn: !Ref pKibanaStream
        #       RoleArn: !Ref pKibanaStreamRole
        #       FilterPattern: "[log_type, log_timestamp, log_id, log_message]"

        #   rLambdaErrorStepCloudWatchAlarm:
        #     Type: AWS::CloudWatch::Alarm
        #     Properties:
        #       AlarmDescription: !Sub ${pStageName} ${pTeamName} ${pPipeline} Error Lambda Alarm
        #       AlarmActions:
        #         - !Sub "{{resolve:ssm:/SDLF/SNS/${pTeamName}/Notifications}}"
        #       MetricName: Invocations
        #       EvaluationPeriods: 5
        #       Period: 60
        #       ComparisonOperator: GreaterThanThreshold
        #       Namespace: AWS/Lambda
        #       Statistic: Sum
        #       Threshold: 5
        #       Unit: Count
        #       Dimensions:
        #         - Name: FunctionName
        #           Value: !Ref rLambdaErrorStep

        ######## STATE MACHINE #########
        statemachine_role_policy = iam.Policy(
            self,
            "sdlf-statemachine-lambda",  # f"sdlf-{p_teamname.value_as_string}-states-execution",
            statements=[
                iam.PolicyStatement(
                    actions=["lambda:InvokeFunction"],
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

        statemachine_role = iam.Role(
            self,
            "rStatesExecutionRole",
            assumed_by=iam.PrincipalWithConditions(
                iam.ServicePrincipal("states.amazonaws.com", region=self.region),
                conditions={"StringEquals": {"aws:SourceAccount": self.account}},
            ),
            path=f"/sdlf-{p_teamname.value_as_string}/",
            permissions_boundary=iam.ManagedPolicy.from_managed_policy_arn(
                self,
                "chaipa3",
                managed_policy_arn=f"{{{{resolve:ssm:/SDLF/IAM/{p_teamname.value_as_string}/TeamPermissionsBoundary}}}}",
            ),
        )
        statemachine_role.attach_inline_policy(statemachine_role_policy)

        statemachine = sfn.StateMachine(
            self,
            "rStateMachine",
            state_machine_name=f"sdlf-{p_teamname.value_as_string}-{p_pipeline.value_as_string}-sm-{p_stagename.value_as_string}",
            role=statemachine_role,
            definition_body=sfn.DefinitionBody.from_file(os.path.join(dirname, "state-machine/stage-lambda.asl.json")),
            definition_substitutions={
                "lPostMetadata": postmetadatastep_function.function_arn,
                "lError": errorstep_function.function_arn,
            },
            tracing_enabled=True if p_enabletracing.value_as_string.lower() == "true" else False,
        )
        ssm.StringParameter(
            self,
            "rStateMachineSsm",
            description=f"ARN of the {p_stagename.value_as_string} {p_teamname.value_as_string} {p_pipeline.value_as_string} State Machine",
            parameter_name=f"/SDLF/SM/{p_teamname.value_as_string}/{p_pipeline.value_as_string}{p_stagename.value_as_string}SM",
            simple_name=False,  # parameter name is a token
            string_value=statemachine.state_machine_name,
        )

        statemachine_map_role_policy = iam.Policy(
            self,
            "sfn-map",
            statements=[
                iam.PolicyStatement(
                    actions=["states:StartExecution", "states:DescribeExecution", "states:StopExecution"],
                    resources=[
                        statemachine.state_machine_arn,
                        self.format_arn(
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
            "sdlf-routing-lambda",  # f"sdlf-{p_teamname.value_as_string}-{p_pipeline.value_as_string}-routing-{p_stagename.value_as_string}",
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
                        self.format_arn(
                            service="sqs",
                            resource=f"sdlf-{p_teamname.value_as_string}-{p_pipeline.value_as_string}-queue-*",
                            arn_format=ArnFormat.NO_RESOURCE_NAME,
                        ),
                        self.format_arn(
                            service="sqs",
                            resource=f"sdlf-{p_teamname.value_as_string}-{p_pipeline.value_as_string}-dlq-*",
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
            path=f"/sdlf-{p_teamname.value_as_string}/",
            permissions_boundary=iam.ManagedPolicy.from_managed_policy_arn(
                self,
                "chaipa5",
                managed_policy_arn=f"{{{{resolve:ssm:/SDLF/IAM/{p_teamname.value_as_string}/TeamPermissionsBoundary}}}}",
            ),
        )
        routingstep_role.attach_inline_policy(routingstep_role_policy)
        routingstep_role.add_managed_policy(common_policy)

        routingstep_function = _lambda.Function(
            self,
            "rLambdaRoutingStep",
            runtime=_lambda.Runtime.PYTHON_3_12,
            code=_lambda.Code.from_asset(os.path.join(dirname, "lambda/routing/src")),
            handler="lambda_function.lambda_handler",
            function_name=f"sdlf-{p_teamname.value_as_string}-{p_pipeline.value_as_string}-routing-{p_stagename.value_as_string}",
            description="Checks if items are to be processed and route them to state machine",
            memory_size=192,
            timeout=Duration.seconds(60),
            role=routingstep_role,
            environment={
                "STAGE_TRANSFORM": transformstep_function.function_arn,
            },
            environment_encryption=kms.Key.from_key_arn(
                self, "chaipakms7", key_arn=f"{{{{resolve:ssm:/SDLF/KMS/{p_teamname.value_as_string}/InfraKeyId}}}}"
            ),
            # vpcconfig TODO
        )
        ssm.StringParameter(
            self,
            "rRoutingLambdaSsm",
            description=f"ARN of the {p_stagename.value_as_string} {p_teamname.value_as_string} {p_pipeline.value_as_string} Routing Lambda",
            parameter_name=f"/SDLF/Lambda/{p_teamname.value_as_string}/{p_pipeline.value_as_string}{p_stagename.value_as_string}RoutingLambda",
            simple_name=False,  # parameter name is a token
            string_value=routingstep_function.function_arn,
        )

        logs.LogGroup(
            self,
            "rLambdaRoutingStepLogGroup",
            removal_policy=RemovalPolicy.DESTROY,
            log_group_name=f"/aws/lambda/{routingstep_function.function_name}",
            retention=logs.RetentionDays.ONE_MONTH,
            #            retention=Duration.days(p_cloudwatchlogsretentionindays.value_as_number),
            encryption_key=kms.Key.from_key_arn(
                self, "chaipakms8", key_arn=f"{{{{resolve:ssm:/SDLF/KMS/{p_teamname.value_as_string}/InfraKeyId}}}}"
            ),
        )

        redrivestep_function = _lambda.Function(
            self,
            "rLambdaRedriveStep",
            runtime=_lambda.Runtime.PYTHON_3_12,
            code=_lambda.Code.from_asset(os.path.join(dirname, "lambda/redrive/src")),
            handler="lambda_function.lambda_handler",
            function_name=f"sdlf-{p_teamname.value_as_string}-{p_pipeline.value_as_string}-redrive-{p_stagename.value_as_string}",
            description="Redrives Failed messages to the routing queue",
            memory_size=192,
            timeout=Duration.seconds(300),
            role=routingstep_role,
            environment_encryption=kms.Key.from_key_arn(
                self, "chaipakms9", key_arn=f"{{{{resolve:ssm:/SDLF/KMS/{p_teamname.value_as_string}/InfraKeyId}}}}"
            ),
            # vpcconfig TODO
        )

        logs.LogGroup(
            self,
            "rLambdaRedriveStepLogGroup",
            removal_policy=RemovalPolicy.DESTROY,
            log_group_name=f"/aws/lambda/{redrivestep_function.function_name}",
            retention=logs.RetentionDays.ONE_MONTH,
            #            retention=Duration.days(p_cloudwatchlogsretentionindays.value_as_number),
            encryption_key=kms.Key.from_key_arn(
                self, "chaipakms10", key_arn=f"{{{{resolve:ssm:/SDLF/KMS/{p_teamname.value_as_string}/InfraKeyId}}}}"
            ),
        )

        # CloudFormation Outputs TODO
        CfnOutput(
            self,
            "oPipelineReference",
            description="CodePipeline reference this stack has been deployed with",
            value=p_pipelinereference.value_as_string,
        )
