import os
import sys
from unittest.mock import patch

import pytest
from pytest import fixture

sys.path.insert(0, os.path.join(os.path.abspath(
    os.path.dirname(__file__)), '../../../..'))
from python.datalake_library.transforms.stage_b_transforms.heavy_transform_blueprint import CustomTransform


class TestCustomTransform:

    @staticmethod
    def test_check_job_status(mocker):
        # Setup
        bucket = "test-bucket"
        keys = 123
        processed_keys_path = "test-bucket/files/"
        job_details = {"jobName": "meteorites-glue-job", "jobRunId": "1"}

        job_response = {
            "JobRun": {
                "jobName": "meteorites-glue-job",
                "jobRunId": 1,
                "JobRunState": "RUNNING"
            }

        }
        expected_result = {
            "processedKeysPath": processed_keys_path,
            "jobDetails": {"jobName": "meteorites-glue-job", "jobRunId": "1", "jobStatus": "RUNNING"}
        }

        mocker.patch("botocore.client.BaseClient._make_api_call",
                     return_value=job_response)

        # Exercise
        result = CustomTransform().check_job_status(
            bucket, keys, processed_keys_path, job_details)

        # Verify
        assert result == expected_result
