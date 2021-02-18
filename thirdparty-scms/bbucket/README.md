# Serverless Data Lake Framework (SDLF)

## BitBucket

![diagram](SDLF+BitBucket.jpg "Modification")

1. The foundations stacks are still created from the deploy script
2. The git mirroring, and the team repositories creation is delegated to BitBucket using the next features:
    1. An user and an [app-password](https://support.atlassian.com/bitbucket-cloud/docs/app-passwords/): This allows to use a dedicated access from the pipelines to allow the team and pipelines repositories creation and execution.
    2. An AWS credentials access key and secret key (with the option to assume a specific role). This allows to create the repositories and commit by demand.
  These feature are triggered from the file bitbucket-pipelines.yml
3. The **app_password** and **bitbucketuser** parameters are stored as pipeline variables for the  prefix-sdlf-team repository.
4. The **sdlf_\*** parameters are stored in the Workspace Variables ([source](https://support.atlassian.com/bitbucket-cloud/docs/variables-and-secrets/) section *Workspace Variables*) from Bitbucket, in order to be avalaible for the pipelines in a secured way.

## Prerequisites:

1. An [app-password](https://support.atlassian.com/bitbucket-cloud/docs/app-passwords/) with the next permissions:
    - Repositories: Read, Write, Admin
    - Pipelines: Read, Write, Edit variables
2. The pipelines feature should be [enabled](https://support.atlassian.com/bitbucket-cloud/docs/get-started-with-bitbucket-pipelines/) in Bitbucket
3. An IAM user (or role) with the next policy attached:
```
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
              "codecommit:*"
            ],
            "Resource": "arn:aws:codecommit:*:*:sdlf-*"
        }
    ]
}
```
4. JQ: If you're using the linux subsystem, you can install it with:
   
    - sudo apt install -y jq
    
    Otherwise, you can install it from the github page: https://stedolan.github.io/jq/download/
5. [AWS-cli](https://aws.amazon.com/cli/)
6. SED: If you're using the linux subsystem, you can install it with:
   
   - sudo apt install -y sed
    
   or if you're using MacOS:    
   
    - brew install gnu-sed

project private, repos privates

## Setup before deploy

1. Go to the thirdparty-scms/bbucket directory
2. Modify the file parameters.json according to your Bitbucket company policies and configuration:
   
   - **workspace**: The name of your organization
   - **bitbucketprojectkey**: The key string that is generated once a (project is created](https://confluence.atlassian.com/bitbucketserver/creating-projects-776639848.html)
   - **bitbucketuser**: The name of the user which will held the app-password
   - **app_password**: App passwords are substitute passwords for a user account which you can use for scripts and integrating tools to avoid putting your real password into configuration files. (more)[https://support.atlassian.com/bitbucket-cloud/docs/app-passwords/]
   - **repository_prefix**: The prefix of the repositories for the SDLF project
   - **sldf_aws_access_key_id**: The AWS access key ID for signing programmatic requests. Example: AKIAIOSFODNN7EXAMPLE. 
   - **sdlf_aws_secret_access_key**: The AWS secret access key for signing programmatic requests. Example: wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY
   - **sdlf_session_token**: (Optional) The AWS session token for signing programmatic requests. Note: Only use this if you have an external rotation mechanism)
   - **sdlf_role_to_assume**: (Optional) The Amazon Resource Name (ARN) of the role to assume. If a role ARN is specified the access and secret keys configured in the endpoint will be used to generate temporary session credentials, scoped to the specified role, and used be used by the pipeline.

3. Execute the foundations *deploy.sh* script with the option extra option **-x bbucket** from the root folder according to the SDLF installation instructions
