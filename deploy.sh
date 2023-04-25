#!/bin/bash
sflag=false
tflag=false
rflag=false
fflag=false
cflag=false
dflag=false
xflag=false
aflag=false

DIRNAME=$PWD

usage () { echo "
    -h -- Opens up this help message
    -s -- Name of the AWS profile to use for the Shared DevOps Account
    -t -- Name of the AWS profile to use for the Child Account
    -r -- AWS Region to deploy to (e.g. eu-west-1)
    -f -- Deploys SDLF DevOps/CICD/Tooling in the AWS account of the profile provided with -s
    -c -- Deploys Child Account CICD Resources used by SDLF DevOps/CICD/Tooling account
    -d -- Domain accounts list
    -x -- Deploys with an external git SCM. Allowed values: ado -> Azure DevOps, bb -> BitBucket, gitlab -> GitLab
    -a -- Flag to add CodeCommit Pull Request test infrastructure
"; }
options=':s:t:r:d:x:fcha'
while getopts "$options" option
do
    case "$option" in
        s  ) sflag=true; DEVOPS_PROFILE=${OPTARG};;
        t  ) tflag=true; CHILD_PROFILE=${OPTARG};;
        r  ) rflag=true; REGION=${OPTARG};;
        d  ) dflag=true; DOMAIN_ACCOUNTS=${OPTARG};;
        x  ) xflag=true; SCM=${OPTARG};;
        f  ) fflag=true;;
        c  ) cflag=true;;
        a  ) aflag=true;;
        h  ) usage; exit;;
        \? ) echo "Unknown option: -$OPTARG" >&2; exit 1;;
        :  ) echo "Missing option argument for -$OPTARG" >&2; exit 1;;
        *  ) echo "Unimplemented option: -$OPTARG" >&2; exit 1;;
    esac
done

# external SCMs config
if "$xflag"
then
    # declare all the external SCMs supported for example: bitbucket github gitlab
    # each one of these should have its directory, config and custom functions
    declare -a SCMS=(ado bbucket gitlab)
    # shellcheck disable=SC2199,SC2076
    if [[ " ${SCMS[@]} " =~ " ${SCM} " ]]; then
        SCM_DIR=${DIRNAME}/thirdparty-scms/${SCM}
        # shellcheck source=thirdparty-scms/ado/functions.sh
        source "$SCM_DIR"/functions.sh
    else
        echo SCM git value not valid: "$SCM". The allowed values are: "${SCMS[@]}"
        exit 1
    fi
fi

if ! "$sflag"
then
    echo "-s not specified, using default..." >&2
    DEVOPS_PROFILE="default"
fi
if ! "$tflag"
then
    echo "-t not specified, using default..." >&2
    CHILD_PROFILE="default"
fi
if ! "$rflag"
then
    echo "-r not specified, using default region..." >&2
    REGION=$(aws configure get region --profile "$DEVOPS_PROFILE")
fi

DEVOPS_ACCOUNT=$(aws sts get-caller-identity --query 'Account' --output text --profile "$DEVOPS_PROFILE")
CHILD_ACCOUNT=$(aws sts get-caller-identity --query 'Account' --output text --profile "$CHILD_PROFILE")
AWS_PARTITION=$(aws sts get-caller-identity --query 'Arn' --output text --profile "$DEVOPS_PROFILE" | cut -d':' -f2)

function template_protection()
{
    CURRENT_STACK_NAME=$1
    CURRENT_REGION=$2
    CURRENT_PROFILE_NAME=$3

    echo "Updating termination protection for stack $CURRENT_STACK_NAME"
    aws cloudformation update-termination-protection \
        --enable-termination-protection \
        --stack-name "$CURRENT_STACK_NAME" \
        --region "$CURRENT_REGION" \
        --profile "$CURRENT_PROFILE_NAME"
}

