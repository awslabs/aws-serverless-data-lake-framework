# Tutorial: Manifest Based File Processing

This tutorial shows how a manifest based dataset can be processed using a SDLF pipeline. For us to be able to process a manifest based dataset we will need:-

1. Add a new pipeline to an existing SDLF deployment.
2. Add a new dataset for the above pipeline.

## Pre-requisites

We assume that you have completed the main tutorial deploying the Serverless Data Lake Framework, that is the foundations and at least one team, pipeline and dataset are in place. It also assumes that the engineering team is in place.

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


### Limitations

1. The manifest file name must be unique with every data load and for every dataset.
2. The datafile name must be unique for each manifest file.

**Manifest Pipeline (Stage A State Machine)**

![stage_a_manifest_stepfunction.png](docs/_static/stage_a_manifest_stepfunction.png)

### Overview Stage A

The data for this pipeline is collected from Open Data on AWS and can be found [here](https://registry.opendata.aws/noaa-ghcn/). In this stage both the manifest file and the data file are processed. The contents of the manifest file are a part of the key for the DynamoDB control table. The processing metadata of the data file is stored in the DynamoDB control table against the said keys. The DynamoDB control table is used to control the flow of the processing in both Stage A and Stage B of the pipeline. If the dataset is manifest driven, then only the mainfest file is sent to the next stage.

1. `stage-a-preupdate-metadata` : Pre update the comprehensive catalogue for the incoming file.

2. `stage-a-manifestprocess-check` : Checks whether the dataset being processed is manifest enabled or not. Returns True if the dataset is manifest enabled.

3. `stage-a-manifestfile-check` : Checks whether the current file being processed is the manifest file. Checks against the regex pattern which is set during the dataset registration.

4. `stage-a-process-manifestfile` : If the file being processed is a manifest file then it is read and loaded into the DynamoDB control table. The keys for the control table are :

   - `team-dataset-manifestfilename`
   - `manifestfilename-datafilename`

5. `stage-a-loaddatafile-metadata` : This step first checks whether the manifest file has been loaded or not. If the manifest file has not been loaded, this step sleeps for 5 mins and checks again if the manifest has been loaded or not. This keeps repeating every 5 minutes until the manifest file has been loaded or until the manifest threshold has been breached whichever is earlier. Once the process finds the entry for the manifest file, it updates the metadata for the datafile and marks the Stage A status as STARTED for the the current file.

6. `stage-a-process-object` : In this step the light tranform is executed and the control table is updated with Stage A status as PROCESSING.

7. `stage-a-postupdate-metadata` : In this step the comprehensive catalogue is updated and Stage A status is marked as "COMPLETED" if the light transform was successful else it is marked as "FAILED".

**Manifest Pipeline (Stage B State Machine)**

![stage_b_manifest_stepfunction.png](docs/_static/stage_b_manifest_stepfunction.png)

### Overview Stage B

In this stage the manifest file is processed to identify the datafiles that need to be processed. The datafile names obtained from the manifest filename are queried against the DynamoDB control table and if these files have been processed successfully in Stage A then they are sent to the heavy tranformation to processed further.

1. `stage-b-checkmanifestprocess` : In this step it is checked if the dataset being processed is manifest driven. Returns True if it is manifest enabled.

2. `stage-b-processmanifest` : In this step the manifest file is processed to get the keys for the DynamoDB control table. These keys are used to query the control table to check if the files have been processed in Stage A. If the files have not been processed yet or are being processed then this step waits for 5 minutes and checks again. This step repeats evry 5 minutes until all the files have been loaded or the datafile timeout threshold has been breached, whichever is earlier. If there are failures for any files in Stage A then this steps marks the dataset as "FAILED" for Stage B status and fails the pipeline. If all the files have been processed then this step marks the Stage B status as "STARTED" and moves to the hevy transform.

3. `stage-b-process-data` : This step calls the heavy transform, this case the glue job. This step creates the actual s3 prefixes that needs to be processed by the heavy tranform from the DynamoDB control table. Once the job has been triggered, the Stage B status is set to "PROCESSING".

4. `stage-b-postupdate-metadata` : In this step the Stage B status is marked as "COMPLETED" if the glue job was successful else it is marked as "FAILED". This step also updates the comprehensive catalogue.




### Deployment Steps

All artifacts mentioned in this tutorial are located in this directory:

```bash
# sdlf-utils repository
sdlf-utils/pipeline-examples/manifests/
```

We assume your AWS credentials point to the dev account and region.

1. Copy the following directories with their content to the root location and rename the target folders to reflect the new pipeline (manifest) that we are adding:

   - stageA
   - stageB
   - pipeline
   - dataset

   The name of the directories that need to be created in the step below can begin with the following:-

   > sdlf-team-pipeline-dirname

   In this case we will use "sdlf-engineering-mani"

   The following script is doing just that.

   ```bash
   ### Copy Manifest Folders to root location and rename the target
   cd ./sdlf-utils/pipeline-examples/manifests
   cp -R stageA ../../../sdlf-engineering-mani-stageA/
   cp -R stageB ../../../sdlf-engineering-mani-stageB/
   cp -R dataset ../../../sdlf-engineering-mani-dataset/
   cp -R pipeline ../../../sdlf-engineering-mani-pipeline/
   ```

2. Create codecommit repositories for Stage A , Stage B, Pipeline and Weather Dataset

   ```bash
   ### Create the Stage A Repository
   cd ../../../sdlf-engineering-mani-stageA
   aws codecommit create-repository --repository-name sdlf-engineering-mani-stageA
   git init
   git add .
   git commit -m "Initial Commit"
   git remote add origin codecommit://sdlf-engineering-mani-stageA
   git push --set-upstream origin master
   git checkout -b test
   git push --set-upstream origin test
   git checkout -b dev
   git push --set-upstream origin dev

   ### Create the Stage B Repository
   cd ../sdlf-engineering-mani-stageB
   aws codecommit create-repository --repository-name sdlf-engineering-mani-stageB
   git init
   git add .
   git commit -m "Initial Commit"
   git remote add origin codecommit://sdlf-engineering-mani-stageB
   git push --set-upstream origin master
   git checkout -b test
   git push --set-upstream origin test
   git checkout -b dev
   git push --set-upstream origin dev

   ### Create the Pipeline Repository
   cd ../sdlf-engineering-mani-pipeline
   aws codecommit create-repository --repository-name sdlf-engineering-mani-pipeline
   git init
   git add .
   git commit -m "Initial Commit"
   git remote add origin codecommit://sdlf-engineering-mani-pipeline
   git push --set-upstream origin master
   git checkout -b test
   git push --set-upstream origin test
   git checkout -b dev
   git push --set-upstream origin dev


   ### Create Weather Dataset Repository
   cd ../sdlf-engineering-mani-dataset
   aws codecommit create-repository --repository-name sdlf-engineering-mani-dataset
   git init
   git add .
   git commit -m "Initial Commit"
   git remote add origin codecommit://sdlf-engineering-mani-dataset
   git push --set-upstream origin master
   git checkout -b test
   git push --set-upstream origin test
   git checkout -b dev
   git push --set-upstream origin dev

   ```

3. Copy the light tranform, heavy transform and the dataset mappings to datalakeLibrary repository.

   ```bash

   cd ../sdlf-engineering-datalakeLibrary/python/datalake_library/transforms
   cp ../../../../sdlf-utils/pipeline-examples/manifests/dataset_mappings.json .
   cp ../../../../sdlf-utils/pipeline-examples/manifests/transforms/light_transform_manifest.py ./stage_a_transforms/
   cp ../../../../sdlf-utils/pipeline-examples/manifests/transforms/heavy_transform_manifest.py ./stage_b_transforms/
   ```

   Observe the dataset_mappings.json file

   ```bash
    {
        "name": "legislators",
        "transforms": {
            "stage_a_transform": "light_transform_blueprint",
            "stage_b_transform": "heavy_transform_blueprint"
        }
    },
    {
        "name": "weather",
        "transforms": {
            "stage_a_transform": "light_transform_manifest",
            "stage_b_transform": "heavy_transform_manifest"
        }
    }
   ```

   Assuming the legislators was previously deployed an mapped, we added a new mapping for weather dataset

4. Push the changes in sdlf-engineering-datalakeLibrary so that the transforms can be mapped. By commiting changes in datalakeLibrary we trigger a pipeline that will take care of new mappings and deploy the lambda layer with new transformations.

   ```bash
   cd ../../../
   git add .
   git commit -m "Map light and heavy transforms"
   git push
   ```

5. Deploy the new pipeline (manifest pipeline):

   ```bash

   cd ../sdlf-engineering-mani-pipeline
   ./deploy.sh

   ```

6. Deploy the new dataset (Weather dataset):

   ```bash

   cd ../sdlf-engineering-mani-dataset
   ./deploy.sh

   ```

7. Once the deployment completes, move to sdlf-utils/pipeline-examples/manifests/ folder and deploy the glue job that is called by the heavy transformation in Stage B

   ```bash
   cd ../sdlf-utils/pipeline-examples/manifests/
   ./deploy.sh
   ```

8. Assuming everything went right, copy weather data to S3 raw location. This will trigger the pipeline:

   ```bash
   ./send-data.sh
   ```

   You can watch the execution of step functions now.

   Once both Stage A and Stage statemachines have completed exection, you can check the DynamoDB control table for the files that were processed.

![Manifests_Control_table.png](docs/_static/Manifests_Control_table.png)
