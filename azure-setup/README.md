# Serverless Data Lake Framework (SDLF)

An [AWS Professional Service](https://aws.amazon.com/professional-services/) open source initiative | aws-proserve-opensource@amazon.com

The Serverless Data Lake Framework (SDLF) is a collection of reusable artifacts aimed at accelerating the delivery of enterprise data lakes on AWS, shortening the deployment time to production from several months to a few weeks. It can be used by AWS teams, partners and customers to implement the foundational structure of a data lake following best practices. It is used in production by more than thirty large organizations, including public references such as Embraer, Formula One, Hudl, and David Jones.

## [Read The Docs](https://sdlf.readthedocs.io/en/latest/)

- [**Overview**](https://sdlf.readthedocs.io/en/latest/overview.html)
- [**Constructs**](https://sdlf.readthedocs.io/en/latest/constructs.html)
- [**Architecture**](https://sdlf.readthedocs.io/en/latest/architecture.html)

## Adaptation

By default, the SDLF manages the source code layer in the AWS service CodeCommit which allow to manage the artifacts and the team creations in a very efficient way. Unfortunately, in some cases, enterprise clients that wish to adopt the good practices of the SDLF already use another Source Control Management system. This can become a disadvantage when this company tries to use the SDLF. As [AWS Professional Service](https://aws.amazon.com/professional-services/) our goal is to keep adapting, improving and evolving the best offering for any framework in AWS, this is why we offer this improvement in order to delegate the source code layer and team repositories creation to be handled from a pipeline from Azure DevOps.

![diagram](SDLF_AzureDevOps.jpg "Modification")

NOTE: For convenience, the Azure DevOps words will be replaced by ADO.

1. The foundations stacks are still created from the deploy script
2. In AWS an IAM user is created with its corresponding policy that allows to create the SDLF base repositories. The 
   access key is temporally stored in *service-connection.json* file
3. setup_project: the service connection is created in ADO using the access key and secret created in 2.
4. The base repositories are created in AWS empty.
5. The base repositories are created and populated in ADO. So are the pipelines which in the Mirror stage, will use the service connection created in 3.
6. The team creation is now an ADO pipeline responsability therefore the PAT token is stored as a variable in the sdlf-team pipeline with the porpose to create the team repositories in ADO and AWS 

NOTE: From now on, the script **bootstrap_team.sh** from the **sdlf-team** repository will not create any team repository.

## Technical requirements:

1. [Azure-cli](https://docs.microsoft.com/en-us/cli/azure/install-azure-cli) and an authenticated user with the capability to create repositories, password access tokens and pipelines.
2. [Azure Personal access tokens](https://docs.microsoft.com/en-us/azure/devops/organizations/accounts/use-personal-access-tokens-to-authenticate?view=azure-devops&tabs=preview-page#create-a-pat) 
A PAT is necessary in order to allow the sdlf-team pipeline to create the team repositories in ADO. The [scopes](https://docs.microsoft.com/en-us/azure/devops/integrate/get-started/authentication/oauth?view=azure-devops#scopes) of the token should be:
    - Agent Pools: Read (vso.agentpools)
    - Build: Read & execute (vso.build_execute)
    - Code: Read, write, & manage (vso.code_manage)
    - Project and Team: Read (vso.project)
*NOTE: The expiration time for the PAT should be according to the company policy and it has to be renewed to avoid the pipelines disruption*

3. JQ: If you're using the linux subsystem, you can install it with:
   
    - sudo apt install -y jq
    
    Otherwise, you can install it from the github page: https://stedolan.github.io/jq/download/
4. [AWS-cli](https://aws.amazon.com/cli/)
5. [AWS Toolkit for Azure DevOps](https://aws.amazon.com/vsts/) Used in the service-connection
6. SED: If you're using the linux subsystem, you can install it with:
   
   - sudo apt install -y sed
    
   or if you're using MacOS:    
   
    - brew install gnu-sed

## Setup before deploy

1. Go to the azure-setup directory
2. Modify the file parameters.json according to your Azure DevOps company configuration:
   
   - **organization**: The name of your organization
   - **project**: The name of the project where all the resources will be created
   - **repository-prefix**: The prefix of the repositories for the SDLF project
   - **aws-codecommit-user**: The name of the IAM user that will be created on AWS (for example: sdlf-azure-mirror)
   - **service-connection-name**: The name of the service connection that will use the AWS Toolkit
     to allow the interaction with the CodeCommit repositories. 
   - **sdlf-aztoken**: The PAT string created in the Azure DevOps console (like shown on Technical
     Requirements, bullet number 2)  

    Note: All the parameters are mandatory and can not be empty

3. Execute the *deploy-azure.sh* from the root folder according to the SDLF installation instructions