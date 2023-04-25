# Datalake Library
The data lake library repository is where a team pushes the transformation code (i.e. business logic) that they wish to apply to their datasets. After each new commit, the repository is automatically packaged into a lambda layer and mounted to the individual Lambda functions of the pipelines belonging to the team. The repository also holds helper functions that automate boiler plate code such as SQS, S3, and DynamoDB operations.

## IMPORTANT
Please ensure that you follow this file structure, with a folder named `python` at the root containing all the Lambda code that should be part of the Layer. The automated build process depends on the file structure being as follows: 
 
    ./
        ├── README.md
        └── python
            └── datalake_library
                ├── configuration
                ├── interfaces
                ├── octagon
                ├── tests                
                └── transforms
                    ├── stage_a_transforms
                    │   ├── light_transform_blueprint.py
                    │   ├── ...
                    ├── stage_b_transforms
                    │   ├── heavy_transform_blueprint.py
                    │   └── ...
                    └── transform_handler.py
 
## Adding Transformations 
When adding custom transformations to the Lambda Layer, simply add your code to this repository (see example of `light_transform_blueprint.py` in file structure above) in the relevant location (e.g. stage_a_transforms for light transformations in StageA). Any changes to this repository should stay in branches while in development, and once tested/stable, these changes can then be merged into the relevant environment branch (`dev, test or master`). The pipeline will trigger upon commits made to this branch, and release these changes automatically.

## Pipeline
The CICD pipeline for this repository is defined in the `sdlf-team` repository for each team (`nested-stacks/template-cicd.yaml`). A CodeBuild job is used to package the code in this repository into a `.zip` file, while leaving out any `__pycache__` files, which is then published as a Lambda Layer. Due to limitations on the size of packages, the code in this repository must not exceed 50MB when zipped, and no more than 250Mb unzipped.

Configuration details, e.g. the name of the Lambda Layer built from this repository, will be defined in the template containing the **sdlf-pipeline** infrastructure. Some of the configuration details available for customization:
1. Through the pipeline:
   1. Main Git branch to use — currently set to `dev`
2. Through the CodeBuild job:
   1. Name of the resulting Layer
   2. Compatible runtimes
   3. SSM parameter used to store the ARN of the latest version