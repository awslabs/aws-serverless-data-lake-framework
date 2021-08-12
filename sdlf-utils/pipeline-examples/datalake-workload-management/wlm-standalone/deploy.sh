#!/bin/bash
pflag=false
rflag=false
sflag=false

DIRNAME=$(pwd)

usage () { echo "
    -h -- Opens up this help message
    -p -- Name of the AWS profile to use for the Account
    -r -- AWS Region to deploy to (e.g. eu-west-1)
    -s -- S3 bucket to store artifact
"; }
options=':p:r:s:h'
while getopts $options option
do
    case "$option" in
        p  ) pflag=true; PROFILE=${OPTARG};;
        r  ) rflag=true; REGION=${OPTARG};;
        s  ) sflag=true; S3_BUCKET=$OPTARG;;
        h  ) usage; exit;;
        \? ) echo "Unknown option: -$OPTARG" >&2; exit 1;;
        :  ) echo "Missing option argument for -$OPTARG" >&2; exit 1;;
        *  ) echo "Unimplemented option: -$OPTARG" >&2; exit 1;;
    esac
done

if ! $pflag
then
    echo "-s not specified, using default..." >&2
    DEVOPS_PROFILE="default"
fi
if ! $rflag
then
    echo "-r not specified, using default region..." >&2
    REGION=$(aws configure get region --profile ${PROFILE})
fi

ACCOUNT=$(aws sts get-caller-identity --query 'Account' --output text --profile ${PROFILE})

if ! $sflag
then
    S3_BUCKET="wlm-$ACCOUNT-$REGION-artifact-bucket"
fi


echo "Checking if bucket exists ..."
if ! aws s3 ls $S3_BUCKET --profile $PROFILE; then
  echo "S3 bucket named $S3_BUCKET does not exist. Create? [Y/N]"
  read choice
  if [ $choice == "Y" ] || [ $choice == "y" ]; then
    aws s3api create-bucket --bucket $S3_BUCKET --profile $PROFILE --create-bucket-configuration LocationConstraint=$REGION
  else
    echo "Bucket does not exist. Deploy aborted."
    exit 1
  fi
fi

STACK_NAME="wlm-infra-stack"

mkdir $DIRNAME/output
aws cloudformation package --profile $PROFILE --template-file $DIRNAME/template.yaml --s3-bucket $S3_BUCKET --region $REGION --output-template-file $DIRNAME/output/packaged-template.yaml

echo "Checking if stack exists ..."
if ! aws cloudformation describe-stacks --profile $PROFILE --stack-name $STACK_NAME --region $REGION; then
  echo -e "Stack does not exist, creating ..."
  aws cloudformation create-stack \
    --stack-name $STACK_NAME \
    --template-body file://$DIRNAME/output/packaged-template.yaml \
    --capabilities "CAPABILITY_NAMED_IAM" "CAPABILITY_AUTO_EXPAND" \
    --profile $PROFILE \
    --region $REGION 

  echo "Waiting for stack to be created ..."
  aws cloudformation wait stack-create-complete --profile $PROFILE \
    --stack-name $STACK_NAME --region $REGION
else
  echo -e "Stack exists, attempting update ..."

  set +e
  update_output=$( aws cloudformation update-stack \
    --profile $PROFILE \
    --stack-name $STACK_NAME \
    --template-body file://$DIRNAME/output/packaged-template.yaml \
    --region $REGION \
    --capabilities "CAPABILITY_NAMED_IAM" "CAPABILITY_AUTO_EXPAND" 2>&1)
  status=$?
  set -e

  echo "$update_output"

  if [ $status -ne 0 ] ; then
    # Don't fail for no-op update
    if [[ $update_output == *"ValidationError"* && $update_output == *"No updates"* ]] ; then
      echo -e "\nFinished create/update - no updates to be performed";
      exit 0;
    else
      exit $status
    fi
  fi

  echo "Waiting for stack update to complete ..."
  aws cloudformation wait stack-update-complete --profile $PROFILE \
    --stack-name $STACK_NAME --region $REGION
  echo "Finished create/update successfully!"
fi

python $DIRNAME/utils/fill_ddb.py $PROFILE $REGION