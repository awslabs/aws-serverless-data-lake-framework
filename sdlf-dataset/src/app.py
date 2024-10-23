#!/usr/bin/env python3

import aws_cdk as cdk

from dataset import Dataset

app = cdk.App()

lakeformation_cicd_stack = cdk.Stack(app, "LakeFormationDatasetStack")

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

stack = cdk.Stack(app, "DatasetStack")
stack.add_dependency(lakeformation_cicd_stack)
Dataset(stack, "dataset")

app.synth()
