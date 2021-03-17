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
ACCOUNT_ID=$(sed -e 's/^"//' -e 's/"$//' <<<"$(aws ssm get-parameter --name /SDLF/Misc/DevOpsAccountId --profile $PROFILE --query "Parameter.Value")")
ENV=$(sed -e 's/^"//' -e 's/"$//' <<<"$(aws ssm get-parameter --name /SDLF/Misc/pEnv --profile $PROFILE --query "Parameter.Value")")

# Devops role for cicd
aws sts assume-role --role-arn "arn:aws:iam::$ACCOUNT_ID:role/sdlf-cicd-team-codecommit-$ENV-engineering" \
  --role-session-name codecommit_access | jq -r .Credentials > tmp_credentials.json

export AWS_ACCESS_KEY_ID="$(jq -r '.AccessKeyId' tmp_credentials.json)"
export AWS_SECRET_ACCESS_KEY="$(jq -r '.SecretAccessKey' tmp_credentials.json)"
export AWS_SESSION_TOKEN="$(jq -r '.SessionToken' tmp_credentials.json)"

PREV_COMMIT=$(aws codecommit get-commit \
  --repository-name sdlf-engineering-dataset \
  --commit-id "${CODEBUILD_RESOLVED_SOURCE_VERSION}" | jq -r '.commit.parents[]' | head -n 1)

aws codecommit get-differences --repository-name sdlf-engineering-dataset \
  --after-commit-specifier "${CODEBUILD_RESOLVED_SOURCE_VERSION}" \
  --before-commit-specifier "${PREV_COMMIT}" > git_all_changed_files.txt

jq -r '.differences[].afterBlob.path' git_all_changed_files.txt | sort | uniq | grep ".json$" > changed_json_files.txt || echo "No .json file changes detected."
# Unset credentials, we are done with these keys.
unset AWS_ACCESS_KEY_ID
unset AWS_SECRET_ACCESS_KEY
unset AWS_SESSION_TOKEN

printf 'Following are changed files after commit:\t%s\n' "$(cat changed_json_files.txt)"

grep 'parameter' < changed_json_files.txt | while IFS= read -r parameter_file
do
  TEAM_NAME=$(sed -e 's/^"//' -e 's/"$//' <<<"$(jq '.[] | select(.ParameterKey=="pTeamName") | .ParameterValue' $parameter_file)")
  PIPELINE_NAME=$(sed -e 's/^"//' -e 's/"$//' <<<"$(jq '.[] | select(.ParameterKey=="pPipelineName") | .ParameterValue' $parameter_file)")
  DATASET_NAME=$(sed -e 's/^"//' -e 's/"$//' <<<"$(jq '.[] | select(.ParameterKey=="pDatasetName") | .ParameterValue' $parameter_file)")
  if ! $sflag
  then
      S3_BUCKET=$(sed -e 's/^"//' -e 's/"$//' <<<"$(aws ssm get-parameter --name /SDLF/S3/CFNBucket --profile $PROFILE --query "Parameter.Value")")
  fi
  if ! $nflag
  then
      if [ $DATASET_NAME == $PIPELINE_NAME ]; then
        echo "Dataset and pipeline cannot hold the same name. Deploy aborted."
        echo $PIPELINE_NAME
        echo $DATASET_NAME
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

  mkdir -p $DIRNAME/output
  aws cloudformation package --profile $PROFILE --template-file $DIRNAME/template.yaml --s3-bucket $S3_BUCKET --s3-prefix $TEAM_NAME/dataset/$DATASET_NAME --output-template-file $DIRNAME/output/packaged-template.yaml

  echo "Checking if stack exists ..."
  if ! aws cloudformation describe-stacks --profile $PROFILE --stack-name $STACK_NAME; then
    echo -e "Stack does not exist, creating ..."
    aws cloudformation create-stack \
      --stack-name $STACK_NAME \
      --parameters file://$parameter_file \
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
      --parameters file://$parameter_file \
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
done