# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT

import json

from aws_cdk import (
    #    CfnOutput,
    Duration,
    RemovalPolicy,
)
from aws_cdk import aws_events as events
from aws_cdk import aws_events_targets as targets
from aws_cdk import aws_iam as iam
from aws_cdk import aws_kms as kms
from aws_cdk import aws_lambda as _lambda
from aws_cdk import aws_scheduler as scheduler
from aws_cdk import aws_sqs as sqs
from aws_cdk import aws_ssm as ssm
from constructs import Construct

from aws_cdk.aws_lambda_event_sources import SqsEventSource

class Pipeline(Construct):
    external_interface = {}

    def __init__(
        self,
        scope: Construct,
        id: str,
        dataset: str,
        pipeline: str,
        stage: str,
        trigger_type: str,
        trigger_target: str, # here, a lambda arn. later: eventbridge universal target
        kms_key: str,
        stage_enabled: bool = True,
        schedule: str = None, # only used if schedule or event-schedule
        event_pattern: str = None, # only used if event or event-schedule
        event_bus: str = "default", # can be default
        schedule_group: str = "default", # can be default
        # permissions boundary yeah well...
        **kwargs,
    ) -> None:
        super().__init__(scope, id)

        # Pipeline stages have three types of triggers: event, event-schedule, schedule
        # event: run stage when an event received on the team's event bus matches the configured event pattern
        # event-schedule: store events received on the team's event bus matching the configured event pattern, then process them on the configured schedule
        # schedule: run stage on the configured schedule, without any event as input

        if event_pattern: # infra needed for event and event-schedule (trigger-type in ["event", "schedule"], and event_pattern specified)
            routing_dlq_resource_name = "rDeadLetterQueueRoutingStep"
            routing_dlq = sqs.Queue(
                self,
                routing_dlq_resource_name,
                removal_policy=RemovalPolicy.DESTROY,
                queue_name=f"sdlf-{dataset}-{pipeline}-dlq-{stage}.fifo",
                fifo=True,
                retention_period=Duration.days(14),
                visibility_timeout=Duration.seconds(60),
                encryption_master_key=kms.Key.from_key_arn(
                    self,
                    "rDeadLetterQueueRoutingStepEncryption",
                    key_arn=kms_key,
                ),
            )
            self._external_interface(
                routing_dlq_resource_name,
                f"Name of the {stage} {dataset} {pipeline} DLQ",
                routing_dlq.queue_name,
            )

            routing_queue_resource_name = "rQueueRoutingStep"
            routing_queue = sqs.Queue(
                self,
                routing_queue_resource_name,
                removal_policy=RemovalPolicy.DESTROY,
                queue_name=f"sdlf-{dataset}-{pipeline}-queue-{stage}.fifo",
                fifo=True,
                content_based_deduplication=True,
                retention_period=Duration.days(7),
                visibility_timeout=Duration.seconds(60),
                encryption_master_key=kms.Key.from_key_arn(
                    self,
                    "rQueueRoutingStepEncryption",
                    key_arn=kms_key,
                ),
                dead_letter_queue=sqs.DeadLetterQueue(
                    max_receive_count=1,
                    queue=routing_dlq,
                ),
            )
            self._external_interface(
                routing_queue_resource_name,
                f"Name of the {stage} {dataset} {pipeline} Queue",
                routing_dlq.queue_name,
            )

            stage_rule = events.Rule(
                self,
                "rStageRule",
                rule_name=f"sdlf-{dataset}-{pipeline}-rule-{stage}",
                description=f"Send events to {stage} queue",
                event_bus=events.EventBus.from_event_bus_name(
                    self,
                    "rStageRuleEventBus",
                    event_bus,
                ),
                enabled=stage_enabled,
                event_pattern={key.replace("-", "_"): value for key,value in json.loads(event_pattern).items()}, # events.EventPattern(**json.loads(event_pattern)), #{"source": ["aws.states"]},
                targets=[
                    targets.SqsQueue(
                        routing_queue,
                        message_group_id=f"{dataset}-{pipeline}",
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

        if trigger_type == "event" and event_pattern: # infra needed for event only
            _lambda.Function.from_function_arn(self, "rRoutingLambda", function_arn=trigger_target).add_event_source(SqsEventSource(routing_queue, batch_size=10))

        if schedule: # infra needed for event-schedule and schedule (trigger-type in ["event", "schedule"], and schedule specified)
            poststateschedule_role_policy = iam.Policy(
                self,
                "sdlf-schedule",
                statements=[
                    iam.PolicyStatement(
                        actions=["lambda:InvokeFunction"],
                        resources=[trigger_target, f"{trigger_target}:*"],
                    ),
                    iam.PolicyStatement(
                        actions=["kms:Decrypt"],
                        resources=[kms_key],
                    ),
                ],
            )
            poststateschedule_role = iam.Role(
                self,
                "rPostStateScheduleRole",
                path=f"/sdlf-{dataset}/",
                assumed_by=iam.ServicePrincipal("scheduler.amazonaws.com"),
                # permissions_boundary=iam.ManagedPolicy.from_managed_policy_arn(
                #     self,
                #     "rPostStateScheduleRolePermissionsBoundary",
                #     managed_policy_arn=f"{{{{resolve:ssm:/sdlf/IAM/{dataset}/TeamPermissionsBoundary}}}}",
                # ),
            )
            poststateschedule_role.attach_inline_policy(poststateschedule_role_policy)

            poststate_schedule_input = {
                "FunctionName": trigger_target,
                "InvocationType": "Event",
                "Payload": json.dumps(
                    {
                        "dataset": dataset,
                        "pipeline": pipeline,
                        "pipeline_stage": stage,
                        "trigger_type": trigger_type,
                        "event_pattern": "true",  # TODO not too sure passing org, domain, is that useful, maybe others too
                        "domain": data_domain,
                        "org": org,
                    }
                ),
            }
            scheduler.CfnSchedule(
                self,
                "rPostStateSchedule",
                name=f"sdlf-{dataset}-{pipeline}-schedule-rule-{stage}",
                description=f"Trigger {stage} Routing Lambda on a specified schedule",
                group_name=schedule_group,
                kms_key_arn=kms_key,
                schedule_expression=schedule,
                flexible_time_window=scheduler.CfnSchedule.FlexibleTimeWindowProperty(
                    mode="OFF",
                ),
                state="ENABLED" if stage_enabled.lower() == "true" else "DISABLED",
                target=scheduler.CfnSchedule.TargetProperty(
                    arn=f"arn:{scope.partition}:scheduler:::aws-sdk:lambda:invoke",
                    role_arn=poststateschedule_role.role_arn,
                    input=json.dumps(poststate_schedule_input),
                ),
            )

        # CloudFormation Outputs TODO
        # o_pipelinereference = CfnOutput(
        #     self,
        #     "oPipelineReference",
        #     description="CodePipeline reference this stack has been deployed with",
        #     value=p_pipelinereference.value_as_string,
        # )
        # o_pipelinereference.override_logical_id("oPipelineReference")

    def _external_interface(self, resource_name, description, value):
        ssm.StringParameter(
            self,
            f"{resource_name}Ssm",
            description=description,
            parameter_name=f"/sdlf/pipeline/{resource_name}",
            string_value=value,
        )
        self.external_interface[resource_name] = value
