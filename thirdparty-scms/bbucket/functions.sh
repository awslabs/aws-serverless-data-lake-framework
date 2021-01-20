#!/bin/bash

function technical_requirements()
{
  echo "Verifying technical requirements"
  if [[ "$OSTYPE" == "darwin"* ]]; then
      SED=$(which gsed)
  else
      SED=$(which sed)
  fi
  $SED --version > /dev/null 2>&1
  if [[ $? -gt 0 ]]; then
      echo "sed binnary is necessary to execute the deployment" && exit 1
  fi
  jq --version > /dev/null 2>&1
  if [[ $? -gt 0 ]]; then
      echo "jq binnary is necessary to execute the deployment" && exit 1
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
    # Bitbucket mods
    cd ${DIRNAME}/${REPOSITORY}/
    /bin/test -d .git && rm -rf .git
    git init
    if [[ "${REPOSITORY}" == "sdlf-team" ]]; then #remove sdlf-team repositories creation
      $SED -i 's/bootstrap_team_repository ${TEAM_NAME} ${REPOSITORY}/echo "Creation delegated to external SCM"/g' scripts/bootstrap_team.sh
      cp -f ${SCM_DIR}/bitbucket-team-pipelines.yml ./bitbucket-pipelines.yml
    else
      cp -f ${SCM_DIR}/bitbucket-pipelines.yml ./bitbucket-pipelines.yml
    fi
    git add . 
    git commit -m "Initial Commit" > /dev/null
    BB_REPO=$(echo $REPOSITORY | awk '{print tolower($0)}' )
    echo "Creating repository ${PREFIX}-${REPOSITORY} on Bitbucket"
    set +e
    OUTPUT=$(curl -sS -X POST -H "Content-Type: application/json" -u $BBUSER:$APP_PASS  -d "{\"scm\": \"git\", \
     \"is_private\": \"true\",\"project\": {\"key\": \"$BBPROJECT\"} }" \
     https://api.bitbucket.org/2.0/repositories/$WORKSPACE/$PREFIX-$BB_REPO)
    STATUS=$? && set -e
    if [ ${STATUS} -ne 0 ] ; then
      if [[ ${OUTPUT} == *"Repository with this Slug"* ]] ; then
        echo -e "\nRepository named $PREFIX-$BB_REPO already exists in Bitbucket";
      else
        echo "Error. Verify the OUTPUT: ${OUTPUT}" && exit ${STATUS}
      fi
    else
      git remote add origin "https://$BBUSER:$APP_PASS@bitbucket.org/$WORKSPACE/$PREFIX-$BB_REPO.git"
      git push --set-upstream origin master
      git checkout -b test
      git push --set-upstream origin test
      git checkout -b dev
      git push --set-upstream origin dev
    fi
}

function setup_bitbucket_pipelines() {
    REPOSITORY=$1
    REMOTE_REPO=$REPOSITORY
    echo "Enabling pipeline ${PREFIX}-${REPOSITORY}"
    BB_REPO=$(echo $REPOSITORY | awk '{print tolower($0)}' )
    curl -sS -X PUT -H "Content-Type: application/json" -u ${BBUSER}:${APP_PASS} -d '{ "enabled": "true" }' \
    https://api.bitbucket.org/2.0/repositories/$WORKSPACE/${PREFIX}-${BB_REPO}/pipelines_config > /dev/null
    echo "Creating pipelines variables"
    curl -sS -X POST -H "Content-Type: application/json" -u ${BBUSER}:${APP_PASS} -d "{ \"type\": \"pipeline_variable\",\"key\": \"REMOTE_REPO\", \"value\": \"$REMOTE_REPO\", \"secured\": \"false\" }" \
    https://api.bitbucket.org/2.0/repositories/$WORKSPACE/${PREFIX}-${BB_REPO}/pipelines_config/variables/ > /dev/null
    if [[ "${REPOSITORY}" == "sdlf-team" ]]; then #remove sdlf-team repositories creation
      echo "Creating team variables for the repository:${PREFIX}-${BB_REPO}"
      curl -sS -X POST -H "Content-Type: application/json" -u ${BBUSER}:${APP_PASS} -d "{ \"type\": \"pipeline_variable\",\"key\": \"APP_PASS\", \"value\": \"$APP_PASS\", \"secured\": \"true\" }" \
      https://api.bitbucket.org/2.0/repositories/$WORKSPACE/${PREFIX}-${BB_REPO}/pipelines_config/variables/ > /dev/null
      curl -sS -X POST -H "Content-Type: application/json" -u ${BBUSER}:${APP_PASS} -d "{ \"type\": \"pipeline_variable\",\"key\": \"BBUSER\", \"value\": \"$BBUSER\", \"secured\": \"true\" }" \
      https://api.bitbucket.org/2.0/repositories/$WORKSPACE/${PREFIX}-${BB_REPO}/pipelines_config/variables/ > /dev/null
      echo "Creating PREFIX parameter"
      curl -sS -X POST -H "Content-Type: application/json" -u ${BBUSER}:${APP_PASS} -d "{ \"type\": \"pipeline_variable\",\"key\": \"PREFIX\", \"value\": \"$PREFIX\", \"secured\": \"false\" }" \
      https://api.bitbucket.org/2.0/repositories/$WORKSPACE/${PREFIX}-${BB_REPO}/pipelines_config/variables/ > /dev/null
    fi
    for branch in master test dev ; do
      echo "Executing pipeline for $branch"
      OUTPUT=$(curl -sS -X POST -H "Content-Type: application/json" -u ${BBUSER}:${APP_PASS} -d "{\"target\": { \"ref_type\": \"branch\", \"type\": \"pipeline_ref_target\", \"ref_name\": \"$branch\" } }" \
      https://api.bitbucket.org/2.0/repositories/$WORKSPACE/$PREFIX-$BB_REPO/pipelines/)
      UUID=$(echo $OUTPUT | jq -r .uuid)
      if [[  "$branch" == "master" ]]; then
        if [[ "$UUID" != "" && "$UUID" != "null" ]]; then
          for i in {1..12}; do # wait until 2 minutes. The master branch should be mirrored first
            echo "Waiting pipeline on master to finish..." && sleep 10
            STATE=$(curl -sS -H "Content-Type: application/json" -u ${BBUSER}:${APP_PASS} \
            "https://api.bitbucket.org/2.0/repositories/$WORKSPACE/$PREFIX-$BB_REPO/pipelines/\{$UUID\}" |jq -r .state.name)
            echo "The state of the pipeline with UUID $UUID of the repository $PREFIX-$BB_REPO is *$STATE*"
            if [[ "$STATE" == "COMPLETED" ]]; then break; fi
          done
        else
          echo "Error creating the pipeline. Check the output: $OUTPUT"
        fi
      fi
    done
}

function setup_bbucket_workspacevars() {
  echo "Creating workspace variables on BitBucket"
  curl -sS -X POST -H "Content-Type: application/json" -u ${BBUSER}:${APP_PASS} -d "{ \"type\": \"pipeline_variable\", \"key\": \"SDLF_AWS_ACCESS_KEY_ID\", \"value\": \"${SDLF_AWS_ACCESS_KEY_ID}\", \"secured\": \"true\" }" https://api.bitbucket.org/2.0/workspaces/$WORKSPACE/pipelines-config/variables > /dev/null
  curl -sS -X POST -H "Content-Type: application/json" -u ${BBUSER}:${APP_PASS} -d "{ \"type\": \"pipeline_variable\", \"key\": \"SDLF_AWS_SECRET_ACCESS_KEY\", \"value\": \"${SDLF_AWS_SECRET_ACCESS_KEY}\", \"secured\": \"true\" }" https://api.bitbucket.org/2.0/workspaces/$WORKSPACE/pipelines-config/variables > /dev/null
  curl -sS -X POST -H "Content-Type: application/json" -u ${BBUSER}:${APP_PASS} -d "{ \"type\": \"pipeline_variable\", \"key\": \"SDLF_AWS_SESSION_TOKEN\", \"value\": \"${SDLF_AWS_SESSION_TOKEN}\", \"secured\": \"true\" }" https://api.bitbucket.org/2.0/workspaces/$WORKSPACE/pipelines-config/variables > /dev/null
  curl -sS -X POST -H "Content-Type: application/json" -u ${BBUSER}:${APP_PASS} -d "{ \"type\": \"pipeline_variable\", \"key\": \"SDLF_AWS_REGION\", \"value\": \"${REGION}\", \"secured\": \"false\" }" https://api.bitbucket.org/2.0/workspaces/$WORKSPACE/pipelines-config/variables > /dev/null
  curl -sS -X POST -H "Content-Type: application/json" -u ${BBUSER}:${APP_PASS} -d "{ \"type\": \"pipeline_variable\", \"key\": \"SDLF_AWS_ROLE_TO_ASSUME_NAME\", \"value\": \"${SDLF_AWS_ROLE_TO_ASSUME_NAME}\", \"secured\": \"false\" }" https://api.bitbucket.org/2.0/workspaces/$WORKSPACE/pipelines-config/variables > /dev/null
  curl -sS -X POST -H "Content-Type: application/json" -u ${BBUSER}:${APP_PASS} -d "{ \"type\": \"pipeline_variable\", \"key\": \"SDLF_AWS_ROLE_TO_ASSUME_ARN\", \"value\": \"${SDLF_AWS_ROLE_TO_ASSUME_ARN}\", \"secured\": \"false\" }" https://api.bitbucket.org/2.0/workspaces/$WORKSPACE/pipelines-config/variables > /dev/null
}

function deploy_sdlf_foundations_scm() {
    technical_requirements
    cd "${DIRNAME}"
    echo "Getting configuration parameters"
    WORKSPACE=$(jq -r '.[] | select(.ParameterKey=="workspace") | .ParameterValue' ${SCM_DIR}/parameters.json)
    BBUSER=$(jq -r '.[] | select(.ParameterKey=="bitbucketuser") | .ParameterValue' ${SCM_DIR}/parameters.json)
    BBPROJECT=$(jq -r '.[] | select(.ParameterKey=="bitbucketprojectkey") | .ParameterValue' ${SCM_DIR}/parameters.json)
    APP_PASS=$(jq -r '.[] | select(.ParameterKey=="app_password") | .ParameterValue' ${SCM_DIR}/parameters.json)
    PREFIX=$(jq -r '.[] | select(.ParameterKey=="repository_prefix") | .ParameterValue' ${SCM_DIR}/parameters.json)
    SDLF_AWS_ACCESS_KEY_ID=$(jq -r '.[] | select(.ParameterKey=="sdlf_aws_access_key_id") | .ParameterValue' ${SCM_DIR}/parameters.json)
    SDLF_AWS_SECRET_ACCESS_KEY=$(jq -r '.[] | select(.ParameterKey=="sdlf_aws_secret_access_key") | .ParameterValue' ${SCM_DIR}/parameters.json)
    SDLF_AWS_SESSION_TOKEN=$(jq -r '.[] | select(.ParameterKey=="sdlf_aws_session_token") | .ParameterValue' ${SCM_DIR}/parameters.json)
    SDLF_AWS_ROLE_TO_ASSUME_NAME=$(jq -r '.[] | select(.ParameterKey=="sdlf_aws_role_to_assume_name") | .ParameterValue' ${SCM_DIR}/parameters.json)
    SDLF_AWS_ROLE_TO_ASSUME_ARN=$(jq -r '.[] | select(.ParameterKey=="sdlf_aws_role_to_assume_arn") | .ParameterValue' ${SCM_DIR}/parameters.json)

    setup_bbucket_workspacevars

    for REPOSITORY in "${REPOSITORIES[@]}"
    do
      echo =======================================================================
      bootstrap_repository_scm $REPOSITORY
      setup_bitbucket_pipelines $REPOSITORY
    done
    cd "${DIRNAME}"
}
