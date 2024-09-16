import json
import boto3
import datetime

### Step in the testing framework's step function to update end timestamp and
### move the testing to the next test.

session = boto3.Session(region_name = 'us-west-2')
s3 = session.resource("s3")
ddb = session.client("dynamodb")

CONFIG_TABLE = 'datalake-test-config'

def lambda_handler(event, context):
    
    testid = event.get('test_id')
    print("testid:" + str(testid))
    if None == testid:
        testid = '0'
    else:
        first_item = ddb.scan( TableName=CONFIG_TABLE,
            ScanFilter = {
                'test_id' : {'AttributeValueList':[{'S':testid}],
                'ComparisonOperator':'EQ'}
            }
        )
        
        if None == first_item or 0 >= len(first_item.get('Items')):
            print("No test found")
        else:
            is_active = item.get('active').get('N')
            ## Update endedAt only if test was active
            if( "1" == str(is_active)):
                item = first_item.get('Items')[0]
                item['endedAt'] = {'S':str(datetime.datetime.now())}
                ddb.put_item(TableName=CONFIG_TABLE, Item=item)

    ## Increment to next test.
    testid = str(int(testid) + 1)
    rt = {"test_id": testid}
    
    return rt
