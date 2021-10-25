#!/usr/bin/env bash
set -e
TIME_INTERVAL_MINS_STRING='5m'
while true
do
  aws secretsmanager list-secrets | grep Name | awk '{print $2}' | sed 's/[",]//g' | while read secret ; do aws secretsmanager get-secret-value --secret-id $secret | jq '.SecretString' |  sed 's/\\"//g' | sed 's/"{//g' | sed 's/}"//g' | awk '{split($0,a,"password:"); printf a[2]}' > /home/hadoop/$secret ; done
  sudo chown hadoop:hadoop -R /home/hadoop/sdlf/sqoop
  sleep $TIME_INTERVAL_MINS_STRING
done

