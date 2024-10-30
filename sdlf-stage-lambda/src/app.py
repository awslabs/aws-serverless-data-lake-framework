#!/usr/bin/env python3

import os

import aws_cdk as cdk
from awslambda import StageLambda

# Project specific
project_name = os.getenv("SEEDFARMER_PROJECT_NAME", "")
deployment_name = os.getenv("SEEDFARMER_DEPLOYMENT_NAME", "")
module_name = os.getenv("SEEDFARMER_MODULE_NAME", "")

if project_name:
    stack_name = f"{project_name}-{deployment_name}-{module_name}"
    param_prefix = "SEEDFARMER_PARAMETER_"
else:  # app.py not used in a seedfarmer context somehow
    stack_name = "sdlf-stage-lambda"
    param_prefix = ""


def _param(name: str, default: str = None) -> str:
    return os.getenv(f"{param_prefix}{name}", default)


env = cdk.Environment(account=os.getenv("CDK_DEFAULT_ACCOUNT"), region=os.getenv("CDK_DEFAULT_REGION"))

app = cdk.App()
stack = cdk.Stack(app, stack_name, env=env)
stack_stagelambda = StageLambda(
    stack,
    "stagelambda",
    org=_param("ORG"),
    data_domain=_param("DATA_DOMAIN"),
    raw_bucket=_param("RAW_BUCKET"),
    stage_bucket=_param("STAGE_BUCKET"),
    infra_kms_key=_param("INFRA_KMS_KEY"),
    data_kms_key=_param("DATA_KMS_KEY"),
    transform=_param("TRANSFORM"),
    dataset=_param("DATASET"),
    pipeline=_param("PIPELINE"),
    stage=_param("STAGE"),
    trigger_type=_param("TRIGGER_TYPE"),
    event_bus=_param("EVENT_BUS"),
    event_pattern=_param("EVENT_PATTERN"),
)

cdk.CfnOutput(
    scope=stack,
    id="metadata",
    value=stack.to_json_string(stack_stagelambda.external_interface),
)

app.synth()
