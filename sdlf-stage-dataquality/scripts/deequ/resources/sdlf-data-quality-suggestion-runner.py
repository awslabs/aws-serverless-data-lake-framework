import sys
import awswrangler as wr
import logging
import boto3
from awsglue.utils import getResolvedOptions

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

unique_key = 0
for table in glue_tables:
    unique_key = unique_key + 1
    ruleset_name = glue_database + '-' + table + '-ruleset-' + str(unique_key)
    try:
        logger.info(f'Creating data_quality recommendation ruleset for table: {table}')
        df_recommended_ruleset = wr.data_quality.create_recommendation_ruleset(
            name=ruleset_name,
            database=glue_database,
            table=table,
            iam_role_arn=DataLakeAdminRoleArn
        )
        
    except Exception as e:
        logger.error(f'Data Quality create_recommendation_ruleset Failed for table: {table}' , exc_info=True)
        raise e
            
    try:
        logger.info(f'Writing data_quality rules to dynamodb table: {dynamodb_table}')
        dqs_table = dynamodb.Table(dynamodb_table)
        table_row_count = dqs_table.item_count
            
        with dqs_table.batch_writer() as batch:
            for index, row in df_recommended_ruleset.iterrows():
                table_row_count = table_row_count+1
                    
                column_name = row['parameter'].replace('"', '') if row['parameter'] is not None else 'None'
                enable_code = 'N' if row['rule_type'] in ('RowCount','ColumnLength','ColumnValues') else 'Y'
                parameter = row['parameter'] if row['parameter'] is not None else ''
                expression = row['expression'] if row['expression'] is not None else ''
                
                suggestion_hash_key = '##'+team+'##'+dataset+'##'+table+'##'+column_name+'##'+str(table_row_count)
                constraint_code = row['rule_type'] + ' ' + parameter + ' ' + expression
                constraint_code = constraint_code.replace('  ', ' ')
                table_hash_key = team+'-'+dataset+'-'+table
    
                batch.put_item(
                    Item={
                        'suggestion_hash_key': suggestion_hash_key,
                        'column': column_name,
                        'ruleset_name': ruleset_name,
                        'constraint_code': constraint_code,
                        'enable': enable_code,
                        'table_hash_key': table_hash_key
                    }
                )
    except Exception as e:
        logger.error(f'Writing data_quality rulese to dynamodb table: {dynamodb_table} failed' , exc_info=True)
        raise e
    
