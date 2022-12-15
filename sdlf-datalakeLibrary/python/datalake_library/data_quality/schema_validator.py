from abc import ABC, abstractmethod

import awswrangler as wr  # Ensure Lambda has an AWS Wrangler Layer configured
import boto3

from ..commons import init_logger

logger = init_logger(__name__)


class GlueSchemaValidator(ABC):
    """
    Abstract class to validate objects against Glue Table schemas.
    """

    def __init__(self, boto3_session=None):
        """
        Initializes Glue client based on the supplied or a new session.

        Args:
            boto3_session: Boto3 session
        """
        self.boto3_session = boto3_session
        # Reuse session or create a default one
        self.glue_client = boto3_session.client("glue") if boto3_session else boto3.client("glue")

    def _get_table_parameters(self, database_name, table_name):
        """
        Returns the parameters of the Glue table

        Args:
            database_name: Glue database name
            table_name: Glue table name

        Returns: dict of table parameters
        """
        return self.glue_client.get_table(DatabaseName=database_name, Name=table_name)["Table"]["Parameters"]

    def _get_table_schema(self, database_name, table_name):
        """
        Returns column names and respective types of the Glue table

        Args:
            database_name: Glue database name
            table_name: Glue table name

        Returns: list of dicts of a form { 'Name': ..., 'Type': ...}
        """
        return self.glue_client.get_table(DatabaseName=database_name, Name=table_name)["Table"]["StorageDescriptor"][
            "Columns"
        ]

    @abstractmethod
    def validate(self, prefix, keys, database_name, table_name):
        """
        Validates the object(s) against the Glue schema

        Args:
            prefix: S3 prefix
            keys: list of S3 keys
            database_name: Glue database name
            table_name: Glue table name

        Returns: validation result: True or False
        """
        pass


class ParquetSchemaValidator(GlueSchemaValidator):
    def validate(self, prefix, keys, database_name, table_name):
        """
        Validates the Parquet S3 object(s) against the Glue schema

        Args:
            prefix: S3 prefix
            keys: list of S3 keys
            database_name: Glue database name
            table_name: Glue table name

        Returns: validation result: True or False
        """
        # Retrieve table parameters
        table_parameters = self._get_table_parameters(database_name, table_name)
        logger.info(f"Table parameters: {table_parameters}")

        # Parse table parameters
        validate_schema, validate_latest = self._parse_table_parameters(table_parameters)

        if validate_schema:
            # Retrieve table schema
            # Columns must be sorted in order to compare the schema because Parquet
            # does not respect the order
            table_schema = sorted(self._get_table_schema(database_name, table_name), key=lambda x: x["Name"])
            logger.info(f"Table schema: {table_schema}")

            # Retrieve object schema
            object_schema = self._get_object_schema(prefix, keys, validate_latest)
            logger.info(f"Object prefix: {prefix}, keys: {keys}, schema: {object_schema}")

            if table_schema != object_schema:
                return False

        return True

    def _get_object_schema(self, prefix, keys, get_latest):
        """
        Retrieves object schema from a Parquet file

        Args:
            prefix: S3 prefix
            keys: list of S3 keys
            get_latest: Flag to get only latest object (otherwise - get all available objects)

        Returns:  list of dicts of a form { 'Name': ..., 'Type': ...}
        """
        # Retrieve object metadata
        s3_objects = wr.s3.describe_objects(
            path=keys if keys and len(keys) > 0 else prefix, boto3_session=self.boto3_session
        )

        # Sort by last modified date and filter out empty objects
        object_keys = [
            object_key
            for object_key, object_metadata in sorted(s3_objects.items(), key=lambda k_v: k_v[1]["LastModified"])
            if object_metadata["ContentLength"] > 0
        ]

        # Retrieve Parquet metadata
        column_types, _ = wr.s3.read_parquet_metadata(
            path=object_keys[0] if get_latest else object_keys, boto3_session=self.boto3_session
        )

        # Columns must be sorted in order to compare the schema because Parquet
        # does not respect the order
        return sorted(
            list({"Name": name.lower(), "Type": type} for name, type in column_types.items()), key=lambda x: x["Name"]
        )

    @staticmethod
    def _parse_table_parameters(table_parameters):
        """
        Retrieves specific table parameters and provides defaults

        Args:
            table_parameters: table parameters dict

        Returns: tuple of Booleans validate_schema, validate_latest
        """
        try:
            validate_schema = True if table_parameters and table_parameters["validate_schema"] == "true" else False
        except KeyError:
            validate_schema = False
        try:
            validate_latest = True if table_parameters and table_parameters["validate_latest"] == "true" else False
        except KeyError:
            validate_latest = False

        return validate_schema, validate_latest
