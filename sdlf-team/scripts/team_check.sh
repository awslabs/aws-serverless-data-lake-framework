#!/bin/bash
DIRNAME=$PWD
TEAM_NAME=$(sed -e 's/^"//' -e 's/"$//' <<<"$(jq '.[] | select(.ParameterKey=="pTeamName") | .ParameterValue' "$DIRNAME/../parameters-$ENV".json)")

# Retries a command a with backoff.
#
# The retry count is given by ATTEMPTS (default 5), the
# initial backoff timeout is given by TIMEOUT in seconds
# (default 1.)
#
# Successive backoffs double the timeout.
#
# Beware of set -e killing your whole script!
function with_backoff {
  local max_attempts=${ATTEMPTS-4}
  local timeout=${TIMEOUT-20}
  local attempt=0
  local exitCode=0

  while [[ $attempt -lt $max_attempts ]]
  do
    "$@"
    exitCode=$?

    if [[ $exitCode == 0 ]]
    then
      break
    fi

    echo "Failed... Retrying in $timeout.." 1>&2
    sleep "$timeout"
    attempt=$(( attempt + 1 ))
    timeout=$(( timeout * 2 ))
  done

  if [[ $exitCode != 0 ]]
  then
    # shellcheck disable=SC2028,SC2145
    echo "Command ($@) failed all attempts\n Please check that IAM role sdlf-cicd-team-codecommit-${ENV}-${TEAM_NAME} exists in the DevOps account" 1>&2
    exit 1
  fi

  return "$exitCode"
}

with_backoff aws iam get-role --role-name sdlf-cicd-team-codecommit-"$ENV-$TEAM_NAME" --profile crossaccount
