#!/bin/bash

# build a CloudFormation module
# SAM templates cannot be registered as CloudFormation modules directly
# hence the transformation steps in this script

set -Eeuo pipefail

sflag=false
tflag=false
nflag=false
pflag=false

DIRNAME=$(dirname "$0")

usage () { echo "
    -h -- Opens up this help message
    -t -- Path to CloudFormation template file
    -n -- Name of the CloudFormation module
    -p -- Name of the AWS profile to use
    -s -- Name of S3 bucket to upload artifacts to
"; }
options=':t:n:p:s:h'
while getopts "$options" option
do
    case "$option" in
        t  ) tflag=true; TEMPLATE_PATH=$OPTARG;;
        n  ) nflag=true; MODULE_NAME=$OPTARG;;
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
if ! "$sflag"
then
    S3_BUCKET=$(sed -e 's/^"//' -e 's/"$//' <<<"$(aws ssm get-parameter --name /SDLF/S3/CFNBucket --profile "$PROFILE" --query "Parameter.Value")")
fi

# SAM Transform
sam package --template-file "$TEMPLATE_PATH" --s3-bucket "$S3_BUCKET" --s3-prefix sdlf --output-template-file packaged-template.yaml
python3 sam-translate.py --template-file=packaged-template.yaml --output-template=translated-template.json

# CFN Module Creation
mkdir module
pushd module
cfn init --artifact-type MODULE --type-name "awslabs::sdlf::$MODULE_NAME::MODULE" && rm fragments/sample.json
cp -i -a ../translated-template.json fragments/
cfn validate
TYPE_VERSION_ARN=$(cfn submit | tee logs | grep "ProgressStatus" | tr "'" '"' | jq -r '.TypeVersionArn')
cat logs && rm logs
echo "registering new version as default"
aws cloudformation set-type-default-version --type MODULE --arn "$TYPE_VERSION_ARN"
echo "done"
popd
rm -Rf module
