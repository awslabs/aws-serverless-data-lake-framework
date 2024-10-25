# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT

import os.path

from aws_cdk import (
    ArnFormat,
    CfnParameter,
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

from sdlf import pipeline


class StageGlue(Construct):
    def __init__(self, scope: Construct, id: str, **kwargs) -> None:
        super().__init__(scope, id)

        dirname = os.path.dirname(__file__)

        # using context values would be better(?) for CDK but we haven't decided yet what the story is around ServiceCatalog and CloudFormation modules
        # perhaps both (context values feeding into CfnParameter) would be a nice-enough solution. Not sure though. TODO
        p_rawbucket = CfnParameter(
            self, "pRawBucket", description="Raw bucket", type="String", default="{{resolve:ssm:/SDLF/S3/RawBucket:1}}"
        )
        p_rawbucket.override_logical_id("pRawBucket")
        p_stagebucket = CfnParameter(
            self,
            "pStageBucket",
            description="Stage Bucket",
            type="String",
            default="{{resolve:ssm:/SDLF/S3/StageBucket:1}}",
        )
        p_stagebucket.override_logical_id("pStageBucket")
        p_enabletracing = CfnParameter(
            self,
            "pEnableTracing",
            description="Flag for whether XRay tracing is enabled",
            type="String",
        )
        p_enabletracing.override_logical_id("pEnableTracing")

        pipeline_interface = pipeline.Pipeline(scope, f"{id}Pipeline")
        p_pipeline = pipeline_interface.p_pipeline
        p_stagename = pipeline_interface.p_stagename
        p_datasetname = pipeline_interface.p_datasetname

        ######## IAM #########
        common_policy = iam.ManagedPolicy(
            self,
            "rLambdaCommonPolicy",
            path=f"/sdlf-{p_datasetname.value_as_string}/",
            statements=[
                iam.PolicyStatement(
                    actions=["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
                    resources=[
                        scope.format_arn(
                            service="logs",
                            resource="log-group",
                            arn_format=ArnFormat.COLON_RESOURCE_NAME,
                            resource_name=f"/aws/lambda/sdlf-{p_datasetname.value_as_string}-{p_pipeline.value_as_string}-*",
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
                    actions=[
                        "kms:DescribeKey",
                        "kms:Encrypt",
                        "kms:Decrypt",
                        "kms:ReEncrypt*",
                        "kms:GenerateDataKey*",
                        "kms:CreateGrant",
                    ],
                    resources=[f"{{{{resolve:ssm:/SDLF/KMS/{p_datasetname.value_as_string}/InfraKeyId}}}}"],
                ),
            ],
        )

        ######## LAMBDA FUNCTIONS #########
        # Metadata Step Role (fetch metadata, update pipeline execution history...)
        postmetadatastep_role_policy = iam.Policy(
            self,
            "rRoleLambdaExecutionMetadataStepPolicy",
            policy_name=f"sdlf-{p_datasetname.value_as_string}-{p_pipeline.value_as_string}-{p_stagename.value_as_string}-metadata",
            statements=[
                iam.PolicyStatement(
                    actions=["s3:ListBucket"],
                    resources=[
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
                    ],
                ),
                iam.PolicyStatement(
                    actions=["s3:GetObject"],
                    resources=[
                        scope.format_arn(
                            service="s3",
                            resource=f"{p_stagebucket.value_as_string}/{p_datasetname.value_as_string}/*",
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
            path=f"/sdlf-{p_datasetname.value_as_string}/",
            permissions_boundary=iam.ManagedPolicy.from_managed_policy_arn(
                self,
                "rRoleLambdaExecutionMetadataStepPermissionsBoundary",
                managed_policy_arn=f"{{{{resolve:ssm:/SDLF/IAM/{p_datasetname.value_as_string}/TeamPermissionsBoundary}}}}",
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
            function_name=f"sdlf-{p_datasetname.value_as_string}-{p_pipeline.value_as_string}-postupdate-{p_stagename.value_as_string}",
            description="Post-Update the metadata in the DynamoDB Catalog table",
            memory_size=192,
            timeout=Duration.seconds(300),
            role=postmetadatastep_role,
            environment_encryption=kms.Key.from_key_arn(
                self,
                "rLambdaPostMetadataStepEncryption",
                key_arn=f"{{{{resolve:ssm:/SDLF/KMS/{p_datasetname.value_as_string}/InfraKeyId}}}}",
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
                key_arn=f"{{{{resolve:ssm:/SDLF/KMS/{p_datasetname.value_as_string}/InfraKeyId}}}}",
            ),
        )

        errorstep_role_policy = iam.Policy(
            self,
            "rRoleLambdaExecutionErrorStepPolicy",
            policy_name=f"sdlf-{p_datasetname.value_as_string}-{p_pipeline.value_as_string}-{p_stagename.value_as_string}-error",
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
                            resource=f"sdlf-{p_datasetname.value_as_string}-{p_pipeline.value_as_string}-dlq-*",
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
            path=f"/sdlf-{p_datasetname.value_as_string}/",
            permissions_boundary=iam.ManagedPolicy.from_managed_policy_arn(
                self,
                "rRoleLambdaExecutionErrorStepPermissionsBoundary",
                managed_policy_arn=f"{{{{resolve:ssm:/SDLF/IAM/{p_datasetname.value_as_string}/TeamPermissionsBoundary}}}}",
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
            function_name=f"sdlf-{p_datasetname.value_as_string}-{p_pipeline.value_as_string}-error-{p_stagename.value_as_string}",
            description="Fallback lambda to handle messages which failed processing",
            memory_size=192,
            timeout=Duration.seconds(300),
            role=errorstep_role,
            environment_encryption=kms.Key.from_key_arn(
                self,
                "rLambdaErrorStepEncryption",
                key_arn=f"{{{{resolve:ssm:/SDLF/KMS/{p_datasetname.value_as_string}/InfraKeyId}}}}",
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
                key_arn=f"{{{{resolve:ssm:/SDLF/KMS/{p_datasetname.value_as_string}/InfraKeyId}}}}",
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
            "rStatesExecutionRolePolicy",
            policy_name=f"sdlf-{p_datasetname.value_as_string}-{p_pipeline.value_as_string}-{p_stagename.value_as_string}-states-execution",
            statements=[
                iam.PolicyStatement(
                    actions=["lambda:InvokeFunction"],
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
                    actions=[
                        "glue:StartJobRun",
                        "glue:GetJobRun",
                        "glue:GetJobRuns",
                        "glue:BatchStopJobRun",
                    ],
                    resources=[
                        scope.format_arn(
                            service="glue",
                            resource="job",
                            arn_format=ArnFormat.SLASH_RESOURCE_NAME,
                            resource_name=f"sdlf-{p_datasetname.value_as_string}-*",
                        ),
                    ],
                ),
                iam.PolicyStatement(
                    actions=[
                        "glue:StartCrawler",
                        "glue:GetCrawler",
                    ],
                    resources=[
                        scope.format_arn(
                            service="glue",
                            resource="crawler",
                            arn_format=ArnFormat.SLASH_RESOURCE_NAME,
                            resource_name=f"sdlf-{p_datasetname.value_as_string}-*",
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
                iam.ServicePrincipal("states.amazonaws.com", region=scope.region),
                conditions={"StringEquals": {"aws:SourceAccount": scope.account}},
            ),
            path=f"/sdlf-{p_datasetname.value_as_string}/",
            permissions_boundary=iam.ManagedPolicy.from_managed_policy_arn(
                self,
                "rStatesExecutionRolePermissionsBoundary",
                managed_policy_arn=f"{{{{resolve:ssm:/SDLF/IAM/{p_datasetname.value_as_string}/TeamPermissionsBoundary}}}}",
            ),
        )
        statemachine_role.attach_inline_policy(statemachine_role_policy)

        statemachine = sfn.StateMachine(
            self,
            "rStateMachine",
            state_machine_name=f"sdlf-{p_datasetname.value_as_string}-{p_pipeline.value_as_string}-sm-{p_stagename.value_as_string}",
            role=statemachine_role,
            definition_body=sfn.DefinitionBody.from_file(os.path.join(dirname, "state-machine/stage-glue.asl.json")),
            definition_substitutions={
                "lPostMetadata": postmetadatastep_function.function_arn,
                "lError": errorstep_function.function_arn,
            },
            tracing_enabled=True if p_enabletracing.value_as_string.lower() == "true" else False,
        )
        ssm.StringParameter(
            self,
            "rStateMachineSsm",
            description=f"ARN of the {p_stagename.value_as_string} {p_datasetname.value_as_string} {p_pipeline.value_as_string} State Machine",
            parameter_name=f"/SDLF/SM/{p_datasetname.value_as_string}/{p_pipeline.value_as_string}{p_stagename.value_as_string}SM",
            simple_name=False,  # parameter name is a token
            string_value=statemachine.state_machine_name,
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

        routingstep_role_policy = iam.Policy(
            self,
            "rRoleLambdaExecutionRoutingStepPolicy",
            policy_name=f"sdlf-{p_datasetname.value_as_string}-{p_pipeline.value_as_string}-{p_stagename.value_as_string}-routing",
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
                            resource=f"sdlf-{p_datasetname.value_as_string}-{p_pipeline.value_as_string}-queue-*",
                            arn_format=ArnFormat.NO_RESOURCE_NAME,
                        ),
                        scope.format_arn(
                            service="sqs",
                            resource=f"sdlf-{p_datasetname.value_as_string}-{p_pipeline.value_as_string}-dlq-*",
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
            path=f"/sdlf-{p_datasetname.value_as_string}/",
            permissions_boundary=iam.ManagedPolicy.from_managed_policy_arn(
                self,
                "rRoleLambdaExecutionRoutingStepPermissionsBoundary",
                managed_policy_arn=f"{{{{resolve:ssm:/SDLF/IAM/{p_datasetname.value_as_string}/TeamPermissionsBoundary}}}}",
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
            function_name=f"sdlf-{p_datasetname.value_as_string}-{p_pipeline.value_as_string}-routing-{p_stagename.value_as_string}",
            description="Checks if items are to be processed and route them to state machine",
            memory_size=192,
            timeout=Duration.seconds(60),
            role=routingstep_role,
            environment={
                "STAGE_TRANSFORM": "",
            },
            environment_encryption=kms.Key.from_key_arn(
                self,
                "rLambdaRoutingStepEncryption",
                key_arn=f"{{{{resolve:ssm:/SDLF/KMS/{p_datasetname.value_as_string}/InfraKeyId}}}}",
            ),
            # vpcconfig TODO
        )
        ssm.StringParameter(
            self,
            "rRoutingLambdaSsm",
            description=f"ARN of the {p_stagename.value_as_string} {p_datasetname.value_as_string} {p_pipeline.value_as_string} Routing Lambda",
            parameter_name=f"/SDLF/Lambda/{p_datasetname.value_as_string}/{p_pipeline.value_as_string}{p_stagename.value_as_string}RoutingLambda",
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
                self,
                "rLambdaRoutingStepLogGroupEncryption",
                key_arn=f"{{{{resolve:ssm:/SDLF/KMS/{p_datasetname.value_as_string}/InfraKeyId}}}}",
            ),
        )
        pipeline_interface.resources(scope, routingstep_function.function_arn)

        redrivestep_function = _lambda.Function(
            self,
            "rLambdaRedriveStep",
            runtime=_lambda.Runtime.PYTHON_3_12,
            code=_lambda.Code.from_asset(os.path.join(dirname, "lambda/redrive/src")),
            handler="lambda_function.lambda_handler",
            function_name=f"sdlf-{p_datasetname.value_as_string}-{p_pipeline.value_as_string}-redrive-{p_stagename.value_as_string}",
            description="Redrives Failed messages to the routing queue",
            memory_size=192,
            timeout=Duration.seconds(300),
            role=routingstep_role,
            environment_encryption=kms.Key.from_key_arn(
                self,
                "rLambdaRedriveStepEncryption",
                key_arn=f"{{{{resolve:ssm:/SDLF/KMS/{p_datasetname.value_as_string}/InfraKeyId}}}}",
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
                self,
                "rLambdaRedriveStepLogGroupEncryption",
                key_arn=f"{{{{resolve:ssm:/SDLF/KMS/{p_datasetname.value_as_string}/InfraKeyId}}}}",
            ),
        )
