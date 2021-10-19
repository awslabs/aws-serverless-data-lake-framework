# Sqoop Import
This repository contains the code to deploy an ingestion pipeline, 
Extracts information from relational data sources using a transient EMR cluster.


## Architecture
The diagram below illustrates the high-level architecture of the resources deployed by this template:

![StageA Architecture](docs/ArchitectureNoBAckground.png)

##Resources
This template creates the following resources:
1. DynamoDB Table
2. Lambda functions / Step function
3. IAM roles
4. CloudWatch Rules

##Prerequisites
This template need the following resources:
1. Private subnet
2. VPC endpoints or Nat Gateway to call emr services

## Resources Deployed
In detail, this template deploys the following resources:
1. DynamoDB Tables
   1. `odlSqoopStepFunctionsSchedules`
2. Lambda functions
   1. `odlLmbCreateCrondSqoopEMR`
   2  `odlSqoopScheduleDynamoTrigger`
   2. `odlCreateSqoopEMRcluster`
   3. `odlExecuteSqoopJobs`
   4. `odlSqoopSubmit`
   5. `rRoleLambdaExecutionErrorStep`
3. Lambda Triggers
   1.  `odlSqoopScheduleDynamoTrigger`
4. IAM Roles
   1. `SqoopEMRclusterRole`
   2. `SqoopEMREC2Role`
   4. `odlLmbCreateEventsRole`
   5. `odlLambdaExecuteSqoopJobRole`
   6. `LambdaEMRsqoopRole`
5. Instance Profiles
   1. `odlEmrInstanceProfile`
6. CloudWatch Alarms
   1. `rLambdaErrorStepCloudWatchAlarm`
   2. `rLambdaRoutingStepCloudWatchAlarm`
7. SNS Topic
   1. `odlSNStopic`


## Deployment
SDLF:
1.- Create an StageX repo and create the dev test and master branches
2.- Upload the content of this folder to the StageX repo


## Ingestion

#### JDBC and scripts insallation
Copy the content of the emr-sqoop-bootstrap on the artifactory bucket


#### Connection:
Create a new Secret in Secrets Manager,
Secret type: Other type
Secret Name: sdlf/sqoop/identifier
Example: sdlf/sqoop/oracle-sampledb
Secret Value:
```
{
  "sqoop_connection_args": "--connect jdbc:oracle:thin:@172.250.1.123:1521:sampledb --username myusername --password mypassword"
}
```

#### Extraction config:
Add a new item to the table odlSqoopStepFunctionsSchedules

| **Parameter**     | **Description**   |
| :-------------: |:-------------|
| job_name             | Name of the job, used to name the EMR step |
| crond_expression     | Defines the extraction frequency, used to create a CloudWatch rule |
| job_status     | ENABLED, enables the CloudWatch rule<br>DISABLED, disables the CloudWatch rule |
| command      | Command to execute, sqoop command or any other  
| secret_params | Adds adititonal informattion to the command  
| | (Dictionary )
|               |      secret: name of the SSM secret 
|               |      key: key to retrive, usually a connection string |
| date_substitutions | Substitute the tokens with the specified time delta     |




Example DynamoDB Item:
```
{
 "job_name": "gir_giro",
 "date_substitutions": [
  {
   "format": "%Y%m%d 23:59",
   "relativedelta_attributes": {
    "days": -1,
    "years": 0
   },
   "token": "$end_date"
  },
  {
   "format": "%Y%m%d",
   "relativedelta_attributes": {
    "days": -1,
    "years": 0,
    "months": 0
   },
   "token": "$partition_date"
  }
 ],
 "secret_params": {
  "key": "sqoop_connection_args",
  "secret": "sdlf/sqoop/oracle-sampledb"
 },
 "command": "sqoop import --query \"select * from aplicacion.GIR_GIRO where date >= to_date('$partition_date 00:00','yyyymmdd hh24:mi') and date < to_date('$end_date','yyyymmdd hh24:mi') and $CONDITIONS\" --target-dir s3n://matrix-datalake-dev-us-east-1-545611566235-raw/engineer/efecty/GIR_GIRO/fecha=$partition_date --as-textfile -m 1 --fields-terminated-by , --optionally-enclosed-by '\"' --escaped-by \\ --delete-target-dir",
 "crond_expression": "cron(16 14 * * ? *)",
 "job_status": "ENABLED"
}
```


