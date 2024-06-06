# AWS Serverless Data Lake Framework

Serverless Data Lake Framework (SDLF) is a collection of reusable artifacts aimed at accelerating the delivery of enterprise data lakes on AWS, shortening the deployment time to production from several months to a few weeks. It can be used by AWS teams, partners and customers to implement the foundational structure of a data lake following best practices.

## Motivation

A data lake gives your organization agility. It provides a repository where consumers can quickly find the data they need and use it in their business projects. However, building a data lake can be complex; there's a lot to think about beyond the storage of files. For example, how do you catalog the data so you know what you've stored? What ingestion pipelines do you need? How do you manage data quality? How do you keep the code for your transformations under source control? How do you manage development, test and production environments? Building a solution that addresses these use cases can take many weeks and this time can be better spent innovating with data and achieving business goals.

SDLF is a collection of production-hardened, best-practices templates which accelerate your data lake implementation journey on AWS, so that you can focus on use cases that generate value for business.

## Major Features

At a high level, SDLF is an infrastructure-as-code framework that enables customers to create:

- End-to-end data architectures such as a centralized (transactional) data lake or a data mesh
- Foundational data lake assets (e.g. Amazon S3 buckets for data storage)
- Event-driven jobs that orchestrate the transformation of data, storing the output in a new location on S3
- Data processing stages using AWS serverless services such as Lambda or Glue
- Git-driven deployment pipelines (CICD) for the entire data infrastructure

Using all SDLF features as illustrated in the [official workshop](https://sdlf.workshop.aws/) gives you:

1. **Traceability and version control**:
    - SDLF is entirely managed through CICD pipelines. At no point is interaction with the AWS console necessary (in fact it's discouraged).
    - Using version control ensures that any change to the data lake is scrutinized before it enters production.

2. **Scalability and reproducibility**:
    - Deploying and tearing down a customized, production-grade data lake can be done in minutes and across multiple accounts and environments.
    - This is in comparison to a manual approach which would be tedious, slow, prone to errors and unable to scale.

3. **Best practices**:
    - Best practices acquired through dozens of implementations in production are enforced in the framework.
    - Features such as monitoring (S3 Storage Lens, Cloudtrail), encryption (KMS), alerting (Cloudwatch alarms), data permissions (Lake Formation) and many more are baked in SDLF so you don't have to reinvent the wheel.

## Public References

![SDLF Public References](_static/public-references.png)