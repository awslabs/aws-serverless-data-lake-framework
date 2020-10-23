#!/bin/bash
sflag=false
nflag=false
pflag=false

DIRNAME=$(dirname "$0")

usage () { echo "
    -h -- Opens up this help message
    -n -- Name of the Dataset name
    -p -- Name of the AWS profile to use
    -s -- Name of S3 bucket to upload artifacts to
"; }
options=':n:p:s:h'
while getopts $options option
do
    case "$option" in
        n  ) nflag=true; STACK_NAME=$OPTARG;;
        p  ) pflag=true; PROFILE=$OPTARG;;
        s  ) sflag=true; S3_BUCKET=$OPTARG;;
        h  ) usage; exit;;
        \? ) echo "Unknown option: -$OPTARG" >&2; exit 1;;
        :  ) echo "Missing option argument for -$OPTARG" >&2; exit 1;;
        *  ) echo "Unimplemented option: -$OPTARG" >&2; exit 1;;
    esac
done

if ! $pflag
then
    echo "-p not specified, using default..." >&2
    PROFILE="default"
fi
ENV=$(sed -e 's/^"//' -e 's/"$//' <<<"$(aws ssm get-parameter --name /SDLF/Misc/pEnv --profile $PROFILE --query "Parameter.Value")")
TEAM_NAME=$(sed -e 's/^"//' -e 's/"$//' <<<"$(jq '.[] | select(.ParameterKey=="pTeamName") | .ParameterValue' $DIRNAME/parameters-$ENV.json)")
PIPELINE_NAME=$(sed -e 's/^"//' -e 's/"$//' <<<"$(jq '.[] | select(.ParameterKey=="pPipelineName") | .ParameterValue' $DIRNAME/parameters-$ENV.json)")
DATASET_NAME=$(sed -e 's/^"//' -e 's/"$//' <<<"$(jq '.[] | select(.ParameterKey=="pDatasetName") | .ParameterValue' $DIRNAME/parameters-$ENV.json)")
if ! $sflag
then
    S3_BUCKET=$(sed -e 's/^"//' -e 's/"$//' <<<"$(aws ssm get-parameter --name /SDLF/S3/CFNBucket --profile $PROFILE --query "Parameter.Value")")
fi
if ! $nflag
then
    if [ $DATASET_NAME == $PIPELINE_NAME ]; then
      echo "Dataset and pipeline cannot hold the same name. Deploy aborted."
      exit 1
    else
      STACK_NAME="sdlf-$TEAM_NAME-$DATASET_NAME"
    fi
fi

echo "Checking if bucket exists ..."
if ! aws s3 ls $S3_BUCKET --profile $PROFILE; then
  echo "S3 bucket named $S3_BUCKET does not exist. Create? [Y/N]"
  read choice
  if [ $choice == "Y" ] || [ $choice == "y" ]; then
    aws s3 mb s3://$S3_BUCKET --profile $PROFILE
  else
    echo "Bucket does not exist. Deploy aborted."
    exit 1
  fi
fi

mkdir $DIRNAME/output
aws cloudformation package --profile $PROFILE --template-file $DIRNAME/template.yaml --s3-bucket $S3_BUCKET --s3-prefix $TEAM_NAME/dataset/$DATASET_NAME --output-template-file $DIRNAME/output/packaged-template.yaml

echo "Checking if stack exists ..."
if ! aws cloudformation describe-stacks --profile $PROFILE --stack-name $STACK_NAME; then
  echo -e "Stack does not exist, creating ..."
  aws cloudformation create-stack \
    --stack-name $STACK_NAME \
    --parameters file://$DIRNAME/parameters-$ENV.json \
    --template-body file://$DIRNAME/output/packaged-template.yaml \
    --tags file://$DIRNAME/tags.json \
    --capabilities "CAPABILITY_NAMED_IAM" "CAPABILITY_AUTO_EXPAND" \
    --profile $PROFILE

  echo "Waiting for stack to be created ..."
  aws cloudformation wait stack-create-complete --profile $PROFILE \
    --stack-name $STACK_NAME

  echo "Creating octagon-Datasets-$ENV DynamoDB entry"
  DATASET_JSON=$( jq -n \
                --arg dn "$TEAM_NAME-$DATASET_NAME" \
                --arg pn "$PIPELINE_NAME" \
                '{"name": {"S": $dn}, "pipeline": {"S": $pn}, "transforms": { "M": {"stage_a_transform": {"S": "light_transform_blueprint"}, "stage_b_transform": {"S": "heavy_transform_blueprint"}}}, "max_items_process": { "M": {"stage_b": {"N": "100"}, "stage_c": {"N": "100"}}}, "min_items_process": { "M": {"stage_b": {"N": "1"}, "stage_c": {"N": "1"}}}, "version": {"N": "1"}}' )
  aws dynamodb put-item --profile $PROFILE \
    --table-name octagon-Datasets-$ENV \
    --item "$DATASET_JSON"
  echo "$TEAM_NAME-$DATASET_NAME DynamoDB Dataset entry created"
else
  echo -e "Stack exists, attempting update ..."

  set +e
  update_output=$(aws cloudformation update-stack \
    --profile $PROFILE \
    --stack-name $STACK_NAME \
    --parameters file://$DIRNAME/parameters-$ENV.json \
    --template-body file://$DIRNAME/output/packaged-template.yaml \
    --tags file://$DIRNAME/tags.json \
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
    --stack-name $STACK_NAME 
  echo "Finished create/update successfully!"

  echo "Updating octagon-Datasets-$ENV DynamoDB entry"
  KEYS_JSON=$( jq -n \
                  --arg dn "$TEAM_NAME-$DATASET_NAME" \
                  '{"name": {"S": $dn}}' )
  ATTRIBUTES_JSON='{"#N": "name", "#P": "pipeline"}'
  VALUES_JSON=$( jq -n \
                    --arg pn "$PIPELINE_NAME" \
                    '{":p": {"S": $pn}}' )
  aws dynamodb update-item --profile $PROFILE \
      --table-name octagon-Datasets-$ENV \
      --key "$KEYS_JSON" \
      --update-expression "SET #P = :p" \
      --expression-attribute-names "$ATTRIBUTES_JSON" \
      --expression-attribute-values "$VALUES_JSON" \
      --condition-expression "attribute_exists(#N)"
  echo "$TEAM_NAME-$DATASET_NAME DynamoDB Dataset entry updated"
fi