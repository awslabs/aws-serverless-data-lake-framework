# Constructs

The core constructs available in the framework are detailed in this section.

## Available Constructs

- [sdlf-foundations](foundations.md)
- [sdlf-team](team.md)
- [sdlf-pipeline](pipeline.md)
- [sdlf-stageA](stage-lambda.md)
- [sdlf-stageB](stage-glue.md)
- [sdlf-stage-dataquality](stage-dataquality.md)
- [sdlf-dataset](dataset.md)

![SDLF Constructs](../_static/sdlf-constructs.png)

## VPC Networking

All SDLF constructs can work in VPC environments where outbound Internet access is constrained. They consume networking details from specific SSM string parameters:

- `/SDLF/VPC/VpcId` (`vpc-xxx`)
- `/SDLF/VPC/SecurityGroupIds` (`sg-xxx,sg-yyy`)
- `/SDLF/VPC/SubnetIds` (`subnet-xxx,subnet-yyy`)

!!! warning
    SDLF does not create the VPC infrastructure itself - VPC, subnets, security groups, VPC endpoints need creating ahead of time.

The following VPC endpoints, **with DNS name enabled**, are necessary for the current set of constructs:

- `com.amazonaws.{region}.athena` (interface)
- `com.amazonaws.{region}.codepipeline` (interface)
- `com.amazonaws.{region}.dynamodb` (gateway)
- `com.amazonaws.{region}.ec2messages` (interface)
- `com.amazonaws.{region}.events` (interface)
- `com.amazonaws.{region}.glue` (interface)
- `com.amazonaws.{region}.kms` (interface)
- `com.amazonaws.{region}.lambda` (interface)
- `com.amazonaws.{region}.logs` (interface)
- `com.amazonaws.{region}.s3` (gateway)
- `com.amazonaws.{region}.secretsmanager` (interface)
- `com.amazonaws.{region}.sns` (interface)
- `com.amazonaws.{region}.sqs` (interface)
- `com.amazonaws.{region}.ssm` (interface)
- `com.amazonaws.{region}.ssmmessages` (interface)
- `com.amazonaws.{region}.states` (interface)
- `com.amazonaws.{region}.sts` (interface)

The security groups used for interface endpoints must allow inbound access from the security groups provided to SDLF constructs. The security groups provided to SDLF constructs must allow outbound access to the security groups used for interface endpoints.

## sdlf-datalakeLibrary

`sdlf-datalakeLibrary` is a Python library that can be used to interact with the data lake, in particular with the SSM parameters the different modules are publishing and the DynamoDB tables created in `sdlf-foundations`. If using `sdlf-cicd`, a Lambda layer containing `sdlf-datalakeLibrary` is built and used in `sdlf-stageA` and `sdlf-stageB`.

## Transformations

Aforementioned constructs referred to `infrastructure` code. Transformations on the other hand represent the `application` code ran within the steps of a SDLF pipeline. They include instructions to:

- Make an API call to another service (on or outside the AWS platform)
- Store dataset and pipeline execution metadata in a catalog
- Collect logs and store them in ElasticSearch
- ... any other logic

Once transformations and other application code is pushed to the team respository, it goes through a CodePipeline and can be submitted to testing before it enters production.

!!! note
    A SDLF team can define and manage their transformations from the `sdlf-main-{domain}-{team}` repository if using `sdlf-cicd`.

!!! note
    Transformations enable decoupling between a SDLF pipeline and a dataset. It means that a single pipeline can process multiple datasets.
