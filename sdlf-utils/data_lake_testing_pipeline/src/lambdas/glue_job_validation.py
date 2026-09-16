import json

def validate_job(event, context):
    # TODO implement
    response = {}
    print("Glue job validated.")
    return {
        'statusCode': 200,
        'body': json.dumps('Hello from Lambda!'),
        'status' : "SUCCEEDED"
    }

