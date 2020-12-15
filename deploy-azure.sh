#!/usr/local/bin/bash
sflag=false
tflag=false
rflag=false
eflag=false
dflag=false
fflag=false
oflag=false
cflag=false

DIRNAME=$(pwd)

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
"; }
options=':s:t:r:e:dfoch'
while getopts $options option
do
    case "$option" in
        s  ) sflag=true; DEVOPS_PROFILE=${OPTARG};;
        t  ) tflag=true; CHILD_PROFILE=${OPTARG};;
        r  ) rflag=true; REGION=${OPTARG};;
        e  ) eflag=true; ENV=${OPTARG};;
        d  ) dflag=true;;
        f  ) fflag=true;;
        o  ) oflag=true;;
        c  ) cflag=true;;
        h  ) usage; exit;;
        \? ) echo "Unknown option: -$OPTARG" >&2; exit 1;;
        :  ) echo "Missing option argument for -$OPTARG" >&2; exit 1;;
        *  ) echo "Unimplemented option: -$OPTARG" >&2; exit 1;;
    esac
done

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

if [[ "$OSTYPE" == "darwin"* ]];
then
    SED=$(which gsed)
else
    SED=$(which sed)
fi

DEVOPS_ACCOUNT=$(aws sts get-caller-identity --query 'Account' --output text --profile ${DEVOPS_PROFILE})
CHILD_ACCOUNT=$(aws sts get-caller-identity --query 'Account' --output text --profile ${CHILD_PROFILE})

function bootstrap_repository()
{
    REPOSITORY=$1
    echo "Creating repository ${REPOSITORY} on AWS" && set +e
    OUTPUT=$(aws codecommit create-repository --region ${REGION} --profile ${DEVOPS_PROFILE} --repository-name ${REPOSITORY} 2>&1)
    STATUS=$? && set -e
    if [ ${STATUS} -ne 0 ] ; then
      if [[ ${OUTPUT} == *"RepositoryNameExistsException"* ]] ; then
        echo -e "\nRepository named ${TEAM_REPOSITORY} already exists in AWS";
      else
        echo "Error: ${OUTPUT}" && exit ${STATUS}
      fi
    fi
    # copy azure pipeline
    cd "${DIRNAME}"
    if [[ "${REPOSITORY}" == *"team"* ]]; then
      cp -f "$AZDIR"/azure-pipelines-team-template.yml "$AZDIR"/azure-pipelines.yml
    else
      cp -f "$AZDIR"/azure-pipelines-template.yml "$AZDIR"/azure-pipelines.yml
    fi
    $SED -i "s/<REPOSITORY>/${REPOSITORY}/g" "$AZDIR"/azure-pipelines.yml
    $SED -i "s/REGION/${REGION}/g" "$AZDIR"/azure-pipelines.yml
    $SED -i "s/SERVICE_CONNECTION/${SERVICE_CONNECTION}/g" "$AZDIR"/azure-pipelines.yml
    
    cp -f "$AZDIR"/azure-pipelines.yml ./${REPOSITORY}/azure-pipelines.yml
    cd ${REPOSITORY}/
    /bin/test -d .git && rm -rf .git
    git init
    if [[ "${REPOSITORY}" == "sdlf-team" ]]; then #remove sdlf-team repositories creation
      $SED -i 's/bootstrap_team_repository ${TEAM_NAME} ${REPOSITORY}/echo "Creation delegated to external SCM"/g' scripts/bootstrap_team.sh
    fi
    git add . 
    git commit -m "Initial Commit" > /dev/null
    # Azure mods
    echo "Creating repository ${PREFIX}-${REPOSITORY} on Azure"
    set +e
    OUTPUT=$(az repos create --name ${PREFIX}-${REPOSITORY} 2>&1)
    STATUS=$? && set -e
    if [ ${STATUS} -ne 0 ] ; then
      if [[ ${OUTPUT} == "TF400948: A Git repository"* && ${OUTPUT} == *"already exists"* ]] ; then
        echo -e "\nRepository named ${PREFIX}-${REPOSITORY} already exists in Azure";
      else
        echo "Error. Verify the Azure configuration OUTPUT: ${OUTPUT}" && exit ${STATUS}
      fi
    else
      TOKEN64=$(printf ":${TOKEN}" | base64)
      git remote add origin "https://dev.azure.com/${ORG}/${PROJECT}/_git/${PREFIX}-${REPOSITORY}"
      git -c http.extraHeader="Authorization: Basic ${TOKEN64}" push --set-upstream origin master
      git checkout -b test
      git -c http.extraHeader="Authorization: Basic ${TOKEN64}" push --set-upstream origin test
      git checkout -b dev
      git -c http.extraHeader="Authorization: Basic ${TOKEN64}" push --set-upstream origin dev
    fi
}

