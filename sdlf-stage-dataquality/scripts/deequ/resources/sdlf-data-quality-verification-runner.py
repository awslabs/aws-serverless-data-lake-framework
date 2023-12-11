import sys
import awswrangler as wr
import time
import json
import logging
import boto3
from boto3.dynamodb.conditions import Key, Attr
from awsglue.utils import getResolvedOptions
from datetime import datetime

logger = logging.getLogger()
logger.setLevel(logging.INFO)
dynamodb = boto3.resource('dynamodb')

# Required Parameters
args = getResolvedOptions(sys.argv, [
    'team',
    'dataset',
    'glueDatabase',
    'glueTables',
    'dynamodbSuggestionTableName',
    'targetBucketName',
    'pDataLakeAdminRoleArn'])

team = args['team']
dataset = args['dataset']
glue_database = args['glueDatabase']
dynamodb_table = args['dynamodbSuggestionTableName']
targetBucketName = args['targetBucketName']
DataLakeAdminRoleArn = args['pDataLakeAdminRoleArn']
glue_tables = [x.strip() for x in args['glueTables'].split(',')]
#iam_role_arn = "arn:aws:iam::885909252572:role/sdlf-lakeformation-admin"

glue = boto3.client('glue')
#get current year & current month
currentDay = datetime.now().day
currentMonth = datetime.now().month
currentYear = datetime.now().year
currentHour = datetime.now().hour
currentMin = datetime.now().minute

def getRulesfromDyamodbTable(catalog_table,dynamodb_table,table):
    df_s3write = wr.dynamodb.read_items(
    table_name=dynamodb_table,
    filter_expression=(Attr('table_hash_key').eq(catalog_table))
        )
    df_s3write["database"]=glue_database
    df_s3write["table"]=table
    
    #Writing Recommendation output to S3
    wr.s3.to_parquet(df=df_s3write,path=f"{targetBucketName}/ruleset-suggestion/",dataset=True,partition_cols=['database', 'table'],mode="overwrite_partitions")
    
    df = df_s3write[df_s3write['enable'] == 'Y']
    rules = df['constraint_code'].tolist()
    rs_name=df['ruleset_name'].unique()
    
    return rs_name,rules

for table in glue_tables:
    try:
        rule_details = getRulesfromDyamodbTable(f"{team}-{dataset}-{table}",dynamodb_table,table)
        ddql_rules=f"Rules ={rule_details[1]}".replace("'","")
        wr.data_quality.update_ruleset(name=rule_details[0][0], dqdl_rules=ddql_rules)
        logger.info(f'Evaluating data_quality ruleset')
        df_ruleset_results = wr.data_quality.evaluate_ruleset(
             name=rule_details[0][0],
             iam_role_arn=DataLakeAdminRoleArn,
        )
        
        df_ruleset_results["team"]=team
        df_ruleset_results["database"]=glue_database
        df_ruleset_results["table"]=table
        df_ruleset_results["year"]=currentYear
        df_ruleset_results["month"]=currentMonth
        df_ruleset_results["day"]=currentDay
        df_ruleset_results["hour"]=currentHour
        df_ruleset_results["min"]=currentMin
    
        wr.s3.to_parquet(df=df_ruleset_results,path=f"{targetBucketName}/ruleset-evaluation-results/",dataset=True,partition_cols=['database', 'table','year','month','day'])
        
    except Exception as e:
        logger.error(f'Data Quality evaluationruleset Failed for table: {table}' , exc_info=True)
        raise e
    
