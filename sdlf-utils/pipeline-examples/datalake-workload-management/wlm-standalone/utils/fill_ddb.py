import json, boto3, sys


profile = sys.argv[1]
region = sys.argv[2]

print(f"profile:{profile}")
print(f"region:{region}")

session = boto3.Session(profile_name=profile)

ddb = session.resource('dynamodb', region_name=region)

path = './utils/ddb_items/workload_management_ddb.json'

with open(path, 'r') as json_file:
    data = json.load(json_file)

for item in data:
    name = item
    priority = data[item]['priority']

    table = ddb.Table('workload-management-ddb')

    try:
        response = table.put_item(
            Item={
                'name': name,
                'priority': priority
            }
        )
        if response['ResponseMetadata']['HTTPStatusCode'] != 200:
            print(f"error uploading table: {name}")
            print(response)
        else:
            print(f"Added table name: {name}")

    except Exception as e:
        print("Issue writting to workload-management-ddb")
        raise e

