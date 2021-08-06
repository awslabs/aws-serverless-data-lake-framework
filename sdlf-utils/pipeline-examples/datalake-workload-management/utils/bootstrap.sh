#!/bin/bash
set -Eeuox pipefail

pflag=false
rflag=false
bflag=false

DIRNAME=$(pwd)

usage () { echo "
    -h -- Opens up this help message
    -p -- AWS profile
    -r -- AWS Region to deploy to (e.g. eu-west-1)
    -b -- foundational Bucket name for artifacts
"; }
options=':p:r:b:h'
while getopts $options option
do
    case "$option" in
        p  ) pflag=true; PROFILE=${OPTARG};;
        r  ) rflag=true; AWS_DEFAULT_REGION=${OPTARG};;
        b  ) bflag=true; BUCKET=${OPTARG};;
        h  ) usage; exit;;
        \? ) echo "Unknown option: -$OPTARG" >&2; exit 1;;
        :  ) echo "Missing option argument for -$OPTARG" >&2; exit 1;;
        *  ) echo "Unimplemented option: -$OPTARG" >&2; exit 1;;
    esac
done


if ! $pflag
then
    echo "-p not specified, using region as us-east-1..." >&2
    PROFILE="default"
fi

if ! $rflag
then
    echo "-r not specified, using region as us-east-1..." >&2
    AWS_DEFAULT_REGION="us-east-1"
fi


[ -z "$AWS_DEFAULT_REGION" ] && echo "AWS_DEFAULT_REGION is empty" && exit 1

ACCOUNT_NUMBER=`aws sts get-caller-identity --query Account --output text --profile ${PROFILE} --region ${AWS_DEFAULT_REGION}`

if ! $bflag
then
    echo "-b not specified, using deafult bucket naming" >&2
    BUCKET="workload-management-$AWS_DEFAULT_REGION-$ACCOUNT_NUMBER-landing-bucket"
fi

echo "Region selected is $AWS_DEFAULT_REGION"
echo "BUCKET selected is $BUCKET"
echo "PROFILE selected is $PROFILE"


# Clean up and drop demo data into bucket
aws s3 rm s3://${BUCKET}/ --quiet --recursive --profile $PROFILE --region $AWS_DEFAULT_REGION
aws s3 cp $DIRNAME/utils/data/ s3://${BUCKET}/data/ --quiet --recursive --exclude "*.DS_STORE" --profile $PROFILE --region $AWS_DEFAULT_REGION 
aws s3 cp $DIRNAME/utils/trigger/ s3://${BUCKET}/data/ --quiet --recursive --exclude "*.DS_STORE" --profile $PROFILE --region $AWS_DEFAULT_REGION 

