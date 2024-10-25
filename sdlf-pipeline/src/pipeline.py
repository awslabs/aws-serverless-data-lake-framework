# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT

import json

from aws_cdk import (
    CfnOutput,
    CfnParameter,
    Duration,
    RemovalPolicy,
)
from aws_cdk import aws_events as events
from aws_cdk import aws_events_targets as targets
from aws_cdk import aws_iam as iam
from aws_cdk import aws_kms as kms
from aws_cdk import aws_scheduler as scheduler
from aws_cdk import aws_sqs as sqs
from aws_cdk import aws_ssm as ssm
from constructs import Construct


class Pipeline(Construct):
    p_datasetname = None
    p_pipeline = None
    p_stagename = None
    p_stageenabled = None
    p_triggertype = None
    p_schedule = None
    p_eventpattern = None

    def resources(self, scope: Construct, lambda_routingstep) -> None:
        routing_dlq = sqs.Queue(
            self,
            "rDeadLetterQueueRoutingStep",
            removal_policy=RemovalPolicy.DESTROY,
            queue_name=f"sdlf-{self.p_datasetname.value_as_string}-{self.p_pipeline.value_as_string}-dlq-{self.p_stagename.value_as_string}.fifo",
            fifo=True,
            retention_period=Duration.days(14),
            visibility_timeout=Duration.seconds(60),
            encryption_master_key=kms.Key.from_key_arn(
                self,
                "rDeadLetterQueueRoutingStepEncryption",
                key_arn=f"{{{{resolve:ssm:/SDLF/KMS/{self.p_datasetname.value_as_string}/InfraKeyId}}}}",
            ),
        )
        ssm.StringParameter(
            self,
            "rDeadLetterQueueRoutingStepSsm",
            description=f"Name of the {self.p_stagename.value_as_string} {self.p_datasetname.value_as_string} {self.p_pipeline.value_as_string} DLQ",
            parameter_name=f"/SDLF/SQS/{self.p_datasetname.value_as_string}/{self.p_pipeline.value_as_string}{self.p_stagename.value_as_string}DLQ",
            simple_name=False,  # parameter name is a token
            string_value=routing_dlq.queue_name,
        )

        routing_queue = sqs.Queue(
            self,
            "rQueueRoutingStep",
            removal_policy=RemovalPolicy.DESTROY,
            queue_name=f"sdlf-{self.p_datasetname.value_as_string}-{self.p_pipeline.value_as_string}-queue-{self.p_stagename.value_as_string}.fifo",
            fifo=True,
            content_based_deduplication=True,
            retention_period=Duration.days(7),
            visibility_timeout=Duration.seconds(60),
            encryption_master_key=kms.Key.from_key_arn(
                self,
                "rQueueRoutingStepEncryption",
                key_arn=f"{{{{resolve:ssm:/SDLF/KMS/{self.p_datasetname.value_as_string}/InfraKeyId}}}}",
            ),
            dead_letter_queue=sqs.DeadLetterQueue(
                max_receive_count=1,
                queue=routing_dlq,
            ),
        )
        ssm.StringParameter(
            self,
            "rQueueRoutingStepSsm",
            description=f"Name of the {self.p_stagename.value_as_string} {self.p_datasetname.value_as_string} {self.p_pipeline.value_as_string} Queue",
            parameter_name=f"/SDLF/SQS/{self.p_datasetname.value_as_string}/{self.p_pipeline.value_as_string}{self.p_stagename.value_as_string}Queue",
            simple_name=False,  # parameter name is a token
            string_value=routing_dlq.queue_name,
        )

        stage_rule = events.Rule(
            self,
            "rStageRule",
            rule_name=f"sdlf-{self.p_datasetname.value_as_string}-{self.p_pipeline.value_as_string}-rule-{self.p_stagename.value_as_string}",
            description=f"Send events to {self.p_stagename.value_as_string} queue",
            event_bus=events.EventBus.from_event_bus_name(
                self,
                "rStageRuleEventBus",
                f"{{{{resolve:ssm:/SDLF/EventBridge/{self.p_datasetname.value_as_string}/EventBusName}}}}",
            ),
            enabled=True if self.p_stageenabled.value_as_string.lower() == "true" else False,
            #            event_pattern=json.loads(self.p_eventpattern.value_as_string),  # TODO { "source": ["aws.states"] }
            event_pattern={"source": ["aws.states"]},
            targets=[
                targets.SqsQueue(
                    routing_queue,
                    message_group_id=f"{self.p_datasetname.value_as_string}-{self.p_pipeline.value_as_string}",
                    message=events.RuleTargetInput.from_event_path("$.detail"),
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
                    resources=[lambda_routingstep, f"{lambda_routingstep}:*"],
                ),
                iam.PolicyStatement(
                    actions=["kms:Decrypt"],
                    resources=[f"{{{{resolve:ssm:/SDLF/KMS/{self.p_datasetname.value_as_string}/InfraKeyId}}}}"],
                ),
            ],
        )
        poststateschedule_role = iam.Role(
            self,
            "rPostStateScheduleRole",
            path=f"/sdlf-{self.p_datasetname.value_as_string}/",
            assumed_by=iam.ServicePrincipal("scheduler.amazonaws.com"),
            permissions_boundary=iam.ManagedPolicy.from_managed_policy_arn(
                self,
                "rPostStateScheduleRolePermissionsBoundary",
                managed_policy_arn=f"{{{{resolve:ssm:/SDLF/IAM/{self.p_datasetname.value_as_string}/TeamPermissionsBoundary}}}}",
            ),
        )
        poststateschedule_role.attach_inline_policy(poststateschedule_role_policy)

        poststate_schedule_input = {
            "FunctionName": lambda_routingstep,
            "InvocationType": "Event",
            "Payload": json.dumps(
                {
                    "dataset": self.p_datasetname.value_as_string,
                    "pipeline": self.p_pipeline.value_as_string,
                    "pipeline_stage": self.p_stagename.value_as_string,
                    "trigger_type": self.p_triggertype.value_as_string,
                    "event_pattern": "true",
                    "org": self.p_org.value_as_string,
                    "domain": self.p_domain.value_as_string,
                    "env": self.p_env.value_as_string,
                }
            ),
        }
        scheduler.CfnSchedule(
            self,
            "rPostStateSchedule",
            name=f"sdlf-{self.p_datasetname.value_as_string}-{self.p_pipeline.value_as_string}-schedule-rule-{self.p_stagename.value_as_string}",
            description=f"Trigger {self.p_stagename.value_as_string} Routing Lambda on a specified schedule",
            group_name=f"{{{{resolve:ssm:/SDLF/EventBridge/{self.p_datasetname.value_as_string}/ScheduleGroupName}}}}",
            kms_key_arn=f"{{{{resolve:ssm:/SDLF/KMS/{self.p_datasetname.value_as_string}/InfraKeyId}}}}",
            schedule_expression=self.p_schedule.value_as_string,
            flexible_time_window=scheduler.CfnSchedule.FlexibleTimeWindowProperty(
                mode="OFF",
            ),
            state="ENABLED" if self.p_stageenabled.value_as_string.lower() == "true" else "DISABLED",
            target=scheduler.CfnSchedule.TargetProperty(
                arn=f"arn:{scope.partition}:scheduler:::aws-sdk:lambda:invoke",
                role_arn=poststateschedule_role.role_arn,
                input=json.dumps(poststate_schedule_input),
            ),
        )

        ssm.StringParameter(
            self,
            "rPipelineStageSsm",
            description=f"Placeholder {self.p_datasetname.value_as_string} {self.p_pipeline.value_as_string} {self.p_stagename.value_as_string}",
            parameter_name=f"/SDLF/Pipelines/{self.p_datasetname.value_as_string}/{self.p_pipeline.value_as_string}/{self.p_stagename.value_as_string}",
            simple_name=False,  # parameter name is a token
            string_value="placeholder",
        )

    def __init__(self, scope: Construct, id: str, **kwargs) -> None:
        super().__init__(scope, id)

        # using context values would be better(?) for CDK but we haven't decided yet what the story is around ServiceCatalog and CloudFormation modules
        # perhaps both (context values feeding into CfnParameter) would be a nice-enough solution. Not sure though. TODO
        self.p_pipelinereference = CfnParameter(
            self,
            "pPipelineReference",
            type="String",
            default="none",
        )
        self.p_pipelinereference.override_logical_id("pPipelineReference")
        self.p_org = CfnParameter(
            self,
            "pOrg",
            description="Name of the organization owning the datalake",
            type="String",
            default="{{resolve:ssm:/SDLF/Misc/pOrg:1}}",
        )
        self.p_org.override_logical_id("pOrg")
        self.p_domain = CfnParameter(
            self,
            "pDomain",
            description="Data domain name",
            type="String",
            default="{{resolve:ssm:/SDLF/Misc/pDomain:1}}",
        )
        self.p_domain.override_logical_id("pDomain")
        self.p_env = CfnParameter(
            self, "pEnv", description="Environment name", type="String", default="{{resolve:ssm:/SDLF/Misc/pEnv:1}}"
        )
        self.p_env.override_logical_id("pEnv")
        self.p_datasetname = CfnParameter(
            self,
            "pDatasetName",
            description="Name of the dataset (all lowercase, no symbols or spaces)",
            type="String",
            allowed_pattern="[a-z0-9]{2,14}",
        )
        self.p_datasetname.override_logical_id("pDatasetName")
        self.p_pipeline = CfnParameter(
            self,
            "pPipelineName",
            description="The name of the pipeline (all lowercase, no symbols or spaces)",
            type="String",
            allowed_pattern="[a-z0-9]*",
        )
        self.p_pipeline.override_logical_id("pPipeline")
        self.p_stagename = CfnParameter(
            self,
            "pStageName",
            description="Name of the stage (all lowercase, hyphen allowed, no other symbols or spaces)",
            type="String",
            allowed_pattern="[a-zA-Z0-9\\-]{1,12}",
        )
        self.p_stagename.override_logical_id("pStageName")
        self.p_stageenabled = CfnParameter(
            self,
            "pStageEnabled",
            description="Whether the stage is enabled or not",
            type="String",
            allowed_values=["true", "false"],
        )
        self.p_stageenabled.override_logical_id("pStageEnabled")
        self.p_triggertype = CfnParameter(
            self,
            "pTriggerType",
            description="Trigger type of the stage (event or schedule)",
            type="String",
            allowed_values=["event", "schedule"],
            default="event",
        )
        self.p_triggertype.override_logical_id("pTriggerType")
        self.p_schedule = CfnParameter(
            self,
            "pSchedule",
            description="Cron expression when trigger type is schedule",
            type="String",
            default="cron(*/5 * * * ? *)",
        )
        self.p_schedule.override_logical_id("pSchedule")
        self.p_eventpattern = CfnParameter(
            self,
            "pEventPattern",
            description="Event pattern to match from previous stage",
            type="String",
            default="",
        )
        self.p_eventpattern.override_logical_id("pEventPattern")

        # CloudFormation Outputs TODO
        o_pipelinereference = CfnOutput(
            self,
            "oPipelineReference",
            description="CodePipeline reference this stack has been deployed with",
            value=self.p_pipelinereference.value_as_string,
        )
        o_pipelinereference.override_logical_id("oPipelineReference")
