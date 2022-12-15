import botocore
from python.datalake_library.data_quality.schema_validator import ParquetSchemaValidator


class TestParquetSchemaValidator:

    @staticmethod
    def test_validation_off(mocker):
        mocker.patch('botocore.client.BaseClient._make_api_call', return_value={
            'Table': {
                'Parameters': {
                    'validate_schema': 'false'
                }
            }
        })
        mocker.patch('awswrangler.s3.read_parquet_metadata',
                     return_value=({}, None))

        assert ParquetSchemaValidator().validate('', [], None, None)

    @staticmethod
    def test_validation_failure_missing_columns(mocker):
        mocker.patch('botocore.client.BaseClient._make_api_call', return_value={
            'Table': {
                'Parameters': {
                    'validate_schema': 'true'
                },
                'StorageDescriptor': {
                    'Columns': [
                        {'Name': 'id', 'Type': 'string'}
                    ]
                }
            }
        })
        mocker.patch('awswrangler.s3.describe_objects', return_value={})
        mocker.patch('awswrangler.s3.read_parquet_metadata',
                     return_value=({}, None))

        assert not ParquetSchemaValidator().validate('', [], None, None)

    @staticmethod
    def test_validation_failure_different_types(mocker):
        mocker.patch('botocore.client.BaseClient._make_api_call', return_value={
            'Table': {
                'Parameters': {
                    'validate_schema': 'true'
                },
                'StorageDescriptor': {
                    'Columns': [
                        {'Name': 'id', 'Type': 'int'},
                        {'Name': 'op', 'Type': 'string'},
                        {'Name': 'last_modified_at', 'Type': 'timestamp'}
                    ]
                }
            }
        })
        mocker.patch('awswrangler.s3.describe_objects', return_value={})
        mocker.patch('awswrangler.s3.read_parquet_metadata', return_value=({
            'Op': 'string',
            'last_modified_at': 'timestamp',
            'id': 'string'}, None))

        assert not ParquetSchemaValidator().validate('', [], None, None)

    @staticmethod
    def test_validation_success(mocker):
        mocker.patch('botocore.client.BaseClient._make_api_call', return_value={
            'Table': {
                'Parameters': {
                    'validate_schema': 'true'
                },
                'StorageDescriptor': {
                    'Columns': [
                        {'Name': 'op', 'Type': 'string'},
                        {'Name': 'last_modified_at', 'Type': 'timestamp'},
                        {'Name': 'id', 'Type': 'string'}
                    ]
                }
            }
        })
        mocker.patch('awswrangler.s3.describe_objects', return_value={})
        mocker.patch('awswrangler.s3.read_parquet_metadata', return_value=({
            'Op': 'string',
            'last_modified_at': 'timestamp',
            'id': 'string'}, None))

        assert ParquetSchemaValidator().validate('', [], None, None)

    @staticmethod
    def test_validation_success_unordered(mocker):
        mocker.patch('botocore.client.BaseClient._make_api_call', return_value={
            'Table': {
                'Parameters': {
                    'validate_schema': 'true'
                },
                'StorageDescriptor': {
                    'Columns': [
                        {'Name': 'id', 'Type': 'string'},
                        {'Name': 'op', 'Type': 'string'},
                        {'Name': 'last_modified_at', 'Type': 'timestamp'}
                    ]
                }
            }
        })
        mocker.patch('awswrangler.s3.describe_objects', return_value={})
        mocker.patch('awswrangler.s3.read_parquet_metadata', return_value=({
            'Op': 'string',
            'last_modified_at': 'timestamp',
            'id': 'string'}, None))

        assert ParquetSchemaValidator().validate('', [], None, None)
