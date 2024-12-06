# Serverless Data Lake Framework (SDLF)

## Table of Contents

### Required

1. [Overview](#overview-required)
    - [Cost](#cost)
2. [Prerequisites](#prerequisites-required)
3. [Deployment Steps](#deployment-steps-required)
4. [Deployment Validation](#deployment-validation-required)
5. [Running the Guidance](#running-the-guidance-required)
6. [Next Steps](#next-steps-required)
7. [Cleanup](#cleanup-required)

## Overview

An [AWS Professional Service](https://aws.amazon.com/professional-services/) open source initiative | aws-proserve-opensource@amazon.com

<img align="left" src="docs/_static/sail-icon.png" width="50" height="44"> The Serverless Data Lake Framework (SDLF) is a collection of reusable artifacts aimed at accelerating the delivery of enterprise data lakes on AWS, shortening the deployment time to production from several months to a few weeks. It can be used by AWS teams, partners and customers to implement the foundational structure of a data lake following best practices.

A data lake gives your organization agility. It provides a repository where consumers can quickly find the data they need and use it in their business projects. However, building a data lake can be complex; there's a lot to think about beyond the storage of files. For example, how do you catalog the data so you know what you've stored? What ingestion pipelines do you need? How do you manage data quality? How do you keep the code for your transformations under source control? How do you manage development, test and production environments? Building a solution that addresses these use cases can take many weeks and this time can be better spent innovating with data and achieving business goals.

![AWS Serverless Data Lake Framework](docs/_static/sdlf-layers-architecture.png?raw=true "AWS Serverless Data Lake Framework")

To learn more about SDLF, its constructs and data architectures, please visit the following pages:
- [Constructs](https://sdlf.readthedocs.io/en/latest/constructs/)
- [Architecture](https://sdlf.readthedocs.io/en/latest/architecture/)

### Cost

You are responsible for the cost of the AWS services used while running this Guidance. As of December 2024, the cost for running this guidance with the default settings in the eu-west-1 region (Ireland) is approximately $15 per month.

We recommend creating a [Budget](https://docs.aws.amazon.com/cost-management/latest/userguide/budgets-managing-costs.html) through [AWS Cost Explorer](https://aws.amazon.com/aws-cost-management/aws-cost-explorer/) to help manage costs. Prices are subject to change. For full details, refer to the pricing webpage for each AWS service used in this Guidance.


### Sample Cost Table

The following table provides a sample cost breakdown for deploying this guidance with the default parameters in the eu-west-1 region (Ireland) for one month.

| AWS service  | Dimensions | Cost [USD] |
| ----------- | ------------ | ------------ |
| Amazon S3 | 100,000 PUT, COPY, POST, LIST requests to S3 Standard per month  | $3.50 |
| AWS Glue ETL jobs | 10 DPU per job | $0.75 |
| AWS Glue Crawlers | 3 crawlers | $0.50 |
| AWS Lambda | 180 requests per month| $0 |
| AWS Step Functions | 30 workflow requests and 10 state transitions per workflow, per month | $0 |
| Amazon EventBridge | 150 schedule invocations per month | $0 |
| Amazon Athena | 30 queries per month | $0 |
| AWS Lake Formation | - | $0 |
| Amazon SQS | 1 million FIFO queue requests | $0 |
| Amazon DynamoDB | 1 GB data storage size, 1 KB average item size| $1.05 |
| AWS KMS | 5 customer managed Customer Master Keys (CMK) with 2000000 symmetric requests per month | $11.00 |


## Prerequisites

AWS CloudShell can be used to deploy SDLF.

* git
* AWS CLI
* IAM deployment role

## Deployment Steps

**It is recommended to use the [latest stable release](https://github.com/awslabs/aws-serverless-data-lake-framework/releases) when setting up SDLF.**

**For users of SDLF 1.x, version 1 is still available on the [master branch](https://github.com/awslabs/aws-serverless-data-lake-framework/tree/master). Development of newer versions of SDLF (2.x) happens on branch main. The workshop still contains sections for version 1 as well.**

1. Get the latest stable release of SDLF, unarchive it and cd to the new folder:
```
curl -L -O https://github.com/awslabs/aws-serverless-data-lake-framework/archive/refs/tags/2.8.0.tar.gz
tar xzf 2.8.0.tar.gz
cd ./aws-serverless-data-lake-framework-2.8.0/
```

2. Deploy the CodeBuild projects for bootstrapping the rest of the infrastructure:
```
cd sdlf-cicd/
./deploy-generic.sh -p aws_profile_name datalake
```

3. Start the `sdlf-cicd-bootstrap` project and wait for it to complete. It publishes CloudFormation modules for each component of SDLF.
4. Start the `sdlf-cicd-datalake` project and wait for it to complete. It creates an end-to-end data lake infrastructure, including data processing and consumption services.


## Deployment Validation

As you follow the workshop, after each step there is a section helping you validate your deployment.

* In Amazon S3, look for the Raw, Stage, and Analytics buckets, as well as utility storage with the Logs, Artifacts and Athena buckets.
* The Lake Formation access control model was also enabled in the data lake. In AWS Lake Formation, under Administration → Data lake locations, the three storage layers (raw, stage, analytics) should appear.
* Under Data Catalog in the AWS Glue console or in the AWS Lake Formation, three databases should be visible.
* Corresponding Glue crawlers to help populate these catalogs with metadata such as tables. They should be listed under Data Catalog → Crawlers in the AWS Glue console.
* Two Step Functions state machines should be visible.
* An Athena workgroup should have been created.

## Running the Guidance

The [SDLF workshop](https://sdlf.workshop.aws/) walks you through the deployment of a data lake. It includes multiple steps:
* Prerequisites (Initial setup)
* Data and utility storage using S3 (Deploying storage layers)
* Data cataloging with Glue Data catalog (Cataloging data)
* Data processing using AWS Step Functions, Lambda functions and Glue ETL (Processing data)
* Data consumption with Amazon Athena (Consuming data)

## Cleanup

Cleanup is described in the workshop in the [Cleanup section](https://catalog.us-east-1.prod.workshops.aws/workshops/501cb14c-91b3-455c-a2a9-d0a21ce68114/en-US/10-demo/600-clean-up). Essentially it boils down to:

* Emptying the content of all SDLF buckets
* Removing all SDLF CloudFormation stacks
* Removing KMS keys and aliases created by SDLF

After completion of these steps, no SDLF artifacts are left.

## Authors

Cyril Fait, Abiola Babsalaam, Debaprasun Chakraborty, Navin Irimpan, Shakti Singh Shekhawat, Judith Joseph and [open source contributors](https://github.com/awslabs/aws-serverless-data-lake-framework/graphs/contributors).

## Customers using the SDLF

![AWS Serverless Data Lake Framework](docs/_static/public-references.png?raw=true "AWS Serverless Data Lake Framework")
*If you would like us to include your company’s name and/or logo in the README file to indicate that your company is using the AWS Serverless Data Lake Framework, please raise a "Support the SDLF" issue. If you would like us to display your company’s logo, please raise a linked pull request to provide an image file for the logo. Note that by raising a Support the SDLF issue (and related pull request), you are granting AWS permission to use your company’s name (and logo) for the limited purpose described here and you are confirming that you have authority to grant such permission.*
