# Tutorial: Loading ongoing data lake changes with AWS DMS and AWS Glue

This tutorial is heavily based on this [AWS blog](https://aws.amazon.com/blogs/big-data/loading-ongoing-data-lake-changes-with-aws-dms-and-aws-glue/) and focuses on how to integrate CDC ingestion capabilites into SDLF. We highly recommend that you read the blog to better understand the concepts behind this ingestion pattern if you are not already familiar with them.

## Prerequisites
1. Access to an RDS database (e.g. mysql, postgres...) as a super user
2. Credentials to the RDS database are available 

## Deployment
1. We first store the secrets to the RDS server so that they are not exposed in the CFN templates. Navigate to Secrets Manager and create a /SDLF/RDS/team-name/rds-db-name entry listing the “server”, “username” and “password” to the RDS database. You need to respect this naming convention when creating secrets for all RDS DBs (/SDLF/RDS/pTeamName/pDBName). Please note that the pDBName is the name of the database not the server name.

2. Navigate into the dms-replication directory and modify the parameters-$ENV.json with the relevant details then run:
    ```bash
    cd ./ingestion-examples/cdc/dms-replication/
    ./deploy.sh
    ```
A CloudFormation stack will create a DMS replication instance which manages data replication from the RDS databases into the RAW S3 bucket

3. Navigate into the dms-task directory and modify the parameters-$ENV.json with the relevant RDS database details then run:
    ```bash
    cd ./ingestion-examples/cdc/dms-task/
    ./deploy.sh
    ```
A CloudFormation stack will create a DMS task and the Glue jobs that manage deduplication from RAW to STAGE S3 buckets

4. In the DMSCDC_Controller DynamoDB, set the ActiveFlag to true and Primary Keys for each table (follow the example in the blog for more details). Replication will start the next time the CDC_Controller job is triggered and deduplicated data will land in the STAGE S3 bucket.  