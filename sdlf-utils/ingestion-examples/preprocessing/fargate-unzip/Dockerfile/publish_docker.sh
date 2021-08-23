#!/usr/bin/env bash
set -e
#set -nx
# Execution Instructions
# must be executed in the same directory of Dockerfile and .sh
# Get your Account ID
usage () { echo "
    -h -- Opens up this help message
    -n -- Name of the ECR docker repository
    -p -- Name of the AWS profile to use
    -r -- Name of the AWS Region to use
"; }
options=':n:p:r:h'
while getopts $options option
do
    case "$option" in
        n  ) DOCKER_NAME=$OPTARG;;
        p  ) AWS_PROFILE=$OPTARG;;
        r  ) AWS_REGION=$OPTARG;;
        h  ) usage; exit;;
        \? ) echo "Unknown option: -$OPTARG" >&2; exit 1;;
        :  ) echo "Missing option argument for -$OPTARG" >&2; exit 1;;
        *  ) echo "Unimplemented option: -$OPTARG" >&2; exit 1;;
    esac
done
docker build -t $DOCKER_NAME:latest .
ACCOUNT_ID=$(aws sts get-caller-identity --profile $AWS_PROFILE --output text | awk '{print $1}')
aws ecr get-login-password --region $AWS_REGION --profile $AWS_PROFILE | docker login --username AWS --password-stdin $ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com
docker tag $DOCKER_NAME:latest $ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$DOCKER_NAME:latest
echo "Creating ECR repository..."
if ! aws ecr create-repository --profile $AWS_PROFILE --region $AWS_REGION --repository-name $DOCKER_NAME --image-scanning-configuration scanOnPush=true; then
    echo "ECR repository already exists..."
else
    echo "ECR repository created..."
fi
docker push $ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$DOCKER_NAME:latest
