#!/bin/bash
set -e

pflag=false
rflag=false
eflag=false
dflag=false
cflag=false
vflag=false

DIRNAME=$(pwd)

usage () { echo "
    -h -- Opens up this help message
    -p -- Name of the AWS profile to be used for the Child Account
    -r -- AWS Region to deploy to (e.g. eu-west-1)
    -e -- Environment to deploy to (dev, test or prod)
    -c -- Create resources
    -v -- Verbose mode
    -d -- Demo mode
"; }

options='p:r:e:dclvh'
while getopts $options option
do
    case "$option" in
        p  ) pflag=true; CHILD_PROFILE=${OPTARG};;
        r  ) rflag=true; REGION=${OPTARG};;
        e  ) eflag=true; ENV=${OPTARG};;
        d  ) dflag=true;;
        c  ) cflag=true;;
        v  ) set -x;;
        h  ) usage; exit;;
        \? ) echo "Unknown option: -$OPTARG" >&2; exit 1;;
        :  ) echo "Missing option argument for -$OPTARG" >&2; exit 1;;
        *  ) echo "Unimplemented option: -$OPTARG" >&2; exit 1;;
    esac
done

if ! $pflag
then
    echo "-p not specified, using default aws profile..." >&2
    CHILD_PROFILE="default"
fi
if ! $rflag
then
    echo "-r not specified, using default aws region..." >&2
    REGION=$(aws configure get region --profile ${CHILD_PROFILE})
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
    lflag=true
fi

for row in $(jq -c '.[]' parameters-${ENV}.json); do
    KEY=$(echo "${row}" | jq -r '.ParameterKey')
    VAL=$(echo "${row}" | jq -r '.ParameterValue')
    KEY_VAL="${KEY}=\\\"${VAL}\\\" "
    PARAMETER_OVERRIDES="${PARAMETER_OVERRIDES}${KEY_VAL}"
    if [ "${KEY}" == "pTeamName" ]; then
        TEAM_NAME="${VAL}"
    fi
done
PARAMETER_OVERRIDES="${PARAMETER_OVERRIDES}"

CHILD_ACCOUNT=$(aws sts get-caller-identity --query 'Account' --output text --profile ${CHILD_PROFILE})
STACK_NAME="sdlf-${ENV}-unzip-fargate"
APPLICATION_BUILD_OUTPUT_DIRECTORY='.aws-sam/build'

if ! jq --version &> /dev/null
then
    echo "jq could not be found, installing..."
    echo y | sudo yum install jq
fi

if command -v pip3 &> /dev/null
then
    pip3 install -q --upgrade aws-sam-cli
elif command -v pip &> /dev/null
then
    pip install -q --upgrade aws-sam-cli
else
    echo "pip: command not found. Please install it"
    exit 1
fi


echo "ENV: ${ENV}"
echo "PROFILE: ${CHILD_PROFILE}"
echo "REGION: ${REGION}"
echo "STACK_NAME: ${STACK_NAME}"


read -n 1 -s -r -p "Check parameters and press any key to continue..."

echo ""
if $cflag
then
    echo "============================================================="
    echo "Creating Cloudformation stack with required permissions"
    echo "============================================================="
    if ! $dflag
    then
        echo "Validating SAM template"
        sam validate --template template.yaml --profile "${CHILD_PROFILE}"

        echo "Building SAM..."
        sam build \
            --template-file template.yaml \
            --build-dir "${APPLICATION_BUILD_OUTPUT_DIRECTORY}"

        echo "Creating samconfig.toml file"
        rm -f samconfig.toml
        cat <<EOF > samconfig.toml
version = 0.1
[default]
[default.deploy]
[default.deploy.parameters]
stack_name = "${STACK_NAME}"
region = "${REGION}"
confirm_changeset = true
capabilities = "CAPABILITY_IAM CAPABILITY_NAMED_IAM"
parameter_overrides = "${PARAMETER_OVERRIDES}"
EOF


        echo "Deploying SAM template..."
        sam deploy \
            --guided \
            --profile "${CHILD_PROFILE}"
    else
        echo "<<DEMO>>: Creating Cloudformation Stack with the required permissions $STACK_NAME"
    fi
fi

