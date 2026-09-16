import pg8000   ## from package pygresql
import boto3
import json

region_name = 'us-west-2'

## Get the credentials for Redshift cluster from secrets manager.
def get_secret(secret_name):
    # Create a Secrets Manager client
    session = boto3.session.Session()
    client = session.client(
        service_name='secretsmanager',
        region_name=region_name
    )

    get_secret_value_response = client.get_secret_value(
        SecretId=secret_name
    )
    return get_secret_value_response
    
    
def connect_redshift(dbname, secret_name):
    secret = get_secret(secret_name)
    credentials = json.loads(secret['SecretString'])
    conn_obj = pg8000.connect(database=dbname,
            host=credentials['host'],
            user=credentials['username'],
            password=credentials['password'],
            port=credentials['port'])
    return conn_obj
