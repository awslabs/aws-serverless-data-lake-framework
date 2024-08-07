# sdlf-dataset

!!! note
    `sdlf-dataset` is defined in the [sdlf-dataset](https://github.com/awslabs/aws-serverless-data-lake-framework/tree/main/sdlf-dataset) folder of the [SDLF repository](https://github.com/awslabs/aws-serverless-data-lake-framework).

## Infrastructure

![SDLF Dataset](../_static/sdlf-dataset.png)

A SDLF dataset is a logical construct referring to a grouping of data. It can be anything from a single table to an entire database with multiple tables for example. However, an overall good practice is to limit the infrastructure deployed to the minimum to avoid unnecessary overhead and cost. It means that in general, the more data is grouped together the better. Abstraction at the transformation code level can then help make distinctions within a given dataset.

Examples of datasets are:

- A relational database with multiple tables (e.g. Sales DB with orders and customers tables)
- A group of files from a data source (e.g. XML files from a Telemetry system)
- A streaming data source (e.g. Kinesis data stream batching files and dumping them into S3)

`sdlf-dataset` creates a Glue database, as well as a Glue crawler.

SSM parameters holding names or ARNs are created for all resources that may be used by other modules.

## Usage

### CloudFormation with [sdlf-cicd](cicd.md)

Read the official [SDLF workshop](https://sdlf.workshop.aws/) for an end-to-end deployment example.

```
rExample:
    Type: awslabs::sdlf::dataset::MODULE
    Properties:
        pPipelineReference: !Ref pPipelineReference
        pTeamName: iot
        pDatasetName: legislators
```

## Interface

Interfacing with other modules is done through [SSM Parameters](https://docs.aws.amazon.com/systems-manager/latest/userguide/systems-manager-parameter-store.html). `sdlf-dataset` publishes the following parameters:

| SSM Parameter                             | Description                                  | Comment                                      |
| ----------------------------------------- | -------------------------------------------- | -------------------------------------------- |
| `/SDLF/Datasets/{team}/{dataset}`         | Dataset-specific metadata for data pipelines |                                              |
| `/SDLF/Glue/{team}/{dataset}/GlueCrawler` | Team dataset Glue crawler                    |                                              |
| `/SDLF/Glue/{team}/{dataset}/DataCatalog` | Team dataset metadata catalog"               |                                              |
