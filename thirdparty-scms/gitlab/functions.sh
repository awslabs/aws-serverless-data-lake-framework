#!/bin/bash

function technical_requirements()
{
  echo "Verifying technical requirements"
  if [[ "$OSTYPE" == "darwin"* ]]; then
    if ! command -v gsed &> /dev/null; then
        echo "sed binary is necessary to execute the deployment" && exit 1
    fi
    SED=$(command -v gsed)
  else
    if ! command -v sed &> /dev/null; then
        echo "sed binary is necessary to execute the deployment" && exit 1
    fi
    SED=$(command -v sed)
  fi

  if ! command -v jq &> /dev/null; then
      echo "jq binary is necessary to execute the deployment" && exit 1
  fi
}

function bootstrap_repository_scm()
{
    REPOSITORY=$1
    echo "Creating repository $REPOSITORY on AWS" && set +e
    OUTPUT=$(aws codecommit create-repository --region "$REGION" --profile "$DEVOPS_PROFILE" --repository-name "$REPOSITORY" 2>&1)
    STATUS=$? && set -e
    if [ "$STATUS" -ne 0 ] ; then
      if [[ $OUTPUT == *"RepositoryNameExistsException"* ]] ; then
        echo -e "\nRepository named $REPOSITORY already exists in AWS";
      else
        echo "Error: $OUTPUT" && exit "$STATUS"
      fi
    fi
    # GitLab mods
    cd "$DIRNAME/$REPOSITORY"/
    if [[ $(git rev-parse --git-dir) != "." ]]; then
      [[ -d .git ]] && rm -rf .git
      git init -b master
      git add .
      git commit -m "Initial Commit" > /dev/null
      git branch test
      git branch dev
    fi
    if [[ "$REPOSITORY" == "sdlf-team" ]]; then # remove sdlf-team repositories creation
      # shellcheck disable=SC2016
      "$SED" -i 's/bootstrap_team_repository "$TEAM_NAME" "$REPOSITORY"/echo "Creation delegated to external SCM"/g' scripts/bootstrap_team.sh
      cp -f "$SCM_DIR"/functions.sh ./scripts/functions.sh
      cp -f "$SCM_DIR"/gitlab-team-pipelines.yml ./.gitlab-ci.yml
    fi

    declare -a GITLAB_REPOSITORY_PATH_PARTS=("$GROUP" "$TEAM" "$REPOSITORY")
    GITLAB_REPOSITORY_PATH=$(printf '%s/' "${GITLAB_REPOSITORY_PATH_PARTS[@]}" | tr -s /)
    echo "Creating repository ${PREFIX}-${REPOSITORY} on GitLab"
    set +e
    if [[ -z "$GROUP_ID" ]] ; then
      GROUP_ID=$(curl -sS -H "PRIVATE-TOKEN: $API_TOKEN" "https://$GITLAB_HOST/api/v4/groups/$GROUP" | jq -r '.id')
    fi
    OUTPUT=$(curl -sS -X POST -H "Content-Type: application/json" -H "PRIVATE-TOKEN: $API_TOKEN" \
     -d "{\"name\": \"$REPOSITORY\", \"namespace_id\": \"$GROUP_ID\"}" \
     https://"$GITLAB_HOST"/api/v4/projects/)
    STATUS=$? && set -e
    if [ "$STATUS" -ne 0 ] ; then
      if [[ ${OUTPUT} == *"Repository with this Slug"* ]] ; then
        echo -e "\nRepository named $PREFIX-$REPOSITORY already exists in GitLab";
      else
        echo "Error. Verify the OUTPUT: ${OUTPUT}" && exit "$STATUS"
      fi
    else
      if [[ "$REPOSITORY" == "sdlf-team" ]]; then
        setup_gitlab_projectvars
      fi
      # setup push mirroring
      echo "Setting up push mirroring from GitLab to CodeCommit for repository $PREFIX-$REPOSITORY"
      curl -sS -X POST -H "Content-Type: application/json" -H "PRIVATE-TOKEN: $API_TOKEN" \
      -d "{ \"enabled\": \"true\", \"url\": \"https://$SDLF_AWS_CODECOMMIT_USERNAME:$SDLF_AWS_CODECOMMIT_PASSWORD@git-codecommit.$REGION.amazonaws.com/v1/repos/$REPOSITORY\"}" \
      https://"$GITLAB_HOST"/api/v4/projects/"$(printf '%s' "${GITLAB_REPOSITORY_PATH%/}" | jq -s -R -r @uri)"/remote_mirrors > /dev/null

      git push --mirror "https://placeholder:$API_TOKEN@$GITLAB_HOST/${GITLAB_REPOSITORY_PATH%/}.git"
    fi
}

function setup_gitlab_projectvars() {
  echo "Creating project variables on GitLab, used in gitlab-ci.yml"
  curl -sS -X POST -H "Content-Type: application/json" -H "PRIVATE-TOKEN: $API_TOKEN" -d "{ \"key\": \"GITLAB_HOST\", \"value\": \"${GITLAB_HOST}\", \"masked\": \"false\" }" https://"$GITLAB_HOST"/api/v4/projects/"$GROUP"%2Fsdlf-team/variables > /dev/null
  curl -sS -X POST -H "Content-Type: application/json" -H "PRIVATE-TOKEN: $API_TOKEN" -d "{ \"key\": \"GROUP\", \"value\": \"${GROUP}\", \"masked\": \"false\" }" https://"$GITLAB_HOST"/api/v4/projects/"$GROUP"%2Fsdlf-team/variables > /dev/null
  curl -sS -X POST -H "Content-Type: application/json" -H "PRIVATE-TOKEN: $API_TOKEN" -d "{ \"key\": \"PREFIX\", \"value\": \"${PREFIX}\", \"masked\": \"false\" }" https://"$GITLAB_HOST"/api/v4/projects/"$GROUP"%2Fsdlf-team/variables > /dev/null
  curl -sS -X POST -H "Content-Type: application/json" -H "PRIVATE-TOKEN: $API_TOKEN" -d "{ \"key\": \"API_TOKEN\", \"value\": \"${API_TOKEN}\", \"masked\": \"true\" }" https://"$GITLAB_HOST"/api/v4/projects/"$GROUP"%2Fsdlf-team/variables > /dev/null
  curl -sS -X POST -H "Content-Type: application/json" -H "PRIVATE-TOKEN: $API_TOKEN" -d "{ \"key\": \"SDLF_AWS_ACCESS_KEY_ID\", \"value\": \"${SDLF_AWS_ACCESS_KEY_ID}\", \"masked\": \"true\" }" https://"$GITLAB_HOST"/api/v4/projects/"$GROUP"%2Fsdlf-team/variables > /dev/null
  curl -sS -X POST -H "Content-Type: application/json" -H "PRIVATE-TOKEN: $API_TOKEN" -d "{ \"key\": \"SDLF_AWS_SECRET_ACCESS_KEY\", \"value\": \"${SDLF_AWS_SECRET_ACCESS_KEY}\", \"masked\": \"true\" }" https://"$GITLAB_HOST"/api/v4/projects/"$GROUP"%2Fsdlf-team/variables > /dev/null
  curl -sS -X POST -H "Content-Type: application/json" -H "PRIVATE-TOKEN: $API_TOKEN" -d "{ \"key\": \"SDLF_AWS_SESSION_TOKEN\", \"value\": \"${SDLF_AWS_SESSION_TOKEN}\", \"masked\": \"true\" }" https://"$GITLAB_HOST"/api/v4/projects/"$GROUP"%2Fsdlf-team/variables > /dev/null
  curl -sS -X POST -H "Content-Type: application/json" -H "PRIVATE-TOKEN: $API_TOKEN" -d "{ \"key\": \"SDLF_AWS_REGION\", \"value\": \"${REGION}\", \"masked\": \"false\" }" https://"$GITLAB_HOST"/api/v4/projects/"$GROUP"%2Fsdlf-team/variables > /dev/null
  curl -sS -X POST -H "Content-Type: application/json" -H "PRIVATE-TOKEN: $API_TOKEN" -d "{ \"key\": \"SDLF_AWS_ROLE_TO_ASSUME_NAME\", \"value\": \"${SDLF_AWS_ROLE_TO_ASSUME_NAME}\", \"masked\": \"false\" }" https://"$GITLAB_HOST"/api/v4/projects/"$GROUP"%2Fsdlf-team/variables > /dev/null
  curl -sS -X POST -H "Content-Type: application/json" -H "PRIVATE-TOKEN: $API_TOKEN" -d "{ \"key\": \"SDLF_AWS_ROLE_TO_ASSUME_ARN\", \"value\": \"${SDLF_AWS_ROLE_TO_ASSUME_ARN}\", \"masked\": \"false\" }" https://"$GITLAB_HOST"/api/v4/projects/"$GROUP"%2Fsdlf-team/variables > /dev/null
}

function deploy_sdlf_team_repositories() {
    technical_requirements
    for REPOSITORY in "${REPOSITORIES[@]}"
    do
      echo =======================================================================
      bootstrap_repository_scm "$REPOSITORY"
    done
}

function deploy_sdlf_foundations_scm() {
    technical_requirements
    cd "$DIRNAME"
    echo "Getting configuration parameters"
    GITLAB_HOST=$(jq -r '.[] | select(.ParameterKey=="gitlab_host") | .ParameterValue' "$SCM_DIR"/parameters.json)
    GROUP=$(jq -r '.[] | select(.ParameterKey=="group") | .ParameterValue' "$SCM_DIR"/parameters.json)
    API_TOKEN=$(jq -r '.[] | select(.ParameterKey=="api_token") | .ParameterValue' "$SCM_DIR"/parameters.json)
    PREFIX=$(jq -r '.[] | select(.ParameterKey=="repository_prefix") | .ParameterValue' "$SCM_DIR"/parameters.json)
    SDLF_AWS_ACCESS_KEY_ID=$(jq -r '.[] | select(.ParameterKey=="sdlf_aws_access_key_id") | .ParameterValue' "$SCM_DIR"/parameters.json)
    SDLF_AWS_SECRET_ACCESS_KEY=$(jq -r '.[] | select(.ParameterKey=="sdlf_aws_secret_access_key") | .ParameterValue' "$SCM_DIR"/parameters.json)
    SDLF_AWS_SESSION_TOKEN=$(jq -r '.[] | select(.ParameterKey=="sdlf_aws_session_token") | .ParameterValue' "$SCM_DIR"/parameters.json)
    SDLF_AWS_ROLE_TO_ASSUME_NAME=$(jq -r '.[] | select(.ParameterKey=="sdlf_aws_role_to_assume_name") | .ParameterValue' "$SCM_DIR"/parameters.json)
    SDLF_AWS_ROLE_TO_ASSUME_ARN=$(jq -r '.[] | select(.ParameterKey=="sdlf_aws_role_to_assume_arn") | .ParameterValue' "$SCM_DIR"/parameters.json)
    SDLF_AWS_CODECOMMIT_USERNAME=$(jq -r '.[] | select(.ParameterKey=="sdlf_aws_codecommit_username") | .ParameterValue' "$SCM_DIR"/parameters.json)
    SDLF_AWS_CODECOMMIT_PASSWORD=$(jq -r '.[] | select(.ParameterKey=="sdlf_aws_codecommit_password") | .ParameterValue' "$SCM_DIR"/parameters.json)

    for REPOSITORY in "${REPOSITORIES[@]}"
    do
      echo =======================================================================
      bootstrap_repository_scm "$REPOSITORY"
    done
    cd "$DIRNAME"
}
