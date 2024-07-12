# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT

import json

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
    aws_scheduler_alpha as scheduler,
    aws_sns as sns,
    aws_sqs as sqs,
    aws_ssm as ssm,
)
from constructs import Construct


class SdlfPipeline(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

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
        p_env = CfnParameter(
            self, "pEnv", description="Environment name", type="String", default="{{resolve:ssm:/SDLF/Misc/pEnv:1}}"
        )
        p_teamname = CfnParameter(
            self,
            "pTeamName",
            description="Name of the team (all lowercase, no symbols or spaces)",
            type="String",
            allowed_pattern="[a-z0-9]{2,12}",
        )
        p_pipelinename = CfnParameter(
            self,
            "pPipelineName",
            description="The name of the pipeline (all lowercase, no symbols or spaces)",
            type="String",
            allowed_pattern="[a-z0-9]*",
        )
        p_stagename = CfnParameter(
            self,
            "pStageName",
            description="Name of the stage (all lowercase, hyphen allowed, no other symbols or spaces)",
            type="String",
            allowed_pattern="[a-zA-Z0-9\\-]{2,12}",
        )
        p_stageenabled = CfnParameter(
            self,
            "pStageEnabled",
            description="Whether the stage is enabled or not",
            type="String",
            allowed_values=["true", "false"],
        )
        p_triggertype = CfnParameter(
            self,
            "pTriggerType",
            description="Trigger type of the stage (event or schedule)",
            type="String",
            allowed_values=["event", "schedule"],
            default="event",
        )
        p_schedule = CfnParameter(
            self,
            "pSchedule",
            description="Cron expression when trigger type is schedule",
            type="String",
            default="cron(*/5 * * * ? *)",
        )
        p_eventpattern = CfnParameter(
            self,
            "pEventPattern",
            description="Event pattern to match from previous stage",
            type="String",
            default="",
        )
        p_lambdaroutingstep = CfnParameter(
            self,
            "pLambdaRoutingStep",
            description="Routing Lambda function ARN",
            type="String",
        )

        routing_dlq = sqs.Queue(
            self,
            "rDeadLetterQueueRoutingStep",
            removal_policy=RemovalPolicy.DESTROY,
            queue_name=f"sdlf-{p_teamname.value_as_string}-{p_pipelinename.value_as_string}-dlq-{p_stagename.value_as_string}.fifo",
            fifo=True,
            retention_period=Duration.days(14),
            visibility_timeout=Duration.seconds(60),
            encryption_master_key=kms.Key.from_key_arn(
                self, "chaipakms1", key_arn=f"{{{{resolve:ssm:/SDLF/KMS/{p_teamname.value_as_string}/InfraKeyId}}}}"
            ),
        )
        ssm.StringParameter(
            self,
            "rDeadLetterQueueRoutingStepSsm",
            description=f"Name of the {p_stagename.value_as_string} {p_teamname.value_as_string} {p_pipelinename.value_as_string} DLQ",
            parameter_name=f"/SDLF/SQS/{p_teamname.value_as_string}/{p_pipelinename.value_as_string}{p_stagename.value_as_string}DLQ",
            simple_name=False,  # parameter name is a token
            string_value=routing_dlq.queue_name,
        )

        routing_queue = sqs.Queue(
            self,
            "rQueueRoutingStep",
            removal_policy=RemovalPolicy.DESTROY,
            queue_name=f"sdlf-{p_teamname.value_as_string}-{p_pipelinename.value_as_string}-queue-{p_stagename.value_as_string}.fifo",
            fifo=True,
            content_based_deduplication=True,
            retention_period=Duration.days(7),
            visibility_timeout=Duration.seconds(60),
            encryption_master_key=kms.Key.from_key_arn(
                self, "chaipakms2", key_arn=f"{{{{resolve:ssm:/SDLF/KMS/{p_teamname.value_as_string}/InfraKeyId}}}}"
            ),
            dead_letter_queue=sqs.DeadLetterQueue(
                max_receive_count=1,
                queue=routing_dlq,
            ),
        )
        ssm.StringParameter(
            self,
            "rQueueRoutingStepSsm",
            description=f"Name of the {p_stagename.value_as_string} {p_teamname.value_as_string} {p_pipelinename.value_as_string} Queue",
            parameter_name=f"/SDLF/SQS/{p_teamname.value_as_string}/{p_pipelinename.value_as_string}{p_stagename.value_as_string}Queue",
            simple_name=False,  # parameter name is a token
            string_value=routing_dlq.queue_name,
        )

        stage_rule = events.Rule(
            self,
            "rStageRule",
            rule_name=f"sdlf-{p_teamname.value_as_string}-{p_pipelinename.value_as_string}-rule-{p_stagename.value_as_string}",
            description=f"Send events to {p_stagename.value_as_string} queue",
            event_bus=f"{{{{resolve:ssm:/SDLF/EventBridge/{p_teamname.value_as_string}/EventBusName}}}}",
            enabled=True if p_stageenabled.value_as_string.lower() == "true" else False,
            event_pattern=json.loads(p_eventpattern.value_as_string),
            targets=[
                targets.SqsQueue(
                    routing_queue,
                    message_group_id=f"{p_teamname.value_as_string}-{p_pipelinename.value_as_string}",
                    # InputPath: "$.detail" ? TODO
                )
            ],
        )

        routing_queue_policy = iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            principals=[
                iam.ServicePrincipal("events.amazonaws.com"),
            ],
            actions=["SQS:SendMessage"],
            resources=[routing_queue.queue_arn],
            conditions={"ArnEquals": {"aws:SourceArn": stage_rule.rule_arn}},
        )
        routing_queue.add_to_resource_policy(routing_queue_policy)  # TODO may be a cdk grant

        #         catalog_function.add_event_source(eventsources.SqsEventSource(catalog_queue, batch_size=10))
        #   rQueueLambdaEventSourceMapping:
        #     Type: AWS::Lambda::EventSourceMapping
        #     Condition: EventBased
        #     Properties:
        #       BatchSize: 10
        #       Enabled: True
        #       EventSourceArn: !GetAtt rQueueRoutingStep.Arn
        #       FunctionName: !Ref pLambdaRoutingStep

        poststateschedule_role_policy = iam.Policy(
            self,
            "sdlf-schedule",
            statements=[
                iam.PolicyStatement(
                    actions=["lambda:InvokeFunction"],
                    resources=[p_lambdaroutingstep.value_as_string, f"{p_lambdaroutingstep.value_as_string}:*"],
                ),
                iam.PolicyStatement(
                    actions=["kms:Decrypt"],
                    resources=[f"{{{{resolve:ssm:/SDLF/KMS/{p_teamname.value_as_string}/InfraKeyId}}}}"],
                ),
            ],
        )
        poststateschedule_role = iam.Role(
            self,
            "rPostStateScheduleRole",
            path=f"/sdlf-{p_teamname.value_as_string}/",
            assumed_by=iam.ServicePrincipal("scheduler.amazonaws.com"),
            permissions_boundary=f"{{{{resolve:ssm:/SDLF/IAM/{p_teamname.value_as_string}/TeamPermissionsBoundary}}}}",  # TODO
        )
        poststateschedule_role.attach_inline_policy(poststateschedule_role_policy)

        poststate_schedule = scheduler.CfnSchedule(
            self,
            "rPostStateSchedule",
            name=f"sdlf-{p_teamname.value_as_string}-{p_pipelinename.value_as_string}-schedule-rule-{p_stagename.value_as_string}",
            description=f"Trigger {p_stagename.value_as_string} Routing Lambda on a specified schedule",
            group_name=f"{{{{resolve:ssm:/SDLF/EventBridge/{p_teamname.value_as_string}/ScheduleGroupName}}}}",
            kms_key_arn=f"{{{{resolve:ssm:/SDLF/KMS/{p_teamname.value_as_string}/InfraKeyId}}}}",
            schedule_expression=p_schedule.value_as_string,
            flexible_time_window=scheduler.CfnSchedule.FlexibleTimeWindowProperty(
                mode="OFF",
            ),
            state="ENABLED" if p_stageenabled.value_as_string.lower() == "true" else "DISABLED",
            target=scheduler.CfnSchedule.TargetProperty(
                arn=f"arn:{self.partition}:scheduler:::aws-sdk:lambda:invoke",
                role_arn=poststateschedule_role.role_arn,
                # input=f'''
                #     {
                #         "FunctionName": "{p_lambdaroutingstep.value_as_string}",
                #         "InvocationType": "Event",
                #         "Payload": "{\n \"team\": \"{p_teamname.value_as_string}\",\n \"pipeline\": \"{p_pipelinename.value_as_string}\",\n \"pipeline_stage\": \"{p_stagename.value_as_string}\",\n \"trigger_type\": \"{p_triggertype.value_as_string}\",\n \"event_pattern\": \"true\",\n \"org\": \"{p_org.value_as_string}\",\n \"domain\": \"{p_domain.value_as_string}\",\n \"env\": \"{p_env.value_as_string}\"\n }"
                #     }
                #     '''
            ),
        )

        ssm.StringParameter(
            self,
            "rPipelineStageSsm",
            description=f"Placeholder {p_teamname.value_as_string} {p_pipelinename.value_as_string} {p_stagename.value_as_string}",
            parameter_name=f"/SDLF/Pipelines/{p_teamname.value_as_string}/{p_pipelinename.value_as_string}/{p_stagename.value_as_string}",
            simple_name=False,  # parameter name is a token
            string_value="placeholder",
        )

        # CloudFormation Outputs TODO
        CfnOutput(
            self,
            "oPipelineReference",
            description="CodePipeline reference this stack has been deployed with",
            value=p_pipelinereference.value_as_string,
        )
