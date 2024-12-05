#!/bin/bash
pflag=false

DIRNAME=$(dirname "$0")

usage () { echo "
    -h -- Opens up this help message
    -p -- Name of the AWS profile to use
"; }
options=':p:h'
while getopts "$options" option
do
    case "$option" in
        p  ) pflag=true; PROFILE=$OPTARG;;
        h  ) usage; exit;;
        \? ) echo "Unknown option: -$OPTARG" >&2; exit 1;;
        :  ) echo "Missing option argument for -$OPTARG" >&2; exit 1;;
        *  ) echo "Unimplemented option: -$OPTARG" >&2; exit 1;;
    esac
done

if ! "$pflag"
then
    echo "-p not specified, using default..." >&2
    PROFILE="default"
fi
REGION=$(aws configure get region --profile "$PROFILE")

STACK_NAME="sdlf-cicd"
aws cloudformation deploy \
    --stack-name "$STACK_NAME" \
    --template-file "$DIRNAME"/template-cicd-generic-git.yaml \
    --tags Framework=sdlf \
    --capabilities "CAPABILITY_NAMED_IAM" "CAPABILITY_AUTO_EXPAND" \
    --region "$REGION" \
    --profile "$PROFILE" || exit 1
