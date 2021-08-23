import json, boto3, sys


profile = sys.argv[1]
env = sys.argv[2]
team = sys.argv[3]

print(f"profile:{profile}")

session = boto3.Session(profile_name=profile)
my_session = boto3.session.Session()
my_region = my_session.region_name
ddb = session.resource('dynamodb', region_name=my_region)

path = './wlm/wlm-team-dataset-tables-priority.json'

with open(path, 'r') as json_file:
    data = json.load(json_file)

for item in data:
    for item1 in data[item]:
        name = f"{team}-{item}-{item1['table_name']}"
        priority = item1['priority']

        table = ddb.Table(f'octagon-wlm-{env}')

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
            print(f"Issue writting to octagon-wlm-{env}")
            raise e

