#!/usr/bin/env bash
set -e
#set -nx
# Execution Instructions
# must be executed in the same directory of Dockerfile and .sh
# Get your Account ID
dockerContainerName="unzip-shell"
awsRegion="us-east-1"
docker build -t $dockerContainerName:latest .
accountId=$(aws sts get-caller-identity --output text | awk '{print $1}')
aws ecr get-login-password --region $awsRegion | docker login --username AWS --password-stdin $accountId.dkr.ecr.us-east-1.amazonaws.com/
docker tag $dockerContainerName:latest $accountId.dkr.ecr.$awsRegion.amazonaws.com/$dockerContainerName:latest
docker push $accountId.dkr.ecr.$awsRegion.amazonaws.com/$dockerContainerName:latest
