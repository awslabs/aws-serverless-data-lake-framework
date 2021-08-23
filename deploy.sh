#!/bin/bash
sflag=false
tflag=false
rflag=false
eflag=false
dflag=false
fflag=false
oflag=false
cflag=false
xflag=false
aflag=false

DIRNAME=$(pwd)
declare -a REPOSITORIES=("sdlf-foundations" "sdlf-team" "sdlf-pipeline" "sdlf-dataset" "sdlf-datalakeLibrary" "sdlf-pipLibrary" "sdlf-stageA" "sdlf-stageB" "sdlf-utils")

usage () { echo "
    -h -- Opens up this help message
    -s -- Name of the AWS profile to use for the Shared DevOps Account
    -t -- Name of the AWS profile to use for the Child Account
    -r -- AWS Region to deploy to (e.g. eu-west-1)
    -e -- Environment to deploy to (dev, test or prod)
    -d -- Demo mode
    -f -- Deploys SDLF Foundations
    -o -- Deploys Shared DevOps Account CICD Resources
    -c -- Deploys Child Account CICD Resources
    -x -- Deploys with an external git SCM. Allowed values: ado -> Azure DevOps, bb -> BitBucket
    -a -- Flag to add CodeCommit Pull Request test infrastructure
"; }
options=':s:t:r:x:e:dfocha'
while getopts $options option
do
    case "$option" in
        s  ) sflag=true; DEVOPS_PROFILE=${OPTARG};;
        t  ) tflag=true; CHILD_PROFILE=${OPTARG};;
        r  ) rflag=true; REGION=${OPTARG};;
        e  ) eflag=true; ENV=${OPTARG};;
        x  ) xflag=true; SCM=${OPTARG};;
        d  ) dflag=true;;
        f  ) fflag=true;;
        o  ) oflag=true;;
        c  ) cflag=true;;
        a  ) aflag=true;;
        h  ) usage; exit;;
        \? ) echo "Unknown option: -$OPTARG" >&2; exit 1;;
        :  ) echo "Missing option argument for -$OPTARG" >&2; exit 1;;
        *  ) echo "Unimplemented option: -$OPTARG" >&2; exit 1;;
    esac
done

# external SCMs config
if $xflag
then
    if $dflag; then echo "Demo mode not compatible with -x option"; exit 1; fi #validate no demo
    # declare all the external SCMs supported for example: bitbucket github gitlab
    # each one of these should have its directory, config and custom functions
    declare -a SCMS=(ado bbucket)
    if [[ " ${SCMS[@]} " =~ " ${SCM} " ]]; then
        SCM_DIR=${DIRNAME}/thirdparty-scms/${SCM}
        source ${SCM_DIR}/functions.sh
    else
        echo SCM git value not valid: ${SCM}. The allowed values are: ${SCMS[@]}
        exit 1
    fi
fi

if ! $sflag
then
    echo "-s not specified, using default..." >&2
    DEVOPS_PROFILE="default"
fi
if ! $tflag
then
    echo "-t not specified, using default..." >&2
    CHILD_PROFILE="default"
fi
if ! $rflag
then
    echo "-r not specified, using default region..." >&2
    REGION=$(aws configure get region --profile ${DEVOPS_PROFILE})
fi
if ! $eflag
then
    echo "-e not specified, using dev environment..." >&2
    ENV=dev
fi
if ! $dflag
then
    echo "-d not specified, demo mode off..." >&2
    DEMO=false
else
    echo "-d specified, demo mode on..." >&2
    DEMO=true
    fflag=true
    oflag=true
    cflag=true
    git config --global user.email "robot@example.com"
    git config --global user.name "robot"
    echo y | sudo yum install jq
fi


DEVOPS_ACCOUNT=$(aws sts get-caller-identity --query 'Account' --output text --profile ${DEVOPS_PROFILE})
CHILD_ACCOUNT=$(aws sts get-caller-identity --query 'Account' --output text --profile ${CHILD_PROFILE})

