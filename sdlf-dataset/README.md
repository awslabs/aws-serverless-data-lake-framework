# README 
This repository contains the code that enables the deployment of a new dataset.
 
## Prerequisites
Before attempting to deploy a dataset, ensure that both the **FOUNDATIONS** and **PIPELINE** infrastructure has completed its provisioning, and has been successfully deployed. They contain infrastructure resources that the **DATASET**  stack depends on, and without them in place, the deployment of this stack will fail. These resources include:
1. IAM roles
2. The Glue data catalog
3. CodeBuild jobs
4. S3 buckets

## Deploying a dataset

### Parameters
Before deploying a new dataset, ensure that the `parameters/parameters-$DATASET.json` file contains the following parameters that **DATASET** requires:

1. `pTeamName` [***REQUIRED***] — Name of the team as defined in `common-team` that will be owning this dataset.
1. `pPipelineName` [***REQUIRED***] — Name of the pipeline as defined in `common-pipeline` that will be processing this dataset.
1. `pDatasetName` [***REQUIRED***] — Name to give the dataset being deployed. Pick a name that refers to a group of data with a common schema or datasource (e.g. telemetry, orders...). This name will be used as an S3 prefix.
1. `pCreateDatabase` [***OPTIONAL***] — Create a database if True, it will not create if False, Creates or not a glue data catalog database for the dataset and a carwler.
1. `pScheduleExpression` [***OPTIONAL***] — Schedule Expression to trigger the stage B stage of the example pipeline "main" i.e. cron(0 12 * * ? *)

The required parameters MUST be defined in a `parameters/parameters-$DATASET.json` file. The file should look like the following:

    [
        {
            "ParameterKey": "pTeamName",
            "ParameterValue": "<teamName>"
        },
        {
            "ParameterKey": "pPipelineName",
            "ParameterValue": "<pipelineName>"
        },
        {
            "ParameterKey": "pDatasetName",
            "ParameterValue": "<datasetName>"
        },
        {
            "ParameterKey": "pCreateDatabase",
            "ParameterValue": "True"
        },
        {
            "ParameterKey": "pScheduleExpression",
            "ParameterValue": "cron(*/5 * * * ? *)"
        }
    ]

A tags.json file in the same directory can also be amended to tag all resources deployed by CloudFormation.

### Deployment
To deploy a new dataset you should:
1. Create a new `parameters/parameters-$DATASET.json` file.
1. Commit and push it in the repo sdlf-$TEAM-dataset, in the desired branch, corresponding to the desired environment/account (dev,test,master).
1. Wait for the code pipeline and the corresponding cloudFormation stack to complete the deployment of all the infrastructure before proceeding further.

## Architecture

This template creates the necessary resources for each dataset from the parameters defined in a `parameters/parameters-$DATASET.json` file in the parameters folder, the dataset in will be deployed only if it has changed since the last commit, that way we have a in the parameters folder the history of all the deployed datasets.
The resources will be created depending on the branch (dev, test, master) in the corresponding environment/account (dev,test,prod).

This template creates the following resources:
1. SQS Queues - Hold dataset specific messages awaiting to be processed in the next stage
   1. `QueuePostStepRouting`
   2. `DeadLetterQueuePostStepRouting`
2. CloudWatch Rules - Triggers the the next stage pipeline every X minutes to process the dataset messages from the queue (depending on the parameter)
3. Glue crawler (depending on the parameter)