if "$fflag"
then
    echo "Deploying SDLF DevOps/Tooling (components repositories, CICD pipelines)" >&2

    if ! "$dflag"
    then
        echo "Domain accounts need specifying" >&2
        exit 1
    fi

    if "$xflag" ; then
        echo "External SCM deployment detected: ${SCM}"
        deploy_sdlf_foundations_scm
    fi

    STACK_NAME=sdlf-cicd-prerequisites
    aws cloudformation deploy \
        --stack-name "$STACK_NAME" \
        --template-file "$DIRNAME"/sdlf-cicd/template-cicd-prerequisites.yaml \
        --parameter-overrides \
            pDomainAccounts="$DOMAIN_ACCOUNTS" \
        --tags Framework=sdlf \
        --capabilities "CAPABILITY_NAMED_IAM" "CAPABILITY_AUTO_EXPAND" \
        --region "$REGION" \
        --profile "$DEVOPS_PROFILE"
    template_protection "$STACK_NAME" "$REGION" "$DEVOPS_PROFILE"

    ARTIFACTS_BUCKET=$(aws ssm get-parameter --name /SDLF/S3/DevOpsArtifactsBucket --query "Parameter.Value" --output text --region "$REGION" --profile "$DEVOPS_PROFILE")
    mkdir "$DIRNAME"/output
    aws cloudformation package --template-file "$DIRNAME"/sdlf-cicd/template-cicd-sdlf-repositories.yaml --s3-bucket "$ARTIFACTS_BUCKET" --s3-prefix template-cicd-sdlf-repositories --output-template-file "$DIRNAME"/output/packaged-template.yaml --region "$REGION" --profile "$DEVOPS_PROFILE"
    STACK_NAME=sdlf-cicd-sdlf-repositories
    aws cloudformation deploy \
        --s3-bucket "$ARTIFACTS_BUCKET" --s3-prefix sdlf-cicd-sdlf-repositories \
        --stack-name "$STACK_NAME" \
        --template-file "$DIRNAME"/output/packaged-template.yaml \
        --parameter-overrides \
            pArtifactsBucket=/SDLF/S3/DevOpsArtifactsBucket \
            pKMSKey=/SDLF/KMS/CICDKeyId \
        --tags Framework=sdlf \
        --capabilities "CAPABILITY_NAMED_IAM" "CAPABILITY_AUTO_EXPAND" \
        --region "$REGION" \
        --profile "$DEVOPS_PROFILE"
    template_protection "$STACK_NAME" "$REGION" "$DEVOPS_PROFILE"

    declare -a REPOSITORIES=("sdlf-cicd" "sdlf-foundations" "sdlf-team" "sdlf-pipeline" "sdlf-dataset" "sdlf-datalakeLibrary" "sdlf-pipLibrary" "sdlf-stageA" "sdlf-stageB")
    for REPOSITORY in "${REPOSITORIES[@]}"
    do
        latest_commit=$(aws codecommit get-branch --repository-name "$REPOSITORY" --branch-name master --query 'branch.commitId' --output text --region "$REGION" --profile "$DEVOPS_PROFILE")
        aws codecommit create-branch --repository-name "$REPOSITORY" --branch-name dev --commit-id "$latest_commit" --region "$REGION" --profile "$DEVOPS_PROFILE"
        aws codecommit create-branch --repository-name "$REPOSITORY" --branch-name test --commit-id "$latest_commit" --region "$REGION" --profile "$DEVOPS_PROFILE"
    done

    aws s3api put-object --bucket "$ARTIFACTS_BUCKET" --key sam-translate.py --body "$DIRNAME"/sdlf-cicd/sam-translate.py --profile "$DEVOPS_PROFILE"
fi

if "$cflag"
then
    echo "Deploying SDLF DevOps/Tooling roles in child accounts" >&2
    # Increase SSM Parameter Store throughput to 1,000 requests/second TODO
    aws ssm update-service-setting --setting-id arn:"$AWS_PARTITION":ssm:"$REGION:$CHILD_ACCOUNT":servicesetting/ssm/parameter-store/high-throughput-enabled --setting-value true --region "$REGION" --profile "$CHILD_PROFILE"
    DEVOPS_ARTIFACTS_BUCKET=$(aws --region "$REGION" --profile "$DEVOPS_PROFILE" ssm get-parameter --name /SDLF/S3/DevOpsArtifactsBucket --query "Parameter.Value" --output text)
    DEVOPS_KMS_KEY=$(aws --region "$REGION" --profile "$DEVOPS_PROFILE" ssm get-parameter --name /SDLF/KMS/CICDKeyId --query "Parameter.Value" --output text)
    DEVOPS_BUILDCLOUDFORMATIONMODULESTAGE=$(aws --region "$REGION" --profile "$DEVOPS_PROFILE" ssm get-parameter --name /SDLF/CodeBuild/BuildCloudformationModuleStage --query "Parameter.Value" --output text)
    DEVOPS_BUILDDEPLOYDATALAKELIBRARYLAYER=$(aws --region "$REGION" --profile "$DEVOPS_PROFILE" ssm get-parameter --name /SDLF/CodeBuild/BuildDeployDatalakeLibraryLayer --query "Parameter.Value" --output text)
    DEVOPS_BUILDDEPLOYREQUIREMENTSLAYER=$(aws --region "$REGION" --profile "$DEVOPS_PROFILE" ssm get-parameter --name /SDLF/CodeBuild/BuildDeployRequirementsLayer --query "Parameter.Value" --output text)
    STACK_NAME=sdlf-cicd-domain-roles
    aws cloudformation deploy \
        --stack-name "$STACK_NAME" \
        --template-file "$DIRNAME"/sdlf-cicd/template-cicd-domain-roles.yaml \
        --parameter-overrides \
            pDevOpsAccountId="$DEVOPS_ACCOUNT" \
            pDevOpsArtifactsBucket="$DEVOPS_ARTIFACTS_BUCKET" \
            pDevOpsKMSKey="$DEVOPS_KMS_KEY" \
            pBuildCloudformationModuleStage="$DEVOPS_BUILDCLOUDFORMATIONMODULESTAGE" \
            pBuildDeployDatalakeLibraryLayer="$DEVOPS_BUILDDEPLOYDATALAKELIBRARYLAYER" \
            pBuildDeployRequirementsLayer="$DEVOPS_BUILDDEPLOYREQUIREMENTSLAYER" \
        --tags Framework=sdlf \
        --capabilities "CAPABILITY_NAMED_IAM" "CAPABILITY_AUTO_EXPAND" \
        --region "$REGION" \
        --profile "$CHILD_PROFILE"

    template_protection "$STACK_NAME" "$REGION" "$CHILD_PROFILE"
fi
