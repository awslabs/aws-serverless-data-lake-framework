#!/bin/bash
sflag=false
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

ARTIFACTS_BUCKET=$(aws --region "$REGION" --profile "$PROFILE" ssm get-parameter --name /sdlf/storage/rArtifactsBucket/dev --query "Parameter.Value" --output text)
aws s3 cp "$DIRNAME/scripts/legislators-glue-job.py" "s3://$ARTIFACTS_BUCKET/artifacts/" --profile "$PROFILE"

mkdir "$DIRNAME"/output

function send_legislators() 
{
  ORIGIN="$DIRNAME/data/"
  
  RAW_BUCKET=$(aws --region "$REGION" --profile "$PROFILE" ssm get-parameter --name /sdlf/storage/rRawBucket/dev --query "Parameter.Value" --output text)
  STAGE_BUCKET=$(aws --region "$REGION" --profile "$PROFILE" ssm get-parameter --name /sdlf/storage/rStageBucket/dev --query "Parameter.Value" --output text)
  KMS_KEY=$(aws --region "$REGION" --profile "$PROFILE" ssm get-parameter --name /sdlf/dataset/rKMSDataKey/dev --query "Parameter.Value" --output text)

  S3_DESTINATION=s3://$RAW_BUCKET/
  COUNT=0
  for FILE in "$ORIGIN"/*.json;
  do
    (( COUNT++ )) || true
    if [ "$RAW_BUCKET" == "$STAGE_BUCKET" ];then
      aws s3 cp "$FILE" "${S3_DESTINATION}raw/legislators/" --profile "$PROFILE" --sse aws:kms --sse-kms-key-id "$KMS_KEY"
    else
      aws s3 cp "$FILE" "${S3_DESTINATION}/legislators/" --profile "$PROFILE" --sse aws:kms --sse-kms-key-id "$KMS_KEY"
    fi
    echo "transferred $COUNT files"
  done
}

aws cloudformation package --template-file "$DIRNAME"/scripts/legislators-glue-job.yaml \
  --s3-bucket "$ARTIFACTS_BUCKET" \
  --profile "$PROFILE" \
  --output-template-file "$DIRNAME"/output/packaged-template.yaml

STACK_NAME="sdlf-legislators-glue-job"
if ! aws cloudformation describe-stacks --profile "$PROFILE" --stack-name "$STACK_NAME"; then
  echo -e "Stack does not exist, creating ..."
  aws cloudformation create-stack \
  --profile "$PROFILE" \
  --stack-name "$STACK_NAME" \
  --template-body file://"$DIRNAME"/output/packaged-template.yaml \
  --capabilities "CAPABILITY_NAMED_IAM" "CAPABILITY_AUTO_EXPAND"

  echo "Waiting for stack to be created ..."
  aws cloudformation wait stack-create-complete --profile "$PROFILE" \
    --stack-name "$STACK_NAME"
  send_legislators
else
  echo -e "Stack exists, attempting update ..."

  set +e
  update_output=$(aws cloudformation update-stack \
    --profile "$PROFILE" \
    --stack-name "$STACK_NAME" \
    --template-body file://"$DIRNAME"/output/packaged-template.yaml \
    --capabilities "CAPABILITY_NAMED_IAM" "CAPABILITY_AUTO_EXPAND" 2>&1)
  status=$?
  set -e

  echo "$update_output"

  if [ "$status" -ne 0 ] ; then
    # Don't fail for no-op update
    if [[ $update_output == *"ValidationError"* && $update_output == *"No updates"* ]] ; then
      echo -e "\nFinished create/update - no updates to be performed";
      send_legislators;
      exit 0;
    else
      exit "$status"
    fi
  fi

  echo "Waiting for stack update to complete ..."
  aws cloudformation wait stack-update-complete --profile "$PROFILE" \
    --stack-name "$STACK_NAME"
  echo "Finished create/update successfully!"
fi
