#!/bin/bash

DIRNAME=$PWD

bold=$(tput bold)
underline=$(tput smul)
notunderline=$(tput rmul)
notbold=$(tput sgr0)

version () { echo "awssdlf/2.7.0-alpha.0"; }

usage () { echo "
    --version -- Prints the SDLF version
    -h -- Opens up this help message
    -r -- AWS Region to deploy to (e.g. eu-west-1)

    crossaccount-cicd-roles -d -p -- Deploys crossaccount IAM roles necessary for DevOps CICD pipelines
        -d -- AWS account id of the Shared DevOps account
        -p -- Name of the AWS profile to use where a SDLF data domain will reside
        -f -- Enable optional features: monitoring, vpc. Multiple -f options can be given.
    devops-account -d -p -- Deploys SDLF DevOps/CICD/Tooling resources
        -d -- Comma-delimited list of AWS account ids where SDLF data domains are deployed
        -p -- Name of the AWS profile to use where SDLF DevOps/CICD/Tooling will reside
        -f -- Enable optional features: gluejobdeployer, lambdalayerbuilder, monitoring, vpc. Multiple -f options can be given.

    Examples

    ${bold}./deploy.sh${notbold} ${underline}crossaccount-cicd-roles${notunderline} ${bold}-d${notbold} ${underline}devops_aws_account_id${notunderline} ${bold}-p${notbold} ${underline}aws_account_profile${notunderline}
    deploys IAM roles in the AWS account ${underline}aws_account_profile${notunderline} belongs to.
    These roles are necessary for the DevOps account CICD pipelines to work.
    They should be deployed first.

    ${bold}./deploy.sh${notbold} ${underline}devops-account${notunderline} ${bold}-d${notbold} ${underline}domain_aws_account_id1,domain_aws_account_id2,...${notunderline} ${bold}-p${notbold} ${underline}devops_aws_account_profile${notunderline}
    deploys SDLF DevOps/CICD/Tooling resources in the AWS account ${underline}devops_aws_account_profile${notunderline} belongs to.
    These resources are used to deploy new data domains, teams, pipelines and datasets in the provided comma-delimited list of accounts.
    This should be used after creating the crossaccount CICD roles with ${bold}./deploy.sh crossaccount-cicd-roles${notbold} for each of the AWS accounts listed.
"; }

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

crossaccount_cicd_roles () { 
    pflag=false
    rflag=false
    dflag=false
    fflag=false
    options=':p:r:d:f:'
    while getopts "$options" option
    do
        case "$option" in
            p  ) pflag=true; DOMAIN_AWS_PROFILE=${OPTARG};;
            r  ) rflag=true; REGION=${OPTARG};;
            d  ) dflag=true; DEVOPS_ACCOUNT=${OPTARG};;
            f  ) fflag=true; FEATURES+=("${OPTARG}");;
            \? ) echo "Unknown option: -$OPTARG" >&2; exit 1;;
            :  ) echo "Missing option argument for -$OPTARG" >&2; exit 1;;
            *  ) echo "Unimplemented option: -$OPTARG" >&2; exit 1;;
        esac
    done

    if ! "$pflag"
    then
        echo "-p not specified, using default..." >&2
        DOMAIN_AWS_PROFILE="default"
    fi
    if ! "$rflag"
    then
        echo "-r not specified, using default region..." >&2
        REGION=$(aws configure get region --profile "$DOMAIN_AWS_PROFILE")
    fi
    if ! "$dflag"
    then
        echo "-d must be specified when using the crossaccount-cicd-roles command" >&2
        exit 1
    fi
    if "$fflag"
    then
        MONITORING=false
        VPC=false
        if printf "%s\0" "${FEATURES[@]}" | grep -Fxqz -- "monitoring"
        then
            MONITORING=true
            echo "Optional feature: sdlf-monitoring module"
        fi
        if printf "%s\0" "${FEATURES[@]}" | grep -Fxqz -- "vpc"
        then
            VPC=true
            echo "Optional feature: VPC support"
        fi
    else
        echo "-f not specified, set all features to false by default" >&2
        MONITORING=false
        VPC=false
    fi

    echo "Deploying SDLF DevOps/Tooling roles in data domain accounts" >&2

    # Increase SSM Parameter Store throughput to 1,000 requests/second
    DOMAIN_ACCOUNT_ID=$(aws --profile "$DOMAIN_AWS_PROFILE" sts get-caller-identity --query 'Account' --output text)
    AWS_PARTITION=$(aws --profile "$DOMAIN_AWS_PROFILE" sts get-caller-identity --query 'Arn' --output text | cut -d':' -f2)
    aws --region "$REGION" --profile "$DOMAIN_AWS_PROFILE" ssm update-service-setting --setting-id "arn:$AWS_PARTITION:ssm:$REGION:$DOMAIN_ACCOUNT_ID:servicesetting/ssm/parameter-store/high-throughput-enabled" --setting-value true
    DEVOPS_ARTIFACTS_BUCKET="sdlf-$REGION-$DEVOPS_ACCOUNT-cicd-cfn-artifacts"
    DEVOPS_KMS_KEY_ALIAS="alias/sdlf-cicd-kms-key"
    STACK_NAME=sdlf-cicd-domain-roles
    aws cloudformation deploy \
        --stack-name "$STACK_NAME" \
        --template-file "$DIRNAME"/sdlf-cicd/template-cicd-domain-roles.yaml \
        --parameter-overrides \
            pDevOpsAccountId="$DEVOPS_ACCOUNT" \
            pDevOpsArtifactsBucket="$DEVOPS_ARTIFACTS_BUCKET" \
            pDevOpsKMSKey="$DEVOPS_KMS_KEY_ALIAS" \
            pEnableMonitoring="$MONITORING" \
            pEnableVpc="$VPC" \
        --tags Framework=sdlf \
        --capabilities "CAPABILITY_NAMED_IAM" "CAPABILITY_AUTO_EXPAND" \
        --region "$REGION" \
        --profile "$DOMAIN_AWS_PROFILE"

    template_protection "$STACK_NAME" "$REGION" "$DOMAIN_AWS_PROFILE"

    exit
}

