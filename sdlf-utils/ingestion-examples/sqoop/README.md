# Sqoop Import
This repository contains the code needed to deploy an EMR-sqoop based ingestion solution for relational databases. 
It integrates to the team pipelines as a new stage (**StageX**).

## Architecture
The diagram below illustrates the high-level architecture of the resources deployed by this template:

![StageX Architecture](docs/Architecture.png)


## Dependencies 
1. A private subnet is required to deploy the EMR cluster
2. All the connectivity for the EMR cluster needs to be ready (routes to the source DB, rules, VPN etc.)
3. Create the following VPC endpoints or ensure the subnet has access to:
* com.amazonaws.[region].secretsmanager
* com.amazonaws.[region].elasticmapreduce


## Installation
This solution is an extension of the SDLF, you need to have an SDLF implementation.
Where a new Stage called stageX will be created
1. Create a new repository named `sdlf-stageX` and add the master/test/dev branches to it
2. Copy the content of the `sdlf-stageX` folder into those branches
3. Upload the content of the `sdlf-team`, `sdlf-datalakeLibrary` and `sdlf-datalakeLibrary` folders  into their respective repos. Alternatively you can copy them directly to the team repos if you don't want to include this changes to every new team
4. Create a new team (engineering is used for this example)
5. Modify the pipeline parameters to include the new Stage and specify the subnet parameter `pEMRsubnet` with the subnet id where EMR will be started
EMR needs to be created in a private subnet


## Best practices
1. Use an S3 endpoint to avoid network traffic over internet.
2. If connection by SSM is needed include ssm, ec2messages and ssmmessages connection/endpoints
3. Sqoop usually benefits from multiple small containers. 
* m4 instances give the best cost/#taks out of the box
* E.g: m4 instances can run more mappers or extractions than m5.
* Choose your instances based on the map/memory ratio or modify your mappers/reducers settings. Check the [default settings](https://docs.aws.amazon.com/emr/latest/ReleaseGuide/emr-hadoop-task-config.html)  for each instance

## Modifications made
Some SDLF repos need to be modified to support the extraction stage. 
They don't affect the current implementation (unless specified) 

Modifications:
1. **sdlf-datalakeLibrary**: 
* Step functions interface to allow naming for easy identification and debugging.
2. **sdlf-team**: 
* permissions to create the EMR/instances roles and its actions.
* create stageX team repository when a new team is created
3. **sdlf-pipeline**
* Includes new subnet parameter and includes the new stage 
**NOTE: If you have other stages in the pipeline they must have the same parameters as the StageX**


## Configuration 

#### JDBC and scripts installation

* To include a new jar add it to the `sdlf-stageX/emr-sqoop-bootstrap/jdbc_jars` folder
* As per [AWS premium suport](https://aws.amazon.com/premiumsupport/knowledge-center/unknown-dataset-uri-pattern-sqoop-emr/) some sqoop versions may need kite-data-s3-1.1.0.jar. Download it and place it in the `sdlf-stageX/emr-sqoop-bootstrap/jdbc_jars` folder
* Copy the content of the `sdlf-stageX/emr-sqoop-bootstrap` to the artifactory bucket 

#### Cluster and node configuration
Modify the parameters on the `sdlf-stageX/template.yam` to adjust the number and type of nodes and EMR release version

#### Connection setup:
1. Create a new Secret in **Secrets Manager**,
* **Secret type**: Other type
* **Secret Name**: sdlf/sqoop/identifier
* * Example: sdlf/sqoop/oracle-sampledb
* **Secret Value**: 
```
{
  "sqoop_connection_args": "--connect jdbc:oracle:thin:@172.250.1.2:1521:sampledb --username myusername",
  "password":"mypassword"
}
```


**Tip - Connection strings structure**

* Oracle: `jdbc:oracle:thin:@172.250.1.2:1521:sampledb`
* SQLServer: `jdbc:sqlserver://172.250.1.2:1433;databaseName=sampledb`
* Postgres: `jdbc:postgresql://172.250.1.2:5432/sampledb`
* MySQL: `jdbc:mysql://172.250.1.2:3306/sampledb`
* Sybase: `jdbc:sybase:Tds:172.250.1.2:5000?ServiceName=`


**Note**: DB name can be skipped if multiple DBs run in the same host, but it will need to be specified in the sqoop command



#### Extraction config:
Add a new item to the table odlSqoopStepFunctionsSchedules

| **Parameter**     | **Description**   |
| :-------------: |:-------------|
| job_name             | Name of the job, used to name the EMR step |
| crond_expression     | Defines the extraction frequency, used to create a CloudWatch rule |
| job_status     | ENABLED, enables the CloudWatch rule<br>DISABLED, disables the CloudWatch rule |
| command      | Sqoop command to execute  
| secret_params | Adds the connection information to the command  
| | (Dictionary )
|               |      **secret**: name of the SSM secret 
|               |      **key**: key to retrieve, usually a connection string |
| date_substitutions | Substitute the tokens with the specified time delta     |
|               |**token**: String to substitute in the **command**  |
|               |**format**: Expected output date format |
|               |**relativedelta_attributes**: Calculates de extraction date (today - relativedelta)  [relativedelta documentation](https://dateutil.readthedocs.io/en/stable/relativedelta.html)  |





### Example DynamoDB Item:
Example item to extract yesterday data from my_table and store the delta in a partitioned table in S3
```
{
 "job_name": "my_table",
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
 "command": "sqoop import --query \"select * from samplebd.my_table where date >= to_date('$partition_date 00:00','yyyymmdd hh24:mi') and date < to_date('$end_date','yyyymmdd hh24:mi') and $CONDITIONS\" --target-dir s3n://my-datalake-dev-us-east-1-1234567890-raw/engineering/sampledb/my_table/date=$partition_date --as-textfile -m 1 --fields-terminated-by , --escaped-by \\ --delete-target-dir",
 "crond_expression": "cron(16 14 * * ? *)",
 "job_status": "ENABLED"
}
```


