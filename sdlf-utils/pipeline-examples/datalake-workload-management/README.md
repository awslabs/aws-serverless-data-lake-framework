# Tutorial: datalake-workload-management

This readme describes a workload management solution which can be used in data lake pipelines to manage different types of workloads based on source-dataset and priority. It can help to reduce the throttling errors and unnecessary clogging of resource from a dominant source. Since performance and service limits issues are common to most medium to large customers, this solution based on workload management concept can be generalized and reused by other data lake customers as well

## Usecase
In Data Lake projects, there are various different phases ranging from ingestion, foundations and consumption. During the Ingestion phases, a lot of data is ingested to the data lake on s3 from various sources. Each source can have multiple datasets that will be ingested concurrently onto the platform. During one of our usecase implementations, we faced couple of issues with large number of simultaneous step function executions which had multiple steps using glue/lambda resources. 1) The glue job failed with max concurrency which was resolved by adding wait states and increasing the limits 2) Associate KMS key when using KMS key in the glue security configuration where we hit a hard limit on associatekmskey action on CloudWatch log groups. 3) Glue crawler api throttle on start crawler. Furthermore, it become a concern when sources with large number of datasets started taking control of compute resources for a long time and clogging the pipeline. The workload management solution aims to control the flow of step function executions based on priority of source-dataset which will ensure all datasets are processed based on priority.

<<<<<<< HEAD
## Architecture
![Architecture](workload\ management\ artifact.png) 
=======
![Architecture](workload management artifact.png) 
>>>>>>> f33f3eb4c7a2bb840f02ec4c3e9eab8c995d3bca


## Deployment
1. Use the artifacts in the `stageA` directory to create a SDLF pipeline with one stage. The resulting step function is as follows: 
![research_stepfunctions_graph.png](docs/_static/dependency_stepfunction.png)

2. Create the Aggregate Dataset using the template in the `dataset` directory. You can also develop a transform for this dataset that will be executed in the `Execute Transformation` step. Otherwise, use the dummy transformation in the `transforms` directory as a dummy for testing

3. Once the Aggregate Dataset is deployed, update its DynamoDB entry in the `octagon-Dataset-$ENV` table to specify the Atomic Dataset(s) in the dependencies:
```
{
  "dependencies": {
    "dataset1": "engineering-legislators",
    "dataset2": "engineering-politicians",
    ...
  },
  "max_items_process": {
    "stage_b": 100,
    "stage_c": 100
  },
  "min_items_process": {
    "stage_b": 1,
    "stage_c": 1
  },
  "name": "engineering-dependent",
  "pipeline": "aggregate",
  "transforms": {
    "stage_a_transform": "aggregate_dependent_transform",
    "stage_b_transform": "heavy_transform_blueprint"
  },
  "version": 1
}
```
The step function waits for the second stage of all specified Atomic Datasets to finish before executing the submitted transformation. If the conditions are not met, it waits for one hour and retries 2 times by default before abandoning. The retry duration and count can be amended in the stageA and dataset templates, respectively.
