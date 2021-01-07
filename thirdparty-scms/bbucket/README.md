# Serverless Data Lake Framework (SDLF)

## BitBucket

![diagram](SDLF_AzureDevOps.jpg "Modification")


https://support.atlassian.com/bitbucket-cloud/docs/app-passwords/

3. ssd

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

## Setup before deploy

1. Go to the thirdparty-scms/ado directory
2. Modify the file parameters.json according to your Azure DevOps company configuration:
   
   - **organization**: The name of your organization
   - **project**: The name of the project where all the resources will be created
   - **repository-prefix**: The prefix of the repositories for the SDLF project
   - **service-connection-name**: The name of the service connection that will use the AWS Toolkit
     to allow the interaction with the CodeCommit repositories. 
   - **sdlf-aztoken**: The PAT string created in the Azure DevOps console (like shown on TPrerequisites, bullet number 2)  