function bootstrap_repository()
{
    REPOSITORY=${1}
    echo "Creating and Loading ${REPOSITORY} Repository"
    aws codecommit create-repository --region ${REGION} --profile ${DEVOPS_PROFILE} --repository-name ${REPOSITORY}
    cd ${DIRNAME}/${REPOSITORY}/
    git init
    git add .
    git commit -m "Initial Commit"
    git remote add origin https://git-codecommit.${REGION}.amazonaws.com/v1/repos/${REPOSITORY}
    git push --set-upstream origin master
    git checkout -b test
    git push --set-upstream origin test
    git checkout -b dev
    git push --set-upstream origin dev
}

function deploy_sdlf_foundations()
{
    git config --global credential.helper '!aws --profile '${DEVOPS_PROFILE}' codecommit credential-helper $@'
    git config --global credential.UseHttpPath true
    for REPOSITORY in "${REPOSITORIES[@]}"
    do
        bootstrap_repository ${REPOSITORY}
    done
    cd ${DIRNAME}
}

function template_protection()
{
    CURRENT_ENV=$1
    CURRENT_STACK_NAME=$2
    CURRENT_REGION=$3
    CURRENT_PROFILE_NAME=$4

    if [ $CURRENT_ENV != "dev" ]
    then
        echo "Updating termination protection for stack $CURRENT_STACK_NAME"
        aws cloudformation update-termination-protection \
            --enable-termination-protection \
            --stack-name $CURRENT_STACK_NAME \
            --region $CURRENT_REGION \
            --profile $CURRENT_PROFILE_NAME
    else
        echo "Target is the dev account. Not applying template protection"
    fi
}

if $fflag
then
    echo "Deploying SDLF foundational repositories..." >&2

    if $xflag ; then
        echo "External SCM deployment detected: ${SCM}"
        deploy_sdlf_foundations_scm
    else
        deploy_sdlf_foundations
    fi
    STACK_NAME=sdlf-cicd-team-repos
    aws cloudformation create-stack \
        --stack-name ${STACK_NAME} \
        --template-body file://${DIRNAME}/sdlf-cicd/template-cicd-team-repos.yaml \
        --tags Key=Framework,Value=sdlf \
        --capabilities "CAPABILITY_NAMED_IAM" "CAPABILITY_AUTO_EXPAND" \
        --region ${REGION} \
        --profile ${DEVOPS_PROFILE}
    echo "Waiting for stack to be created ..."
    aws cloudformation wait stack-create-complete --profile ${DEVOPS_PROFILE} --region ${REGION} --stack-name ${STACK_NAME}

    template_protection ${ENV} ${STACK_NAME} ${REGION} ${DEVOPS_PROFILE}
fi

