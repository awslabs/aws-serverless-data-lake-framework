#!/bin/bash
pflag=false
sflag=false
aflag=false
eflag=false
tflag=false
cflag=false

DIRNAME=$(dirname "$0")

usage () { echo "
    -h -- Opens up this help message
    -p -- Name of the AWS profile to use
    -s -- Name of S3 bucket to upload CFN artifacts to
    -a -- Name of S3 bucket to upload SDLF artifacts to
    -e -- Name of the SDLF enviromnment
    -t -- Name of the owner team of the Glue jobs
    -c -- Y or N to create or not a glue connection, if yes, a parameters-conn-<ENV>.json file should exist
"; }
options=':p:s:a:e:t:c:h:'
while getopts $options option
do
    case "$option" in
        p  ) pflag=true; PROFILE=$OPTARG;;
        s  ) sflag=true; S3_BUCKET=$OPTARG;;
        a  ) aflag=true; ARTIFACTS_BUCKET=$OPTARG;;
        e  ) eflag=true; ENV=$OPTARG;;
        t  ) tflag=true; TEAM=$OPTARG;;
        c  ) cflag=true; CONN=$OPTARG;;
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
if ! $sflag
then
    S3_BUCKET=$(sed -e 's/^"//' -e 's/"$//' <<<"$(aws ssm get-parameter --name /SDLF/S3/CFNBucket --profile $PROFILE --query "Parameter.Value")")
fi
if ! $aflag
then
    ARTIFACTS_BUCKET=$(sed -e 's/^"//' -e 's/"$//' <<<"$(aws ssm get-parameter --name /SDLF/S3/ArtifactsBucket --profile $PROFILE --query "Parameter.Value")")
fi
if ! $eflag
then
    ENV=$(sed -e 's/^"//' -e 's/"$//' <<<"$(aws ssm get-parameter --name /SDLF/Misc/pEnv --profile $PROFILE --query "Parameter.Value")")
fi
if ! $tflag
then
    echo "-t not specified, using default..." >&2
    TEAM="engineering"
fi
if ! $cflag
then
    echo "-c not specified, using default..." >&2
    CONN="Y"
fi

mkdir -p $DIRNAME/tmp_output

if [ $CONN = 'Y' ]; then
  STACK_NAME_CONN="sdlf-$TEAM-glue-connection"

  aws cloudformation package --template-file $DIRNAME/glue-conn.yaml \
    --s3-bucket $S3_BUCKET \
    --profile $PROFILE \
    --output-template-file $DIRNAME/tmp_output/packaged-glue-connection-$ENV.yaml

  if ! aws cloudformation describe-stacks --profile $PROFILE --stack-name $STACK_NAME_CONN; then
    echo -e "Stack does not exist, creating ..."
    aws cloudformation create-stack \
    --profile $PROFILE \
    --stack-name $STACK_NAME_CONN \
    --parameters file://$DIRNAME/tmp_output/parameters-conn-$ENV.json \
    --template-body file://$DIRNAME/tmp_output/packaged-glue-connection-$ENV.yaml \
    --capabilities "CAPABILITY_NAMED_IAM" "CAPABILITY_AUTO_EXPAND"

    echo "Waiting for stack to be created ..."
    aws cloudformation wait stack-create-complete --profile $PROFILE \
      --stack-name $STACK_NAME_CONN
  else
    echo -e "Stack exists, attempting update ..."

    set +e
    update_output=$(aws cloudformation update-stack \
    --profile $PROFILE \
    --stack-name $STACK_NAME_CONN \
    --parameters file://$DIRNAME/tmp_output/parameters-conn-$ENV.json \
    --template-body file://$DIRNAME/tmp_output/packaged-glue-connection-$ENV.yaml \
    --capabilities "CAPABILITY_NAMED_IAM" "CAPABILITY_AUTO_EXPAND" 2>&1)
    status=$?
    set -e

    echo "$update_output"

    if [ $status -ne 0 ] ; then
      # Don't fail for no-op update
      if [[ $update_output == *"ValidationError"* && $update_output == *"No updates"* ]] ; then
        echo -e "\nFinished create/update - no updates to be performed";
      fi
    else
      echo "Waiting for stack update to complete ..."
      aws cloudformation wait stack-update-complete --profile $PROFILE \
       --stack-name $STACK_NAME_CONN
      echo "Finished create/update successfully!"
    fi

  fi
  echo "Finished create/update successfully!"
fi
set +e

