# Serverless Data Lake Framework (SDLF)

## BitBucket

![diagram](SDLF_AzureDevOps.jpg "Modification")


https://support.atlassian.com/bitbucket-cloud/docs/app-passwords/

3. app password with the permissions:
- Repositories: Read, Write, Admin
- Pipelines: Read, Write, Edit variables

Params:
- IAM user 
Pipeline:
- assume role
- export AWS_*
- git helper


## Prerequisites:

1. https://support.atlassian.com/bitbucket-cloud/docs/app-passwords/

2. JQ: If you're using the linux subsystem, you can install it with:
   
    - sudo apt install -y jq
    
    Otherwise, you can install it from the github page: https://stedolan.github.io/jq/download/
3. [AWS-cli](https://aws.amazon.com/cli/)
4. SED: If you're using the linux subsystem, you can install it with:
   
   - sudo apt install -y sed
    
   or if you're using MacOS:    
   
    - brew install gnu-sed

project private, repos privates

## Setup before deploy

1. Go to the thirdparty-scms/ado directory
2. Modify the file parameters.json according to your Azure DevOps company configuration:
   
   - **workspace**: The name of your organization
   - **bitbucketuser**: The name of the project where all the resources will be created
   - **app-password**: App passwords are substitute passwords for a user account which you can use for scripts and integrating tools to avoid putting your real password into configuration files. (more)[https://support.atlassian.com/bitbucket-cloud/docs/app-passwords/]
   - **repository-prefix**: The prefix of the repositories for the SDLF project
   - **aws-access-key-id**: The AWS access key ID for signing programmatic requests. Example: AKIAIOSFODNN7EXAMPLE. 
   - **aws-secret-access-key**: The AWS secret access key for signing programmatic requests. Example: wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY
   - **session-token**: (Optional) The AWS session token for signing programmatic requests. Note: Only use this if you have an external rotation mechanism)
   - **role-to-assume**: (Optional) The Amazon Resource Name (ARN) of the role to assume. If a role ARN is specified the access and secret keys configured in the endpoint will be used to generate temporary session credentials, scoped to the specified role, and used be used by the pipeline. 

