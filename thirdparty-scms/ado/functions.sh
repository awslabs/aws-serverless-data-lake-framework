#!/bin/bash

function technical_requirements()
{
  echo "Verifying technical requirements"
  if [[ "$OSTYPE" == "darwin"* ]]; then
      SED=$(which gsed)
  else
      SED=$(which sed)
  fi
  $SED --version > /dev/null
  if [[ $? -gt 0 ]]; then
      echo "sed binnary is necessary to execute the deployment" && exit 1
  fi
  jq --version > /dev/null
  if [[ $? -gt 0 ]]; then
      echo "jq binnary is necessary to execute the deployment" && exit 1
  fi
  echo "Verifying if az cli is authenticated Azure"
  output=$(az account list 2>&1)
  if [[ "$output" == *"Please run"* ]]; then
      echo "You have to be authenticated to deploy from Azure DevOps" && exit 1
  fi
}

function bootstrap_repository_scm()
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
    if [[ "${REPOSITORY}" == "sdlf-team" ]]; then
      cp -f ${SCM_DIR}/azure-pipelines-team-template.yml ${SCM_DIR}/azure-pipelines.yml
    else
      cp -f ${SCM_DIR}/azure-pipelines-template.yml ${SCM_DIR}/azure-pipelines.yml
    fi
    $SED -i "s/<REPOSITORY>/${REPOSITORY}/g" ${SCM_DIR}/azure-pipelines.yml
    $SED -i "s/REGION/${REGION}/g" ${SCM_DIR}/azure-pipelines.yml
    $SED -i "s/SERVICE_CONNECTION/${SERVICE_CONNECTION}/g" ${SCM_DIR}/azure-pipelines.yml
    
    cp -f ${SCM_DIR}/azure-pipelines.yml ${DIRNAME}/${REPOSITORY}/azure-pipelines.yml
    cd ${DIRNAME}/${REPOSITORY}/
    /bin/test -d .git && rm -rf .git
    git init
    if [[ "${REPOSITORY}" == "sdlf-team" ]]; then #remove sdlf-team repositories creation
      $SED -i 's/bootstrap_team_repository ${TEAM_NAME} ${REPOSITORY}/echo "Creation delegated to external SCM"/g' scripts/bootstrap_team.sh
    fi
    git add . 
    git commit -m "Initial Commit" > /dev/null
    # Azure mods
    echo "Creating repository ${PREFIX}-${REPOSITORY} on Azure DevOps"
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
      PIPELINE_ID=$(az pipelines run --name ${PREFIX}-${REPOSITORY} --branch ${BRANCH} --folder-path "sdlf" | jq -r .id)
      if [[ "${REPOSITORY}" == "sdlf-team" ||  "${REPOSITORY}" == "sdlf-foundations" ]]; then # these repositories must be populated synchronously
        STATUS=$(az pipelines runs show --id ${PIPELINE_ID} | jq -r .status)
        while [ "$STATUS" != "completed" ]; do
          echo "Waiting for the pipeline ${PREFIX}-${REPOSITORY} on branch ${BRANCH} to finish" && sleep 7
          STATUS=$(az pipelines runs show --id ${PIPELINE_ID} | jq -r .status)
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
    cp -f ${SCM_DIR}/service-connection-template.json ${SCM_DIR}/service-connection.json
    $SED -i "s|PROJECT|${PROJECT}|g" ${SCM_DIR}/service-connection.json
    $SED -i "s|AWS_ACCESS_KEY|${AWS_ACCESS_KEY}|g" ${SCM_DIR}/service-connection.json
    $SED -i "s|AWS_SECRET_KEY|${AWS_SECRET_KEY}|g" ${SCM_DIR}/service-connection.json
    $SED -i "s|SERVICE_CONNECTION|${SERVICE_CONNECTION}|g" ${SCM_DIR}/service-connection.json

    az devops configure --defaults organization="https://dev.azure.com/$ORG" project="$PROJECT"
    echo "Creating service-connection \"${SERVICE_CONNECTION}\" on the project: \"${PROJECT}\""
    SC_ID=$(az devops service-endpoint create --service-endpoint-configuration \
      ${SCM_DIR}/service-connection.json | jq -r .id)
    az devops service-endpoint update --id ${SC_ID} --enable-for-all > /dev/null
}

function deploy_sdlf_foundations_scm() {
    technical_requirements
    cd "${DIRNAME}"
    declare -a REPOSITORIES=("sdlf-team" "sdlf-foundations" "sdlf-pipeline" "sdlf-dataset" "sdlf-datalakeLibrary" "sdlf-pipLibrary" "sdlf-stageA" "sdlf-stageB")
    echo "Getting configuration parameters"
    ORG=$(jq -r '.[] | select(.ParameterKey=="organization") | .ParameterValue' ${SCM_DIR}/parameters.json)
    PROJECT=$(jq -r '.[] | select(.ParameterKey=="project") | .ParameterValue' ${SCM_DIR}/parameters.json)
    PREFIX=$(jq -r '.[] | select(.ParameterKey=="repository-prefix") | .ParameterValue' ${SCM_DIR}/parameters.json)
    AWS_CC_USER=$(jq -r '.[] | select(.ParameterKey=="aws-codecommit-user") | .ParameterValue' ${SCM_DIR}/parameters.json)
    IAM_USER=$(aws iam list-users --profile ${DEVOPS_PROFILE} | jq -r --arg USER "${AWS_CC_USER}" '.Users[] |select(.UserName==$USER) | .UserName')
    SERVICE_CONNECTION=$(jq -r '.[] | select(.ParameterKey=="service-connection-name") | .ParameterValue' ${SCM_DIR}/parameters.json)
    TOKEN=$(jq -r '.[] | select(.ParameterKey=="sdlf-aztoken") | .ParameterValue' ${SCM_DIR}/parameters.json)

    if [[ "${IAM_USER}" == "" ]]; then
      echo "Creating CodeCommit User on AWS";
      aws iam create-user --user-name ${AWS_CC_USER} --profile ${DEVOPS_PROFILE} > /dev/null
      cp -f ${SCM_DIR}/aws-codecommit-policy-template.json ${SCM_DIR}/aws-codecommit-policy.json
      $SED -i "s/REGION/${REGION}/g" ${SCM_DIR}/aws-codecommit-policy.json
      $SED -i "s/ACCOUNT_ID/${DEVOPS_ACCOUNT}/g" ${SCM_DIR}/aws-codecommit-policy.json
      POLICY_ARN=$(aws iam create-policy --policy-name ${AWS_CC_USER}-policy --policy-document --profile ${DEVOPS_PROFILE} \
        file://${SCM_DIR}/aws-codecommit-policy.json |jq -r '.Policy.Arn')
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
      echo "bootstrap_repository_scm ${REPOSITORY}..."
      bootstrap_repository_scm $REPOSITORY
      echo "setup_azure_pipelines ${REPOSITORY}"
      setup_azure_pipelines $REPOSITORY
    done
    cd "${DIRNAME}"
}
