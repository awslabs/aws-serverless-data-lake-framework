# README 
This repository contains the code that enables the deployment of a new dataset.
This is an alternative to the main sdlf-dataset repository, that enables you to maintain the history of the deployed datasets, in a single folder.
Using this repo instead of the original one you will have only one `parameters` folder, and will create there as much parameters as datasets you have. Instead of having a folder per environment.

- To be able to use this approach as initial setup you only need replace the entire content of the main repository `sdlf-dataset` with all the content in the preset folder `alternative-sdlf-dataset`, and use it as explained in the main documentation.

- To be able to deploy in different environments (dev, test, prod), you should ensure you are pushing your changes to the corresponding branch (dev. test, master).

## Motivation
Usually you need to deploy not a single dataset but many, so to have a single parameters-$ENV.json file per environment forces you to change the json descriptor each time you need to deploy a new dataset, losing the Jsons that were used to deploy the above datasets.
In the day to day work with the framework, it is common the need to re-deploy the same dataset several times, after a minor change, specially in the dev environment, and rewrite the Json descriptor file each time is not an optimal way to do that.
Instead of having a single json, we propose to have a folder with one Json file per dataset.
That way the template creates the necessary resources for each dataset from the parameters defined in a parameters/parameters-$DATASET.json file in the parameters folder, the dataset will be deployed only if it has changed since the last commit, that way we have in the parameters folder the history of all the deployed datasets.
The resources will be created depending on the branch (dev, test, master) in the corresponding environment/account (dev,test,prod), so no specific environment is necessary in the parameters file name itself.


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