for file in $(find job_files -type f -name '*.json'); do
  filepath="${file%/*}"
  PIPELINE=$( echo $filepath | cut -d/ -f2 )
  filebase=$(basename -- "$file")
  DATASET="${filebase%%.*}"
  echo "Deploying glue job for the pipeline: " $PIPELINE
  echo "and the dataset: " $DATASET

  STACK_NAME=sdlf-$TEAM-$PIPELINE-$DATASET-glue-job

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

  aws s3 cp "$DIRNAME/pipeline_scripts/$PIPELINE-glue-job.py" "s3://$ARTIFACTS_BUCKET/artifacts/glue_jobs/pipeline_scripts/$PIPELINE/" --profile $PROFILE
  aws s3 cp "$DIRNAME/job_files/$PIPELINE/$DATASET.json" "s3://$ARTIFACTS_BUCKET/artifacts/glue_jobs/job_files/$PIPELINE/" --profile $PROFILE
  aws s3 cp "$DIRNAME/job_files/$PIPELINE/$DATASET.sql" "s3://$ARTIFACTS_BUCKET/artifacts/glue_jobs/job_files/$PIPELINE/" --profile $PROFILE
  aws s3 cp "$DIRNAME/job_files/conf_$ENV.json" "s3://$ARTIFACTS_BUCKET/artifacts/glue_jobs/job_files/" --profile $PROFILE

  aws cloudformation package --template-file $DIRNAME/glue-job.yaml \
    --s3-bucket $S3_BUCKET \
    --profile $PROFILE \
    --output-template-file $DIRNAME/tmp_output/packaged-$PIPELINE-$DATASET-$ENV.yaml

  params=""
  echo -e "Creating cloud formation stack parameters file..."
  params="[{\"ParameterKey\":\"pPipeline\",\"ParameterValue\":\"$PIPELINE\"},{\"ParameterKey\":\"pTeam\",\"ParameterValue\":\"$TEAM\"},{\"ParameterKey\":\"pDataset\",\"ParameterValue\":\"$DATASET\"},{\"ParameterKey\":\"pJobFiles\",\"ParameterValue\":\""
  s3path="s3://$ARTIFACTS_BUCKET/artifacts/glue_jobs/job_files/$PIPELINE/"
  s3pathConf="s3://$ARTIFACTS_BUCKET/artifacts/glue_jobs/job_files/"
  if [ $PIPELINE == 'examplepipeline' ]; then
    params="${params}${s3path}${DATASET}.json,${s3path}${DATASET}.sql"
  elif [ $PIPELINE == 'analyticspipeline' ]; then
    params="${params}${s3path}${DATASET}.json,${s3path}${DATASET}.sql"
  elif [ $PIPELINE == 'jdbc2stage' ]; then
    params="${params}${s3path}${DATASET}.json,${s3pathConf}conf_$ENV.json"
  else
    params="${params}${s3path}${DATASET}.json"
  fi

  capacityparam="$( cat $DIRNAME/job_files/$PIPELINE/$DATASET.json | jq '.AllocatedCapacity' )"
  capacity=${capacityparam:-2}
  prefij="\"},{\"ParameterKey\":\"pAllocatedCapacity\",\"ParameterValue\":\""
  params="${params}${prefij}${capacity}"


  params="${params}\"}]"
  echo $params > tmp_output/parameters-$PIPELINE-$DATASET-$ENV.json


  if ! aws cloudformation describe-stacks --profile $PROFILE --stack-name $STACK_NAME; then
    echo -e "Stack does not exist, creating ..."
    aws cloudformation create-stack \
    --profile $PROFILE \
    --stack-name $STACK_NAME \
    --parameters file://$DIRNAME/tmp_output/parameters-$PIPELINE-$DATASET-$ENV.json \
    --template-body file://$DIRNAME/tmp_output/packaged-$PIPELINE-$DATASET-$ENV.yaml \
    --capabilities "CAPABILITY_NAMED_IAM" "CAPABILITY_AUTO_EXPAND"

    echo "Waiting for stack to be created ..."
    aws cloudformation wait stack-create-complete --profile $PROFILE \
      --stack-name $STACK_NAME
  else
    echo -e "Stack exists, recreating ..."
    aws cloudformation delete-stack --profile $PROFILE --stack-name $STACK_NAME
    echo "Waiting for stack to be deleted ..."
    aws cloudformation wait stack-delete-complete --profile $PROFILE --stack-name $STACK_NAME
    aws cloudformation create-stack \
    --profile $PROFILE \
    --stack-name $STACK_NAME \
    --parameters file://$DIRNAME/tmp_output/parameters-$PIPELINE-$DATASET-$ENV.json \
    --template-body file://$DIRNAME/tmp_output/packaged-$PIPELINE-$DATASET-$ENV.yaml \
    --capabilities "CAPABILITY_NAMED_IAM" "CAPABILITY_AUTO_EXPAND"

    echo "Waiting for stack to be created ..."
    aws cloudformation wait stack-create-complete --profile $PROFILE \
      --stack-name $STACK_NAME
  fi
  echo "Finished create/update successfully!!"

done