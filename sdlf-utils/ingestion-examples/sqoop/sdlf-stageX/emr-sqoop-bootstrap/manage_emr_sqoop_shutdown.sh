#!/bin/bash -x
#
# Copyright 2016 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License").
# You may not use this file except in compliance with the License.
# A copy of the License is located at
#
# http://aws.amazon.com/apache2.0
#
# or in the "license" file accompanying this file. This file is distributed
# on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either
# express or implied. See the License for the specific language governing
# permissions and limitations under the License.
#

CLUSTER_ID=$(cat /mnt/var/lib/info/job-flow.json | jq -r ".jobFlowId")

SLEEP_TIME_BEGINING='20m'
TIME_LIMIT_MINS=20
TIME_INTERVAL_MINS=2

sleep $SLEEP_TIME_BEGINING

TIME_COUNTER_MINS=0
TIME_INTERVAL_MINS_STRING=$TIME_INTERVAL_MINS'm'
OIFS=$IFS

while  [ $TIME_COUNTER_MINS -le $TIME_LIMIT_MINS ]
do
  JOBS_NUM=$(yarn application -list |grep "Total number of " |  awk -F "):" '{print $2}')
  # if the process in livy are 0 , means that livy server has been inactive for a while.
  if [[ "$JOBS_NUM" == 0 ]]; then
     TIME_COUNTER_MINS=$((TIME_COUNTER_MINS+TIME_INTERVAL_MINS))
  # if the livy server had some activity in the last loop cycle, restart the time counter.
  else
     TIME_COUNTER_MINS=0
  fi
  sleep $TIME_INTERVAL_MINS_STRING

done

IFS=$OIFS

MESSAGE="$(date): Terminating cluster ${CLUSTER_ID}"
SUBJECT="EMR Cluster shutdown: ${CLUSTER_ID}"
echo ${MESSAGE}

aws emr terminate-clusters --cluster-ids ${CLUSTER_ID}
exit 0


