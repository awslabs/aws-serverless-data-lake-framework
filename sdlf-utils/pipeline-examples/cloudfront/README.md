# Tutorial: Building a new pipeline with EMR and Deequ steps into SDLF

The aim of this tutorial is two-fold:

1. Demonstrate how to add a pipeline and a dataset to an existing SDLF deployment
2. Showcase a pipeline example involving multiple EMR steps, including a data quality step using Deequ

The final output is similar to the step function defined in this [AWS blog](https://aws.amazon.com/blogs/aws/new-using-step-functions-to-orchestrate-amazon-emr-workloads/):

![EMR_StepFunctions](docs/_static/emr_stepfunction.png)

## Pre-requisites

We assume that you have completed the main tutorial deploying the Serverless Data Lake Framework, that is the foundations and at least one team, pipeline and dataset are in place.

- You must run in a linux like environment, with **python 3.9+** on it
- **AWS CLI 2** installed
- **AWS SAM** installed
- **jq** linux utility installed, and
- **git-remote-codecommit** python library installed.

Verify like this:

```bash
aws --version
sam --version
python --version
jq --version

pip list| grep git-remote-codecommit

```

## Deployment

We aim to ingest and transform a new dataset named `clf` referring to [CloudFront logs](https://github.com/aws-samples/amazon-cloudfront-log-analysis/tree/master/lab1-serveless-cloudfront-log-analysis). The heavy transformation will involve running multiple EMR steps from within the step function.

0.  All artifacts mentioned in this tutorial are located in this directory:

    ```bash
    # sdlf-utils repository
    sdlf-utils/pipeline-examples/cloudfront/

    ```

    This example is using `engineering` team to deploy a new pipeline that will process cloudfron logs.

1.  First, we create a new stage definition for a pipeline. In this case, we would like the pipeline to keep the same definition for `stageA` but to modify `stageB` so that the Glue job is replaced with multiple EMR steps.
    Duplicate `sdlf-engineering-stageB` repository and and name the duplicated repo `sdlf-engineering-emr-stageB`. Add it to CodeCommit and create dev, test and prod branches.

    ```bash
    # assuming you are initially in aws-serverless-data-lake-framework-sdlf, root of the framework
    cp -R ./sdlf-engineering-stageB ./sdlf-engineering-emr-stageB/
    cd ./sdlf-engineering-emr-stageB
    rm -rf .git
    aws codecommit create-repository --repository-name sdlf-engineering-emr-stageB
    git init
    git add .
    git commit -m "Initial Commit"
    git remote add origin codecommit://sdlf-engineering-emr-stageB
    git push --set-upstream origin master
    git checkout -b test
    git push --set-upstream origin test
    git checkout -b dev
    git push --set-upstream origin dev

    # go back to root
    cd ../

    ```

    Then replace the CloudFormation `template.yaml` and `./state-machine/stage-b.asl.json` files in the `sdlf-engineering-emr-stageB` repository with the ones located in `./sdlf-utils/pipeline-examples/cloudfront`. This new CloudFormation template and State Machine structure define a step function which includes multiple EMR steps. You can run a `git diff` to see these changes.

    Push these new changes to `dev` branch in CodeCommit.

2.  Now that the `stageB` structure has been defined, we can deploy the new pipeline.

    Duplicate `sdlf-engineering-pipeline` and rename the duplicated folder to `sdlf-engineering-emr-pipeline`. Remove existing git association, and add
    `sdlf-engineering-emr-pipeline` to codecommit as a new repository. Create dev, test and prod branches.

    This script will help with creating the repo and dev, test, prod branches:

    ```bash
    # assuming you are initially in aws-serverless-data-lake-framework-sdlf, root of the framework
    cp -R ./sdlf-engineering-pipeline ./sdlf-engineering-emr-pipeline/
    cd ./sdlf-engineering-emr-pipeline
    rm -rf .git
    aws codecommit create-repository --repository-name sdlf-engineering-emr-pipeline
    git init
    git add .
    git commit -m "Initial Commit"
    git remote add origin codecommit://sdlf-engineering-emr-pipeline
    git push --set-upstream origin master
    git checkout -b test
    git push --set-upstream origin test
    git checkout -b dev
    git push --set-upstream origin dev


    ```

    While you are in `sdlf-engineering-emr-pipeline`, modify the value of `pPipelineName` to `emr` and the value of `pStageBStateMachineRepository` to `sdlf-engineering-emr-stageB` in all `parameters-$ENV.json` files. Then, push changes to CodeCommit and deploy the pipeline by executing `deploy.sh` locally.

    ```bash
    # Run in sdlf-engineering-emr-pipeline repository
    ./deploy.sh
    ```

    A new CloudFormation stack will create the necessary infrastructure for this pipeline. Once it reaches the `CREATE_COMPLETE` state, you can check in the Step Functions console that a new pipeline is in place with the same StageA definition but with different StageB steps

3.  We now turn our attention to creating a new dataset.

    Duplicate `sdlf-engineering-dataset` folder and rename duplicated folder to `sdlf-engineering-emr-dataset`. Remove existing git association, and add
    `sdlf-engineering-emr-dataset` to codecommit as a new repository. Create dev, test and prod branches.

    ```bash
    cd ./qaz5-engineering-emr-dataset
    rm -rf .git
    aws codecommit create-repository --repository-name qaz5-engineering-emr-dataset
    git init
    git add .
    git commit -m "Initial Commit"
    git remote add origin codecommit://qaz5-engineering-emr-dataset
    git push --set-upstream origin master
    git checkout -b test
    git push --set-upstream origin test
    git checkout -b dev
    git push --set-upstream origin dev

    ```

    Change the `pPipelineName` value to `emr` and the `pDatasetName` value to `clf` in all `parameters-$ENV.json` files before saving it. Once the parameters are configured run the below command locally:

    ```bash
    # Run in sdlf-engineering-emr-dataset repository
    ./deploy.sh
    ```

    A CloudFormation stack for the `clf` dataset will be created

4.  We must now reference the custom transformations that this new pipeline will apply on the data. Observe both the `light_transform_clf.py` and `heavy_transform_clf.py` files in the `sdlf-utils` directory. The light transformation adds a column to incoming CloudFront logs while the heavy transform calls three EMR steps including a Deequ data quality check. Now copy `light_transform_clf.py` into `sdlf-engineering-datalakeLibrary/python/datalake_library/transforms/stage_a_transforms` and
    `heavy_transform_clf.py` into `sdlf-engineering-datalakeLibrary/python/datalake_library/transforms/stage_b_transforms`.

    We then modify the `dataset_mappings.json` file to specify the `dataset` to `transforms` mapping that we wish to apply:

    ```bash
    [
        {
            "name": "legislators",
            "transforms": {
                "stage_a_transform": "light_transform_blueprint",
                "stage_b_transform": "heavy_transform_blueprint"
            }
        },
        ...
        {
            "name": "clf",
            "transforms": {
                "stage_a_transform": "light_transform_clf",
                "stage_b_transform": "heavy_transform_clf"
            }
        }
    ]
    ```

        At last we push these changes:

    ```bash
    # Run in sdlf-engineering-datalakeLibrary repository
    git add .
    git commit -m "Created CloudFront logs transforms"
    git push
    ```

    A CodePipeline will update the relevant Lambdas in the `emr` pipeline with this code

5.  Back in the local directory (`sdlf-utils/pipeline-examples/cloudfront/`), run:

    ```bash
    ./deploy.sh
    ```

    The script will create EMR default roles if they don't already exist in the account, load the EMR and Deequ scripts in the artifacts bucket. For other pipelines, we would deploy the glue job for the heavy transformation here, but in our case this is taken care by EMR handled through stageB worflow.

6.  Assumming everything went right, submit the sample data file to the target raw location that will trigger the pipeline.

    ```bash
    ./send-data.sh
    ```

    CloudFront logs will first be processed through the Pre-Stage (i.e. StageA) step function where a column representing the HTTP status outcome is added to each file. Then in the Post-Stage (i.e. StageB) step function, an EMR cluster is created and processes a batch of files through three EMR steps. The first runs a Deequ quality check and outputs results to `s3://<artifacts-bucket>/engineering/clf/elasticmapreduce/deequ-metrics/metrics-repository/`. The second step is ran in parallel and cancelled after 10 seconds. A last step waits for the previous two to succeed before running a Hive query on the logs to calculate the total number of requests per operating system over a specified time frame. Results are visible in Athena once the Glue crawler step completes.

    Note that you can provide an existing EMR cluster Id to the step function instead of creating one. Likewise, you can decide whether to delete the cluster or keep it alive at the end.
