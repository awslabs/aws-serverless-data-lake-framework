#!/bin/bash
sflag=false
pflag=false

DIRNAME=$(dirname "$0")

usage () { echo "
    -h -- Opens up this help message
    -p -- Name of the AWS profile to use
    -s -- Name of S3 bucket to upload artifacts to
"; }
options=':p:s:h'
while getopts $options option
do
    case "$option" in
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
if ! $sflag
then
    S3_BUCKET=$(sed -e 's/^"//' -e 's/"$//' <<<"$(aws ssm get-parameter --name /SDLF/S3/CFNBucket --profile $PROFILE --query "Parameter.Value")")
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

function send_data()
{

  CENTRAL_BUCKET=$(sed -e 's/^"//' -e 's/"$//' <<<"$(aws ssm get-parameter --name /SDLF/S3/CentralBucket --profile $PROFILE --query "Parameter.Value")")
  STAGE_BUCKET=$(sed -e 's/^"//' -e 's/"$//' <<<"$(aws ssm get-parameter --name /SDLF/S3/StageBucket --profile $PROFILE --query "Parameter.Value")")
  KMS_KEY=$(sed -e 's/^"//' -e 's/"$//' <<<"$(aws ssm get-parameter --name /SDLF/KMS/engineering/DataKeyId --profile $PROFILE --query "Parameter.Value")")

  ORIGIN=$DIRNAME/data/
  S3_DESTINATION=s3://$CENTRAL_BUCKET/
  S3_DESTINATION_FRAGMENT='engineering/clf/'


  COUNT=0
  for FILE in $(ls $ORIGIN | awk '{print $1}');
  do
    let COUNT=COUNT+1
    if [ "$CENTRAL_BUCKET" == "$STAGE_BUCKET" ];then
      aws s3 cp $ORIGIN$FILE "${S3_DESTINATION}raw/${S3_DESTINATION_FRAGMENT}" --profile $PROFILE --sse aws:kms --sse-kms-key-id $KMS_KEY
    else
      aws s3 cp $ORIGIN$FILE "${S3_DESTINATION}${S3_DESTINATION_FRAGMENT}" --profile $PROFILE --sse aws:kms --sse-kms-key-id $KMS_KEY
    fi
    echo "transferred $COUNT files"
  done
}

send_data;