if $oflag
then
    STACK_NAME=sdlf-cicd-shared-foundations-${ENV}
    aws cloudformation deploy \
        --stack-name ${STACK_NAME} \
        --template-file ${DIRNAME}/sdlf-cicd/template-cicd-shared-foundations.yaml \
        --parameter-overrides \
            pEnvironment="${ENV}" \
            pChildAccountId="${CHILD_ACCOUNT}" \
        --tags Framework=sdlf \
        --capabilities "CAPABILITY_NAMED_IAM" "CAPABILITY_AUTO_EXPAND" \
        --region ${REGION} \
        --profile ${DEVOPS_PROFILE}
    echo "Waiting for stack to be created ..."
    aws cloudformation wait stack-create-complete --profile ${DEVOPS_PROFILE} --region ${REGION} --stack-name ${STACK_NAME}

    template_protection ${ENV} ${STACK_NAME} ${REGION} ${DEVOPS_PROFILE}
    # Adding in CodeCommit Pull Request tests. Pass / Fail comments are injected into the 'Activity' tab of CodeCommit
    if [ "$xflag" == "false" ] && [ "$aflag" == "true" ]
    then
        DEVOPS_ACCOUNT_KMS=$(aws ssm get-parameter --name /SDLF/KMS/${ENV}/CICDKeyId --region ${REGION} --profile ${DEVOPS_PROFILE} --query "Parameter.Value" --output text)
        for REPOSITORY in "${REPOSITORIES[@]}"
        do
            # Currently the tests focus on cfn-lint and cfn_nag scans. Ignoring repositories
            # that do not have these templates.

            if [ "$REPOSITORY" != "sdlf-datalakeLibrary" ] && [ "$REPOSITORY" != "sdlf-pipLibrary" ]
            then
                # NOTE: The default is that only cfn-lint and cfn_nag tests are executed.
                #       If wishing to execute different tests beyond cfn-lint / cfn_nag for any one of the repositories,
                #       override the default values below by adding if conditions. An example is below:
                #
                #       pInstallationCommands="gem install cfn-nag && pip3 install cfn-lint"
                #       pTestCommands="cfn-lint **/*.yaml && cfn_nag_scan --input-path ./ --template-pattern '..*\.yaml|..*\.yml' -s"
                #       if [ "$REPOSITORY" == "sdlf-team" ]
                #       then
                #           pInstallationCommands="$pInstallationCommands && pip3 install -r policy_creation/requirements.txt"
                #           pTestCommands="$pTestCommands && pytest --cov=bucket_policies -v"
                #       fi
                pInstallationCommands="gem install cfn-nag && pip3 install cfn-lint"
                pTestCommands="cfn-lint **/*.yaml && cfn_nag_scan --input-path ./ --template-pattern '..*\.yaml|..*\.yml' -s"

                STACK_NAME="$REPOSITORY-pr-check-stack"
                aws cloudformation deploy \
                    --stack-name "${STACK_NAME}" \
                    --template-file ${DIRNAME}/sdlf-cicd/template-codecommit-pr-check.yaml \
                    --parameter-overrides \
                        pTargetRepositoryName="${REPOSITORY}" \
                        pKMSKeyArn="${DEVOPS_ACCOUNT_KMS}" \
                        pInstallationCommands="${pInstallationCommands}" \
                        pTestCommands="${pTestCommands}" \
                    --tags Framework=sdlf \
                    --capabilities "CAPABILITY_IAM" \
                    --region ${REGION} \
                    --profile ${DEVOPS_PROFILE} \
                    --no-fail-on-empty-changeset

                template_protection ${ENV} ${STACK_NAME} ${REGION} ${CHILD_PROFILE}
            fi
        done
    fi
fi

if $cflag
then
    # Increase SSM Parameter Store throughput to 1,000 requests/second
    aws ssm update-service-setting --setting-id arn:aws:ssm:${REGION}:${CHILD_ACCOUNT}:servicesetting/ssm/parameter-store/high-throughput-enabled --setting-value true --region ${REGION} --profile ${CHILD_PROFILE}
    DEVOPS_ACCOUNT_KMS=$(aws ssm get-parameter --name /SDLF/KMS/${ENV}/CICDKeyId --region ${REGION} --profile ${DEVOPS_PROFILE} --query "Parameter.Value" --output text)
    STACK_NAME=sdlf-cicd-child-foundations
    aws cloudformation deploy \
        --stack-name ${STACK_NAME} \
        --template-file ${DIRNAME}/sdlf-cicd/template-cicd-child-foundations.yaml \
        --parameter-overrides \
            pDemo="${DEMO}" \
            pEnvironment="${ENV}" \
            pSharedDevOpsAccountId="${DEVOPS_ACCOUNT}" \
            pSharedDevOpsAccountKmsKeyArn="${DEVOPS_ACCOUNT_KMS}" \
        --tags Framework=sdlf \
        --capabilities "CAPABILITY_NAMED_IAM" "CAPABILITY_AUTO_EXPAND" \
        --region ${REGION} \
        --profile ${CHILD_PROFILE}

    template_protection ${ENV} ${STACK_NAME} ${REGION} ${CHILD_PROFILE}
fi