import logging

logger = logging.getLogger(__name__)


def clean_table(dynamodb, table_name, pk_name, sk_name=""):
    logger.debug(f"Clean dynamodb table {table_name}, PK: {pk_name}, SK: {sk_name}")
    table = dynamodb.Table(table_name)
    while True:
        result = table.scan()
        if result["Count"] == 0:
            logger.debug(f"Clean dynamodb table {table_name}... DONE")
            return

        with table.batch_writer() as batch:
            for item in result["Items"]:
                if not sk_name:
                    batch.delete_item(Key={pk_name: item[pk_name]})
                else:
                    batch.delete_item(Key={pk_name: item[pk_name], sk_name: item[sk_name]})
