Sample code for testing redshift with the framework.

redshift_core.py - library functions to connect to redshift with psql. Store credentials in a secret named 'aws-ps-redshift'. Expects a database named 'dev' to pre-exist.
redshift_adhoc.py - unit test to test adhoc redshift queries
redshift_counter.py - unit test to test record count
