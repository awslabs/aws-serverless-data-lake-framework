#!/usr/bin/env python3

import os

import aws_cdk as cdk
from foundations import Foundations

# Project specific
project_name = os.getenv("SEEDFARMER_PROJECT_NAME", "")
deployment_name = os.getenv("SEEDFARMER_DEPLOYMENT_NAME", "")
module_name = os.getenv("SEEDFARMER_MODULE_NAME", "")

if project_name:
    stack_name = f"{project_name}-{deployment_name}-{module_name}"
    param_prefix = "SEEDFARMER_PARAMETER_"
else:  # app.py not used in a seedfarmer context somehow
    stack_name = "sdlf-foundations"
    param_prefix = ""


def _param(name: str, default: str = None) -> str:
    return os.getenv(f"{param_prefix}{name}", default)


app = cdk.App()
stack = cdk.Stack(app, stack_name)
stack_foundations = Foundations(
    stack,
    "foundations",
    org=_param("ORG"),
    data_domain=_param("DATA_DOMAIN"),
    account_id=os.getenv("CDK_DEFAULT_ACCOUNT"),
)

cdk.CfnOutput(
    scope=stack,
    id="metadata",
    value=stack.to_json_string(stack_foundations.external_interface),
)

app.synth()