function setup_azure_pipelines() {
    REPOSITORY=$1
    echo "Creating pipeline ${PREFIX}-${REPOSITORY}"
    az pipelines create --name ${PREFIX}-${REPOSITORY} \
    --branch master --description "Pipeline SDLF for ${PREFIX}-${REPOSITORY}" \
    --folder-path "sdlf" --yml-path azure-pipelines.yml \
    --repository "${PREFIX}-${REPOSITORY}" --repository-type tfsgit --skip-first-run true > /dev/null

    if [[ "${REPOSITORY}" == "sdlf-team" ]]; then
      echo "Creating pipeline variables for team repository"
      az pipelines variable create --pipeline-name ${PREFIX}-${REPOSITORY} \
          --name sdlf-aztoken --value ${TOKEN} --secret true > /dev/null
      az pipelines variable create --pipeline-name ${PREFIX}-${REPOSITORY} \
          --name sdlf-team-firstTime --value "1" > /dev/null
      az pipelines variable create --pipeline-name ${PREFIX}-${REPOSITORY} \
          --name sdlf-azure-prefix --value ${PREFIX} > /dev/null
    fi
    echo "Running pipelines"
    for BRANCH in master dev test; do
      PIPELINE_ID=`az pipelines run --name ${PREFIX}-${REPOSITORY} --branch ${BRANCH} --folder-path "sdlf" | jq -r .id`
      if [[ "${REPOSITORY}" == "sdlf-team" ||  "${REPOSITORY}" == "sdlf-foundations" ]]; then # these repositories must be populated synchronously
        STATUS=`az pipelines runs show --id ${PIPELINE_ID} | jq -r .status`
        while [ "$STATUS" != "completed" ]; do
          echo "Waiting for the pipeline ${PREFIX}-${REPOSITORY} on branch ${BRANCH} to finish" && sleep 7
          STATUS=`az pipelines runs show --id ${PIPELINE_ID} | jq -r .status`
        done
      fi
    done
    if [[ "${REPOSITORY}" == "sdlf-team" ]]; then #disable the firstTime flag to enable teams creation
      az pipelines variable update --pipeline-name ${PREFIX}-${REPOSITORY} \
          --name sdlf-team-firstTime --value "0" > /dev/null
    fi
} 

function setup_azure_config() {
    echo "Setting up Azure config and service-connection request"
    cp -f "$AZDIR"/service-connection-template.json "$AZDIR"/service-connection.json
    $SED -i "s|PROJECT|${PROJECT}|g" "$AZDIR"/service-connection.json
    $SED -i "s|AWS_ACCESS_KEY|${AWS_ACCESS_KEY}|g" "$AZDIR"/service-connection.json
    $SED -i "s|AWS_SECRET_KEY|${AWS_SECRET_KEY}|g" "$AZDIR"/service-connection.json
    $SED -i "s|SERVICE_CONNECTION|${SERVICE_CONNECTION}|g" "$AZDIR"/service-connection.json

    az devops configure --defaults organization="https://dev.azure.com/$ORG" project="$PROJECT"
    echo "Creating service-connection \"${SERVICE_CONNECTION}\" on the project: \"${PROJECT}\""
    SC_ID=`az devops service-endpoint create --service-endpoint-configuration \
      "$AZDIR"/service-connection.json | jq -r .id`
    az devops service-endpoint update --id ${SC_ID} --enable-for-all > /dev/null
}

function deploy_sdlf_foundations() {
    cd "${DIRNAME}"
    AZDIR="$DIRNAME"/azure-setup
    declare -a REPOSITORIES=("sdlf-team" "sdlf-foundations" "sdlf-pipeline" "sdlf-dataset" "sdlf-datalakeLibrary" "sdlf-pipLibrary" "sdlf-stageA" "sdlf-stageB")
    echo "Getting configuration parameters"
    ORG=`jq -r '.[] | select(.ParameterKey=="organization") | .ParameterValue' "$AZDIR"/parameters.json`
    PROJECT=`jq -r '.[] | select(.ParameterKey=="project") | .ParameterValue' "$AZDIR"/parameters.json`
    PREFIX=`jq -r '.[] | select(.ParameterKey=="repository-prefix") | .ParameterValue' "$AZDIR"/parameters.json`
    AWS_CC_USER=`jq -r '.[] | select(.ParameterKey=="aws-codecommit-user") | .ParameterValue' "$AZDIR"/parameters.json`
    IAM_USER=`aws iam list-users --profile ${DEVOPS_PROFILE} | jq -r --arg USER "${AWS_CC_USER}" '.Users[] |select(.UserName==$USER) | .UserName'`
    SERVICE_CONNECTION=`jq -r '.[] | select(.ParameterKey=="service-connection-name") | .ParameterValue' "$AZDIR"/parameters.json`
    TOKEN=`jq -r '.[] | select(.ParameterKey=="sdlf-aztoken") | .ParameterValue' "$AZDIR"/parameters.json`

    if [[ "${IAM_USER}" == "" ]]; then
      echo "Creating CodeCommit User on AWS";
      aws iam create-user --user-name ${AWS_CC_USER} --profile ${DEVOPS_PROFILE} > /dev/null
      cp -f "$AZDIR"/aws-codecommit-policy-template.json "$AZDIR"/aws-codecommit-policy.json
      $SED -i "s/REGION/${REGION}/g" "$AZDIR"/aws-codecommit-policy.json
      $SED -i "s/ACCOUNT_ID/${DEVOPS_ACCOUNT}/g" "$AZDIR"/aws-codecommit-policy.json
      POLICY_ARN=`aws iam create-policy --policy-name ${AWS_CC_USER}-policy --policy-document \
        --profile ${DEVOPS_PROFILE} file://"$AZDIR"/aws-codecommit-policy.json |jq -r '.Policy.Arn'`
      aws iam attach-user-policy --policy-arn ${POLICY_ARN} --user-name ${AWS_CC_USER} --profile ${DEVOPS_PROFILE}
      echo "Creating access_key on AWS";
      JSONRESPONSE=$(aws iam create-access-key --user-name ${AWS_CC_USER} --profile ${DEVOPS_PROFILE})
      AWS_ACCESS_KEY=$(echo ${JSONRESPONSE} |jq -r '.AccessKey.AccessKeyId')
      AWS_SECRET_KEY=$(echo ${JSONRESPONSE} |jq -r '.AccessKey.SecretAccessKey')
    else
      echo "The user \"$AWS_CC_USER\" already exists. Aborting!!!" && exit 1
    fi

    setup_azure_config
    for REPOSITORY in "${REPOSITORIES[@]}"
    do
      echo "bootstrap_repository ${REPOSITORY}..."
      bootstrap_repository $REPOSITORY
      echo "setup_azure_pipelines ${REPOSITORY}"
      setup_azure_pipelines $REPOSITORY
      echo waiting key
      read -n 1
    done
    cd "${DIRNAME}"
}

