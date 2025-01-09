#!/bin/bash

bold=$(tput bold)
underline=$(tput smul)
notunderline=$(tput rmul)
notbold=$(tput sgr0)

die() {
    printf '%s\n' "$1" >&2
    exit 1
}

version () { echo "awssdlf/2.7.0"; }

usage () { echo "
Serverless Data Lake Framework (SDLF) is a collection of infrastructure-as-code artifacts to deploy data architectures on AWS.
This script creates a CodeBuild project with the set of permissions required to deploy the specified SDLF constructs.

Usage: ./deploy-generic.sh [-V | --version] [-h | --help] [-p | --profile <aws-profile>] [-c sdlf-construct1 | --construct sdlf-construct1 ] [-c sdlf-construct...] <name>

Options
  -V, --version -- Print the SDLF version
  -h, --help -- Show this help message
  -p -- Name of the AWS profile to use
  -c -- Name of the SDLF construct that will be used
  <name> -- Name to uniquely identify this deployment

  ${underline}-c sdlf${notunderline} can be used as a shorthand for "all SDLF constructs"
  ${underline}-c sdlf-stage${notunderline} can be used as a shorthand for "all SDLF Stage constructs"

Examples
  Create a CodeBuild project named sdlf-main able to deploy any SDLF construct:
  ${bold}./deploy-generic.sh${notbold} ${underline}sdlf-main${notunderline} ${bold}-c${notbold} ${underline}sdlf${notunderline}

  Create a CodeBuild project named sdlf-data-team able to deploy technical catalogs, data processing workflows and consumption tools:
  ${bold}./deploy-generic.sh${notbold} ${underline}sdlf-data-team${notunderline} ${bold}-c${notbold} ${underline}sdlf-dataset${notunderline} ${bold}-c${notbold} ${underline}sdlf-stage${notunderline} ${bold}-c${notbold} ${underline}sdlf-team${notunderline}

More details and examples on https://sdlf.readthedocs.io/en/latest/constructs/cicd/
"; }

pflag=false
rflag=false
cflag=false

DIRNAME=$(dirname "$0")

while :; do
    case $1 in
        -h|-\?|--help)
            usage
            exit
            ;;
        -V|--version)
            version
            exit
            ;;
        -p|--profile)
            if [ "$2" ]; then
                pflag=true;
                PROFILE=$2
                shift
            else
                die 'ERROR: "--profile" requires a non-empty option argument.'
            fi
            ;;
        --profile=?*)
            pflag=true;
            PROFILE=${1#*=} # delete everything up to "=" and assign the remainder
            ;;
        --profile=) # handle the case of an empty --profile=
            die 'ERROR: "--profile" requires a non-empty option argument.'
            ;;
        -r|--region)
            if [ "$2" ]; then
                rflag=true;
                REGION=$2
                shift
            else
                die 'ERROR: "--region" requires a non-empty option argument.'
            fi
            ;;
        --region=?*)
            rflag=true;
            REGION=${1#*=} # delete everything up to "=" and assign the remainder
            ;;
        --region=) # handle the case of an empty --region=
            die 'ERROR: "--region" requires a non-empty option argument.'
            ;;
        -c|--construct)
            if [ "$2" ]; then
                CONSTRUCTS+=("$2")
                shift
            else
                die 'ERROR: "--construct" requires a non-empty option argument.'
            fi
            ;;
        --construct=?*)
            CONSTRUCTS+=("${1#*=}") # delete everything up to "=" and assign the remainder
            ;;
        --construct=) # handle the case of an empty --profile=
            die 'ERROR: "--construct" requires a non-empty option argument.'
            ;;
        --) # end of all options
            shift
            break
            ;;
        -?*)
            printf 'WARN: Unknown option (ignored): %s\n' "$1" >&2
            ;;
        *) # default case: no more options, so break out of the loop
            break
    esac

    shift
done

if [ -z ${1+x} ]; then die 'ERROR: "./deploy-generic.sh" requires a non-option argument.'; fi

if "$pflag"
then
    echo "using AWS profile $PROFILE..." >&2
fi
if "$rflag"
then
    echo "using AWS region $REGION..." >&2
fi

STACK_NAME="sdlf-cicd-$1"
echo "CloudFormation stack name: $STACK_NAME"
aws cloudformation deploy \
    --stack-name "$STACK_NAME" \
    --template-file "$DIRNAME"/template-cicd-generic-git.yaml \
    --tags Framework=sdlf \
    --capabilities "CAPABILITY_NAMED_IAM" "CAPABILITY_AUTO_EXPAND" \
    ${REGION:+--region "$REGION"} \
    ${PROFILE:+--profile "$PROFILE"} || exit 1
