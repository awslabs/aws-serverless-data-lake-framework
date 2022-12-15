#!/bin/bash
sflag=false
nflag=false
pflag=false

DIRNAME=$(dirname "$0")

usage () { echo "
    -h -- Opens up this help message
    -n -- Name of the CloudFormation stack
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
if ! "$sflag"
then
    S3_BUCKET=$(sed -e 's/^"//' -e 's/"$//' <<<"$(aws ssm get-parameter --name /SDLF/S3/CFNBucket --profile "$PROFILE" --query "Parameter.Value")")
fi
if ! "$nflag"
then
    STACK_NAME="sdlf-$TEAM_NAME"
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

# Only when deploying a Demo of SDLF
DEMO=$(sed -e 's/^"//' -e 's/"$//' <<<"$(aws ssm get-parameter --name /SDLF/Misc/Demo --profile "$PROFILE" --query "Parameter.Value")")
if [ "$DEMO" == "true" ];then
  echo "Checking if stack exists ..."
  STACK_CROSS_ACCOUNT_NAME=sdlf-crossaccount-role-${ENV}-${TEAM_NAME}
  ACCOUNT=$(aws sts get-caller-identity --query 'Account' --output text --profile "$PROFILE")
  if ! aws cloudformation describe-stacks --stack-name "$STACK_CROSS_ACCOUNT_NAME" --profile "$PROFILE"; then
    cd "$DIRNAME"/scripts
    echo -e "Stack does not exist, creating ..."
    aws cloudformation create-stack \
      --stack-name "$STACK_CROSS_ACCOUNT_NAME" \
      --parameters \
          ParameterKey=pChildAccountId,ParameterValue="$ACCOUNT" \
          ParameterKey=pEnvironment,ParameterValue="$ENV" \
          ParameterKey=pTeamName,ParameterValue="$TEAM_NAME" \
      --template-body file://"$DIRNAME"/template-team-repos.yaml \
      --tags file://"$DIRNAME"/../tags.json \
      --capabilities "CAPABILITY_NAMED_IAM" "CAPABILITY_AUTO_EXPAND" \
      --profile "$PROFILE"

    echo "Waiting for stack to be created ..."
    aws cloudformation wait stack-create-complete --stack-name "$STACK_CROSS_ACCOUNT_NAME" --profile "$PROFILE"
    cd ../
  fi
fi

mkdir "$DIRNAME"/output
aws cloudformation package --profile "$PROFILE" --template-file "$DIRNAME"/template.yaml --s3-bucket "$S3_BUCKET" --s3-prefix "$TEAM_NAME"/team --output-template-file "$DIRNAME"/output/packaged-template.yaml

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
else
  echo -e "Stack exists, attempting update ..."

  set +e
  update_output=$( aws cloudformation update-stack \
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
      exit "$status"
    fi
  fi

  echo "Waiting for stack update to complete ..."
  aws cloudformation wait stack-update-complete --profile "$PROFILE" \
    --stack-name "$STACK_NAME" 
  echo "Finished create/update successfully!"
fi

CENTRAL_BUCKET=$(sed -e 's/^"//' -e 's/"$//' <<<"$(aws ssm get-parameter --name /SDLF/S3/CentralBucket --profile "$PROFILE" --query "Parameter.Value")")
STAGE_BUCKET=$(sed -e 's/^"//' -e 's/"$//' <<<"$(aws ssm get-parameter --name /SDLF/S3/StageBucket --profile "$PROFILE" --query "Parameter.Value")")
ANALYTICS_BUCKET=$(sed -e 's/^"//' -e 's/"$//' <<<"$(aws ssm get-parameter --name /SDLF/S3/AnalyticsBucket --profile "$PROFILE" --query "Parameter.Value")")
CRAWLER_ARN=$(sed -e 's/^"//' -e 's/"$//' <<<"$(aws ssm get-parameter --name /SDLF/IAM/"$TEAM_NAME"/CrawlerRoleArn --profile "$PROFILE" --query "Parameter.Value")")
echo "Adding Lake Formation permissions ..."
function add_lf_permissions()
{
    CRAWLER_ARN=${1}
    S3_PATH=${2}
    LOCATION_JSON=$( jq -n \
                        --arg pn "$S3_PATH" \
                        '{"DataLocation": {"ResourceArn":$pn}}' )
    aws lakeformation grant-permissions --profile "$PROFILE" \
      --principal  DataLakePrincipalIdentifier="$CRAWLER_ARN" \
      --permissions "DATA_LOCATION_ACCESS" \
      --resource "$LOCATION_JSON"
}
if [ "$CENTRAL_BUCKET" == "$STAGE_BUCKET" ];then
  add_lf_permissions "$CRAWLER_ARN" "arn:aws:s3:::${CENTRAL_BUCKET}/raw/${TEAM_NAME}/"
  add_lf_permissions "$CRAWLER_ARN" "arn:aws:s3:::${CENTRAL_BUCKET}/pre-stage/${TEAM_NAME}/"
  add_lf_permissions "$CRAWLER_ARN" "arn:aws:s3:::${CENTRAL_BUCKET}/post-stage/${TEAM_NAME}/"
  add_lf_permissions "$CRAWLER_ARN" "arn:aws:s3:::${CENTRAL_BUCKET}/analytics/${TEAM_NAME}/"
else
  add_lf_permissions "$CRAWLER_ARN" "arn:aws:s3:::${CENTRAL_BUCKET}/${TEAM_NAME}/"
  add_lf_permissions "$CRAWLER_ARN" "arn:aws:s3:::${STAGE_BUCKET}/pre-stage/${TEAM_NAME}/"
  add_lf_permissions "$CRAWLER_ARN" "arn:aws:s3:::${STAGE_BUCKET}/post-stage/${TEAM_NAME}/"
  add_lf_permissions "$CRAWLER_ARN" "arn:aws:s3:::${ANALYTICS_BUCKET}/${TEAM_NAME}/"
fi
