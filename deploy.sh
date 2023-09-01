#!/bin/bash

DIRNAME=$PWD

bold=$(tput bold)
underline=$(tput smul)
notunderline=$(tput rmul)
notbold=$(tput sgr0)

version () { echo "awssdlf/2.0.0"; }

usage () { echo "
    --version -- Prints the SDLF version
    -h -- Opens up this help message
    -r -- AWS Region to deploy to (e.g. eu-west-1)

    crossaccount-cicd-roles -d -p -- Deploys crossaccount IAM roles necessary for DevOps CICD pipelines
        -d -- AWS account id of the Shared DevOps account
        -p -- Name of the AWS profile to use where a SDLF data domain will reside
    devops-account -d -p -- Deploys SDLF DevOps/CICD/Tooling resources
        -d -- Comma-delimited list of AWS account ids where SDLF data domains are deployed
        -p -- Name of the AWS profile to use where SDLF DevOps/CICD/Tooling will reside

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
    options=':p:r:d:'
    while getopts "$options" option
    do
        case "$option" in
            p  ) pflag=true; DOMAIN_AWS_PROFILE=${OPTARG};;
            r  ) rflag=true; REGION=${OPTARG};;
            d  ) dflag=true; DEVOPS_ACCOUNT=${OPTARG};;
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

    echo "Deploying SDLF DevOps/Tooling roles in data domain accounts" >&2

    # Increase SSM Parameter Store throughput to 1,000 requests/second TODO
    DOMAIN_ACCOUNT_ID=$(aws --profile "$DOMAIN_AWS_PROFILE" sts get-caller-identity --query 'Account' --output text)
    AWS_PARTITION=$(aws --profile "$DOMAIN_AWS_PROFILE" sts get-caller-identity --query 'Arn' --output text | cut -d':' -f2)
    aws --region "$REGION" --profile "$DOMAIN_AWS_PROFILE" ssm update-service-setting --setting-id arn:"$AWS_PARTITION":ssm:"$REGION:$DOMAIN_ACCOUNT_ID":servicesetting/ssm/parameter-store/high-throughput-enabled --setting-value true
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
    options=':p:r:d:'
    while getopts "$options" option
    do
        case "$option" in
            p  ) pflag=true; DEVOPS_AWS_PROFILE=${OPTARG};;
            r  ) rflag=true; REGION=${OPTARG};;
            d  ) dflag=true; DOMAIN_ACCOUNTS=${OPTARG};;
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

    echo "Deploying SDLF DevOps/Tooling (components repositories, CICD pipelines)" >&2

    STACK_NAME=sdlf-cicd-prerequisites
    aws cloudformation deploy \
        --stack-name "$STACK_NAME" \
        --template-file "$DIRNAME"/sdlf-cicd/template-cicd-prerequisites.yaml \
        --parameter-overrides \
            pDomainAccounts="$DOMAIN_ACCOUNTS" \
        --tags Framework=sdlf \
        --capabilities "CAPABILITY_NAMED_IAM" "CAPABILITY_AUTO_EXPAND" \
        --region "$REGION" \
        --profile "$DEVOPS_AWS_PROFILE"
    template_protection "$STACK_NAME" "$REGION" "$DEVOPS_AWS_PROFILE"

    ARTIFACTS_BUCKET=$(aws --region "$REGION" --profile "$DEVOPS_AWS_PROFILE" ssm get-parameter --name /SDLF/S3/DevOpsArtifactsBucket --query "Parameter.Value" --output text)
    mkdir "$DIRNAME"/output
    aws cloudformation package \
        --s3-bucket "$ARTIFACTS_BUCKET" --s3-prefix template-cicd-sdlf-repositories \
        --template-file "$DIRNAME"/sdlf-cicd/template-cicd-sdlf-repositories.yaml \
        --output-template-file "$DIRNAME"/output/packaged-template.yaml \
        --region "$REGION" \
        --profile "$DEVOPS_AWS_PROFILE"
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
        --profile "$DEVOPS_AWS_PROFILE"
    template_protection "$STACK_NAME" "$REGION" "$DEVOPS_AWS_PROFILE"

    declare -a REPOSITORIES=("sdlf-cicd" "sdlf-foundations" "sdlf-team" "sdlf-pipeline" "sdlf-dataset" "sdlf-datalakeLibrary" "sdlf-stageA" "sdlf-stageB")
    for REPOSITORY in "${REPOSITORIES[@]}"
    do
        latest_commit=$(aws --region "$REGION" --profile "$DEVOPS_AWS_PROFILE" codecommit get-branch --repository-name "$REPOSITORY" --branch-name master --query 'branch.commitId' --output text)
        aws --region "$REGION" --profile "$DEVOPS_AWS_PROFILE" codecommit create-branch --repository-name "$REPOSITORY" --branch-name dev --commit-id "$latest_commit"
        aws --region "$REGION" --profile "$DEVOPS_AWS_PROFILE" codecommit create-branch --repository-name "$REPOSITORY" --branch-name test --commit-id "$latest_commit"
    done

    aws --region "$REGION" --profile "$DEVOPS_AWS_PROFILE" s3api put-object --bucket "$ARTIFACTS_BUCKET" --key sam-translate.py --body "$DIRNAME"/sdlf-cicd/sam-translate.py
    curl -L -O --output-dir "$DIRNAME"/sdlf-cicd/ https://github.com/aws/aws-sam-cli/releases/latest/download/aws-sam-cli-linux-x86_64.zip
    aws --region "$REGION" --profile "$DEVOPS_AWS_PROFILE" s3api put-object --bucket "$ARTIFACTS_BUCKET" --key aws-sam-cli-linux-x86_64.zip --body "$DIRNAME"/sdlf-cicd/aws-sam-cli-linux-x86_64.zip
    rm "$DIRNAME"/sdlf-cicd/aws-sam-cli-linux-x86_64.zip

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

case "$subcommand" in
    crossaccount-cicd-roles) crossaccount_cicd_roles "$@"; exit;;
    devops-account) devops_account "$@"; exit;;
    *) echo "Unimplemented command: $subcommand" >&2; exit 1;;
esac