if $fflag
then
    echo "Verifying if az cli is authenticated Azure"
    output=$(az account list 2>&1)
    if [[ "$output" == *"Please run"* ]]; then
        echo "You have to be authenticated to deploy from Azure DevOps" && exit 1
    fi
    echo "Deploying SDLF foundational repositories..."
    deploy_sdlf_foundations
    STACK_NAME=sdlf-cicd-team-repos
    aws cloudformation create-stack \
        --stack-name ${STACK_NAME} \
        --template-body file://"${DIRNAME}"/sdlf-cicd/template-cicd-team-repos.yaml \
        --tags Key=Framework,Value=sdlf \
        --capabilities "CAPABILITY_NAMED_IAM" "CAPABILITY_AUTO_EXPAND" \
        --region ${REGION} \
        --profile ${DEVOPS_PROFILE}
    echo "Waiting for stack to be created ..."
    aws cloudformation wait stack-create-complete --profile ${DEVOPS_PROFILE} --region ${REGION} --stack-name ${STACK_NAME}
fi

if $oflag
then
    STACK_NAME=sdlf-cicd-shared-foundations-${ENV}
    echo creating stack ${STACK_NAME}
    aws cloudformation deploy \
        --stack-name ${STACK_NAME} \
        --template-file "${DIRNAME}"/sdlf-cicd/template-cicd-shared-foundations.yaml \
        --parameter-overrides \
            pEnvironment="${ENV}" \
            pChildAccountId="${CHILD_ACCOUNT}" \
        --tags Framework=sdlf \
        --capabilities "CAPABILITY_NAMED_IAM" "CAPABILITY_AUTO_EXPAND" \
        --region ${REGION} \
        --profile ${DEVOPS_PROFILE}
    echo "Waiting for stack to be created ..."
    aws cloudformation wait stack-create-complete --profile ${DEVOPS_PROFILE} --region ${REGION} --stack-name ${STACK_NAME}
fi

if $cflag
then
    # Increase SSM Parameter Store throughput to 1,000 requests/second
    aws ssm update-service-setting --setting-id arn:aws:ssm:${REGION}:${CHILD_ACCOUNT}:servicesetting/ssm/parameter-store/high-throughput-enabled --setting-value true --region ${REGION} --profile ${CHILD_PROFILE}
    DEVOPS_ACCOUNT_KMS=$(sed -e 's/^"//' -e 's/"$//' <<<"$(aws ssm get-parameter --name /SDLF/KMS/${ENV}/CICDKeyId --region ${REGION} --profile ${DEVOPS_PROFILE} --query "Parameter.Value")")
    STACK_NAME=sdlf-cicd-child-foundations
    aws cloudformation deploy \
        --stack-name ${STACK_NAME} \
        --template-file "${DIRNAME}"/sdlf-cicd/template-cicd-child-foundations.yaml \
        --parameter-overrides \
            pDemo="${DEMO}" \
            pEnvironment="${ENV}" \
            pSharedDevOpsAccountId="${DEVOPS_ACCOUNT}" \
            pSharedDevOpsAccountKmsKeyArn="${DEVOPS_ACCOUNT_KMS}" \
        --tags Framework=sdlf \
        --capabilities "CAPABILITY_NAMED_IAM" "CAPABILITY_AUTO_EXPAND" \
        --region ${REGION} \
        --profile ${CHILD_PROFILE}
    echo "Waiting for stack to be created ..."
    aws cloudformation wait stack-create-complete --profile ${CHILD_PROFILE} --region ${REGION} --stack-name ${STACK_NAME}
fi
