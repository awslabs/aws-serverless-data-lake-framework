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
while getopts "$options" option
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

if ! "$pflag"
then
    echo "-p not specified, using default..." >&2
    PROFILE="default"
fi
ENV=$(sed -e 's/^"//' -e 's/"$//' <<<"$(aws ssm get-parameter --name /SDLF/Misc/pEnv --profile "$PROFILE" --query "Parameter.Value")")
TEAM_NAME=$(sed -e 's/^"//' -e 's/"$//' <<<"$(jq '.[] | select(.ParameterKey=="pTeamName") | .ParameterValue' "$DIRNAME/parameters-$ENV".json)")
PIPELINE_NAME=$(sed -e 's/^"//' -e 's/"$//' <<<"$(jq '.[] | select(.ParameterKey=="pPipelineName") | .ParameterValue' "$DIRNAME/parameters-$ENV".json)")
STAGES=$(sed -e 's/^"//' -e 's/"$//' <<<"$(jq '.[] | select(.ParameterKey | endswith("StateMachineRepository")) | .ParameterKey | .[6:7]' "$DIRNAME/parameters-$ENV".json)")
ENTRYPOINT=$(sed -e 's/^"//' -e 's/"$//' <<<"$(jq '.[] | select(.ParameterKey=="pEntryPoint") | .ParameterValue' "$DIRNAME/parameters-$ENV".json)")
if ! "$sflag"
then
    S3_BUCKET=$(sed -e 's/^"//' -e 's/"$//' <<<"$(aws ssm get-parameter --name /SDLF/S3/CFNBucket --profile "$PROFILE" --query "Parameter.Value")")
fi
if ! "$nflag"
then
    STACK_NAME="sdlf-$TEAM_NAME-$PIPELINE_NAME"
fi

echo "Checking if bucket exists ..."
if ! aws s3 ls "$S3_BUCKET" --profile "$PROFILE"; then
  echo "S3 bucket named $S3_BUCKET does not exist. Create? [Y/N]"
  read -r choice
  if [ "$choice" == "Y" ] || [ "$choice" == "y" ]; then
    aws s3 mb s3://"$S3_BUCKET" --profile "$PROFILE"
  else
    echo "Bucket does not exist. Deploy aborted."
    exit 1
  fi
fi

aws s3 cp "$DIRNAME/nested-stacks/template-stage-interface.yaml" "s3://$S3_BUCKET/pipeline/" --profile "$PROFILE"
mkdir "$DIRNAME"/output
aws cloudformation package --profile "$PROFILE" --template-file "$DIRNAME"/template.yaml --s3-bucket "$S3_BUCKET" --s3-prefix "$TEAM_NAME/pipeline/$PIPELINE_NAME" --output-template-file "$DIRNAME"/output/packaged-template.yaml

echo "Checking if stack exists ..."
if ! aws cloudformation describe-stacks --profile "$PROFILE" --stack-name "$STACK_NAME"; then
  echo -e "Stack does not exist, creating ..."
  aws cloudformation create-stack \
    --stack-name "$STACK_NAME" \
    --parameters file://"$DIRNAME/parameters-$ENV".json \
    --template-body file://"$DIRNAME"/output/packaged-template.yaml \
    --tags file://"$DIRNAME"/tags.json \
    --capabilities "CAPABILITY_NAMED_IAM" "CAPABILITY_AUTO_EXPAND" \
    --profile "$PROFILE"

  echo "Waiting for stack to be created ..."
  aws cloudformation wait stack-create-complete --profile "$PROFILE" \
    --stack-name "$STACK_NAME"

  echo "Creating octagon-Pipelines-$ENV DynamoDB entry"
  while IFS= read -r s
  do
      PIPELINE_STAGE=$(echo stage-"$s" | awk '{print tolower($0)}')
      if [[ "$PIPELINE_STAGE" == "$ENTRYPOINT" ]]; then
          ENTRYPOINT_STAGE=true
      else
          ENTRYPOINT_STAGE=false
      fi
      PIPELINE_JSON=$( jq -n \
                          --arg pn "$TEAM_NAME-$PIPELINE_NAME-$PIPELINE_STAGE" \
                          --arg ep "$ENTRYPOINT_STAGE" \
                          '{"name": {"S": $pn}, "type": {"S": "TRANSFORMATION"}, "status": {"S": "ACTIVE"}, "entrypoint": {"S": $ep}, "version": {"N": "1"}}' )
      aws dynamodb put-item --profile "$PROFILE" \
        --table-name octagon-Pipelines-"$ENV" \
        --item "$PIPELINE_JSON"
      echo "$TEAM_NAME-$PIPELINE_NAME-$PIPELINE_STAGE DynamoDB Pipeline entry created"
  done <<< "$STAGES"
else
  echo -e "Stack exists, attempting update ..."

  set +e
  update_output=$(aws cloudformation update-stack \
    --profile "$PROFILE" \
    --stack-name "$STACK_NAME" \
    --parameters file://"$DIRNAME/parameters-$ENV".json \
    --template-body file://"$DIRNAME"/output/packaged-template.yaml \
    --tags file://"$DIRNAME"/tags.json \
    --capabilities "CAPABILITY_NAMED_IAM" "CAPABILITY_AUTO_EXPAND" 2>&1)
  status=$?
  set -e

  echo "$update_output"

  if [ "$status" -ne 0 ] ; then
    # Don't fail for no-op update
    if [[ $update_output == *"ValidationError"* && $update_output == *"No updates"* ]] ; then
      echo -e "\nFinished create/update - no updates to be performed";
      exit 0;
    else
      exit "$status";
    fi
  fi

  echo "Waiting for stack update to complete ..."
  aws cloudformation wait stack-update-complete --profile "$PROFILE" \
    --stack-name "$STACK_NAME" 
  echo "Finished create/update successfully!"

  echo "Updating octagon-Pipelines-$ENV DynamoDB entry"
  while IFS= read -r s
  do
      PIPELINE_STAGE=$(echo stage-"$s" | awk '{print tolower($0)}')
      if [[ "$PIPELINE_STAGE" == "$ENTRYPOINT" ]]; then
          ENTRYPOINT_STAGE=true
      else
          ENTRYPOINT_STAGE=false
      fi
      PIPELINE_JSON=$( jq -n \
                          --arg pn "$TEAM_NAME-$PIPELINE_NAME-$PIPELINE_STAGE" \
                          --arg ep "$ENTRYPOINT_STAGE" \
                          '{"name": {"S": $pn}, "type": {"S": "TRANSFORMATION"}, "status": {"S": "ACTIVE"}, "entrypoint": {"S": $ep}, "version": {"N": "1"}}' )
      echo "$PIPELINE_JSON"
      ATTRIBUTES_JSON='{"#N": "name"}'
      set +e
      update_output=$(aws dynamodb put-item --profile "$PROFILE" \
        --table-name octagon-Pipelines-"$ENV" \
        --item "$PIPELINE_JSON" \
        --expression-attribute-names "$ATTRIBUTES_JSON" \
        --condition-expression "attribute_not_exists(#N)" 2>&1)
      status=$?
      set -e
      
      echo "$update_output"
      
      if [ "$status" -ne 0 ] ; then
        # Don't fail for no-op update
        if [[ $update_output == *"ConditionalCheckFailedException"* ]] ; then
          echo -e "\nPipeline entry already exists in DynamoDB table";
        else
          exit "$status";
        fi
      fi
        
      echo "$TEAM_NAME-$PIPELINE_NAME-$PIPELINE_STAGE DynamoDB Pipeline entry created"
  done <<< "$STAGES"
fi
