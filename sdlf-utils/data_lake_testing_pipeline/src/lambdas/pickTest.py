import json
import boto3
import datetime

### Test picker to pick an active test, identify the ARN/test params and hand
### it to step function for execution.

session = boto3.Session(region_name = 'us-west-2')
s3 = session.resource("s3")
ddb = session.client("dynamodb")

CONFIG_TABLE = 'datalake-test-config'
        
def lambda_handler(event, context):
    
    testid = event.get('test_id')
    print("testid:" + str(testid))
    if None == testid:
        testid = '0'
    
    first_item = ddb.scan( TableName=CONFIG_TABLE,
            ScanFilter = {
                'test_id' : {'AttributeValueList':[{'S':testid}],
                'ComparisonOperator':'EQ'}
            }
        )
    
    ### If no test is found, the testing ends there.
    if None == first_item or 0 >= len(first_item.get('Items')):
        return { 'job': 'null', 'test_id': testid}
    
    item = first_item.get('Items')[0]
    is_active = item.get('active').get('N')
    
    if( "1" == str(is_active)):
        item['startedAt'] = {'S':str(datetime.datetime.now())}
        ddb.put_item(TableName=CONFIG_TABLE, Item=item)
        rt =  { 'job' : item.get('job').get('S'),
            'TaskExecution': item.get('job_arn').get('S').split("/")[-1],
            'TaskValidation': item.get('validation_lambda_arn').get('S').split(":")[-1],
            'test_id': testid,
            'params': item.get('job_input').get('M')
        }
    else:
        ## If the test is not active, keep moving to the next test.
        rt =  { 'job' : 'skip', 'test_id' : testid }
    
    return rt
