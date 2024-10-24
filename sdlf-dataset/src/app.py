#!/usr/bin/env python3

import os

import aws_cdk as cdk
from dataset import Dataset

# Project specific
project_name = os.getenv("SEEDFARMER_PROJECT_NAME", "")
deployment_name = os.getenv("SEEDFARMER_DEPLOYMENT_NAME", "")
module_name = os.getenv("SEEDFARMER_MODULE_NAME", "")

if project_name:
    stack_name = f"{project_name}-{deployment_name}-{module_name}"
else:  # app.py not used in a seedfarmer context somehow
    stack_name = "sdlf-dataset"

app = cdk.App()
lakeformation_cicd_stack = cdk.Stack(app, f"{stack_name}-lakeformation")

cdk.aws_lakeformation.CfnDataLakeSettings(
    lakeformation_cicd_stack,
    "rDataLakeSettings",
    admins=[
        cdk.aws_lakeformation.CfnDataLakeSettings.DataLakePrincipalProperty(
            data_lake_principal_identifier=cdk.Fn.sub(
                lakeformation_cicd_stack.synthesizer.cloud_formation_execution_role_arn
            )
        ),
    ],
    mutation_type="APPEND",
)

stack = cdk.Stack(app, stack_name)
stack.add_dependency(lakeformation_cicd_stack)
Dataset(stack, "dataset")

app.synth()