devops_account () { 
    pflag=false
    rflag=false
    dflag=false
    fflag=false
    options=':p:r:d:f:'
    while getopts "$options" option
    do
        case "$option" in
            p  ) pflag=true; DEVOPS_AWS_PROFILE=${OPTARG};;
            r  ) rflag=true; REGION=${OPTARG};;
            d  ) dflag=true; DOMAIN_ACCOUNTS=${OPTARG};;
            f  ) fflag=true; FEATURES+=("${OPTARG}");;
            \? ) echo "Unknown option: -$OPTARG" >&2; exit 1;;
            :  ) echo "Missing option argument for -$OPTARG" >&2; exit 1;;
            *  ) echo "Unimplemented option: -$OPTARG" >&2; exit 1;;
        esac
    done

    if ! "$pflag"
    then
        echo "-p not specified, using default..." >&2
        DEVOPS_AWS_PROFILE="default"
    fi
    if ! "$rflag"
    then
        echo "-r not specified, using default region..." >&2
        REGION=$(aws configure get region --profile "$DEVOPS_AWS_PROFILE")
    fi
    if ! "$dflag"
    then
        echo "-d must be specified when using the devops-account command" >&2
        exit 1
    fi
    if "$fflag"
    then
        GIT_PLATFORM=CodeCommit
        GITLAB=false
        GITHUB=false
        GLUE_JOB_DEPLOYER=false
        LAMBDA_LAYER_BUILDER=false
        MONITORING=false
        VPC=false
        if printf "%s\0" "${FEATURES[@]}" | grep -Fxqz -- "gitlab"
        then
            GIT_PLATFORM=GitLab
            GITLAB=true
            echo "Optional feature: GitLab"
        fi
        if printf "%s\0" "${FEATURES[@]}" | grep -Fxqz -- "github"
        then
            GIT_PLATFORM=GitHub
            GITHUB=true
            echo "Optional feature: GitHub"
        fi
        if printf "%s\0" "${FEATURES[@]}" | grep -Fxqz -- "gluejobdeployer"
        then
            GLUE_JOB_DEPLOYER=true
            echo "Optional feature: Glue Job Deployer"
        fi
        if printf "%s\0" "${FEATURES[@]}" | grep -Fxqz -- "lambdalayerbuilder"
        then
            LAMBDA_LAYER_BUILDER=true
            echo "Optional feature: Lambda Layer Builder"
        fi
        if printf "%s\0" "${FEATURES[@]}" | grep -Fxqz -- "monitoring"
        then
            MONITORING=true
            echo "Optional feature: sdlf-monitoring module"
        fi
        if printf "%s\0" "${FEATURES[@]}" | grep -Fxqz -- "vpc"
        then
            VPC=true
            echo "Optional feature: VPC support"
        fi
    else
        echo "-f not specified, set all features to false by default" >&2
        GIT_PLATFORM=CodeCommit
        GITLAB=false
        GITHUB=false
        GLUE_JOB_DEPLOYER=false
        LAMBDA_LAYER_BUILDER=false
        MONITORING=false
        VPC=false
    fi
    echo "Deploying SDLF DevOps/Tooling (components repositories, CICD pipelines)" >&2

    # Increase SSM Parameter Store throughput to 1,000 requests/second
    DEVOPS_ACCOUNT_ID=$(aws --profile "$DEVOPS_AWS_PROFILE" sts get-caller-identity --query 'Account' --output text)
    AWS_PARTITION=$(aws --profile "$DEVOPS_AWS_PROFILE" sts get-caller-identity --query 'Arn' --output text | cut -d':' -f2)
    aws --region "$REGION" --profile "$DEVOPS_AWS_PROFILE" ssm update-service-setting --setting-id "arn:$AWS_PARTITION:ssm:$REGION:$DEVOPS_ACCOUNT_ID:servicesetting/ssm/parameter-store/high-throughput-enabled" --setting-value true

    STACK_NAME=sdlf-cicd-prerequisites
    aws cloudformation deploy \
        --stack-name "$STACK_NAME" \
        --template-file "$DIRNAME"/sdlf-cicd/template-cicd-prerequisites.yaml \
        --parameter-overrides \
            pDomainAccounts="$DOMAIN_ACCOUNTS" \
            pGitPlatform="$GIT_PLATFORM" \
            pEnableGlueJobDeployer="$GLUE_JOB_DEPLOYER" \
            pEnableLambdaLayerBuilder="$LAMBDA_LAYER_BUILDER" \
            pEnableMonitoring="$MONITORING" \
            pEnableVpc="$VPC" \
        --tags Framework=sdlf \
        --capabilities "CAPABILITY_NAMED_IAM" "CAPABILITY_AUTO_EXPAND" \
        --region "$REGION" \
        --profile "$DEVOPS_AWS_PROFILE" || exit 1
    template_protection "$STACK_NAME" "$REGION" "$DEVOPS_AWS_PROFILE"

    ARTIFACTS_BUCKET=$(aws --region "$REGION" --profile "$DEVOPS_AWS_PROFILE" ssm get-parameter --name /SDLF/S3/DevOpsArtifactsBucket --query "Parameter.Value" --output text)
    REPOSITORIES_TEMPLATE_FILE="$DIRNAME/sdlf-cicd/template-cicd-sdlf-repositories.$(tr "[:upper:]" "[:lower:]" <<< "$GIT_PLATFORM").yaml"
    mkdir "$DIRNAME"/output
    aws cloudformation package \
        --s3-bucket "$ARTIFACTS_BUCKET" --s3-prefix template-cicd-sdlf-repositories \
        --template-file "$REPOSITORIES_TEMPLATE_FILE" \
        --output-template-file "$DIRNAME"/output/packaged-template-cicd-sdlf-repositories.yaml \
        --region "$REGION" \
        --profile "$DEVOPS_AWS_PROFILE"
    STACK_NAME=sdlf-cicd-sdlf-repositories
    aws cloudformation deploy \
        --s3-bucket "$ARTIFACTS_BUCKET" --s3-prefix sdlf-cicd-sdlf-repositories \
        --stack-name "$STACK_NAME" \
        --template-file "$DIRNAME"/output/packaged-template-cicd-sdlf-repositories.yaml \
        --parameter-overrides \
            pKMSKey=/SDLF/KMS/CICDKeyId \
        --tags Framework=sdlf \
        --capabilities "CAPABILITY_NAMED_IAM" "CAPABILITY_AUTO_EXPAND" \
        --region "$REGION" \
        --profile "$DEVOPS_AWS_PROFILE" || exit 1
    template_protection "$STACK_NAME" "$REGION" "$DEVOPS_AWS_PROFILE"
    rm -Rf "$DIRNAME"/output

    declare -a REPOSITORIES=("sdlf-cicd" "sdlf-foundations" "sdlf-team" "sdlf-pipeline" "sdlf-dataset" "sdlf-datalakeLibrary" "sdlf-stageA" "sdlf-stageB" "sdlf-stage-lambda" "sdlf-stage-glue" "sdlf-main")
    if "$MONITORING"
    then
        REPOSITORIES+=("sdlf-monitoring")
    fi
    for REPOSITORY in "${REPOSITORIES[@]}"
    do
        if "$GITLAB"
        then
            GITLAB_URL=$(aws --region "$REGION" --profile "$DEVOPS_AWS_PROFILE" ssm get-parameter --with-decryption --name /SDLF/GitLab/Url --query "Parameter.Value" --output text)
            GITLAB_ACCESSTOKEN=$(aws --region "$REGION" --profile "$DEVOPS_AWS_PROFILE" ssm get-parameter --with-decryption --name /SDLF/GitLab/AccessToken --query "Parameter.Value" --output text)
            GITLAB_REPOSITORY_URL="https://aws:$GITLAB_ACCESSTOKEN@${GITLAB_URL#https://}sdlf/$REPOSITORY.git"

            if [ "$REPOSITORY" = "sdlf-main" ]
            then
                mkdir sdlf-main
                cp sdlf-cicd/README.md sdlf-main/
            fi
            pushd "$REPOSITORY" || exit
            if [ ! -d .git ] # if .git exists, deploy.sh has likely been run before - do not try to push the base repositories
            then
                git init
                git remote add origin "$GITLAB_REPOSITORY_URL" || exit 1
                git add .
                git commit -m "initial commit"
                git push origin main || exit 1
                git push origin main:dev
                git push origin main:test
            fi
            popd || exit
        elif "$GITHUB"
        then
            #GITHUB_ACCESSTOKEN=$(aws --region "$REGION" --profile "$DEVOPS_AWS_PROFILE" ssm get-parameter --with-decryption --name /SDLF/GitHub/AccessToken --query "Parameter.Value" --output text)
            GITHUB_REPOSITORY_URL="https://github.com/$REPOSITORY.git"

            if [ "$REPOSITORY" = "sdlf-main" ]
            then
                mkdir sdlf-main
                cp sdlf-cicd/README.md sdlf-main/
            fi
            pushd "$REPOSITORY" || exit
            if [ ! -d .git ] # if .git exists, deploy.sh has likely been run before - do not try to push the base repositories
            then
                git init
                git remote add origin "$GITHUB_REPOSITORY_URL" || exit 1
                git add .
                git commit -m "initial commit"
                git push origin main || exit 1
                git push origin main:dev
                git push origin main:test
            fi
            popd || exit
        else
            latest_commit=$(aws --region "$REGION" --profile "$DEVOPS_AWS_PROFILE" codecommit get-branch --repository-name "$REPOSITORY" --branch-name main --query "branch.commitId" --output text)
            aws --region "$REGION" --profile "$DEVOPS_AWS_PROFILE" codecommit create-branch --repository-name "$REPOSITORY" --branch-name dev --commit-id "$latest_commit"
            aws --region "$REGION" --profile "$DEVOPS_AWS_PROFILE" codecommit create-branch --repository-name "$REPOSITORY" --branch-name test --commit-id "$latest_commit"
        fi
    done

    aws --region "$REGION" --profile "$DEVOPS_AWS_PROFILE" s3api put-object --bucket "$ARTIFACTS_BUCKET" --key sam-translate.py --body "$DIRNAME"/sdlf-cicd/sam-translate.py
    curl -L -O --output-dir "$DIRNAME"/sdlf-cicd/ https://github.com/aws/aws-sam-cli/releases/latest/download/aws-sam-cli-linux-x86_64.zip
    aws --region "$REGION" --profile "$DEVOPS_AWS_PROFILE" s3api put-object --bucket "$ARTIFACTS_BUCKET" --key aws-sam-cli-linux-x86_64.zip --body "$DIRNAME"/sdlf-cicd/aws-sam-cli-linux-x86_64.zip
    rm "$DIRNAME"/sdlf-cicd/aws-sam-cli-linux-x86_64.zip

    mkdir "$DIRNAME"/output
    aws cloudformation package \
        --s3-bucket "$ARTIFACTS_BUCKET" --s3-prefix template-cicd-sdlf-pipelines \
        --template-file "$DIRNAME"/sdlf-cicd/template-cicd-sdlf-pipelines.yaml \
        --output-template-file "$DIRNAME"/output/packaged-template-cicd-sdlf-pipelines.yaml \
        --region "$REGION" \
        --profile "$DEVOPS_AWS_PROFILE"
    STACK_NAME=sdlf-cicd-sdlf-pipelines
    aws cloudformation deploy \
        --s3-bucket "$ARTIFACTS_BUCKET" --s3-prefix sdlf-cicd-sdlf-pipelines \
        --stack-name "$STACK_NAME" \
        --template-file "$DIRNAME"/output/packaged-template-cicd-sdlf-pipelines.yaml \
        --parameter-overrides \
            pArtifactsBucket=/SDLF/S3/DevOpsArtifactsBucket \
            pKMSKey=/SDLF/KMS/CICDKeyId \
            pCicdRepository="/SDLF/$GIT_PLATFORM/Cicd$GIT_PLATFORM" \
            pMainRepository="/SDLF/$GIT_PLATFORM/Main$GIT_PLATFORM" \
        --tags Framework=sdlf \
        --capabilities "CAPABILITY_NAMED_IAM" "CAPABILITY_AUTO_EXPAND" \
        --region "$REGION" \
        --profile "$DEVOPS_AWS_PROFILE" || exit 1
    template_protection "$STACK_NAME" "$REGION" "$DEVOPS_AWS_PROFILE"
    rm -Rf "$DIRNAME"/output

    exit
}

options='ha-:'
while getopts "$options" option
do
    case "$option" in
        -  )
            case "${OPTARG}" in
                version)
                    version; exit;;
            esac;;
        h  ) usage; exit;;
        \? ) echo "Unknown option: -$OPTARG" >&2; exit 1;;
        *  ) echo "Unimplemented option: -$OPTARG" >&2; exit 1;;
    esac
done

# crossaccount-cicd-roles, devops-account
# check aws-cli version is recent enough
if (echo aws-cli/2.13.0; aws --version | cut -d' ' -f1) | sort -V | tail -1 | grep -Fv "aws-cli/2.13.0"
then
  echo "aws-cli >= 2.13.0, deployment can start"
else
  echo "SDLF requires aws-cli >= 2.13.0"
  echo "https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html"
  exit 1
fi

if [ "${1#-}" = "$1" ]
then
    subcommand=$1
    shift
    unset OPTIND
fi

# shellcheck disable=SC2317
case "$subcommand" in
    crossaccount-cicd-roles) crossaccount_cicd_roles "$@"; exit;;
    devops-account) devops_account "$@"; exit;;
    *) echo "Unimplemented command: $subcommand" >&2; exit 1;;
esac
