import sys
from awsglue.transforms import *
from awsglue.utils import getResolvedOptions
from pyspark.context import SparkContext
from awsglue.context import GlueContext
from awsglue.dynamicframe import DynamicFrame
from awsglue.job import Job
from pyspark.sql import SparkSession
from pyspark.sql.functions import udf
from pyspark.sql.types import StringType

args = getResolvedOptions(
    sys.argv, ['JOB_NAME', 'SOURCE_LOCATION', 'OUTPUT_LOCATION'])
source = args['SOURCE_LOCATION']
destination = args['OUTPUT_LOCATION']
table = source.split("/")[-1]

glueContext = GlueContext(SparkContext.getOrCreate())
job = Job(glueContext)
job.init(args['JOB_NAME'], args)

if(table == "persons"):
    persons = glueContext.create_dynamic_frame.from_options(
        connection_type="s3",
        format="json",
        connection_options={
            "paths": ['{}/{}'.format(source, 'persons_parsed.json')]
        },
        format_options={
            "withHeader": False
        },
        transformation_ctx="path={}".format('persons_df')
    )
    persons.toDF().write.mode("overwrite").parquet(
    '{}/persons/'.format(destination))

if(table == "memberships"):
    memberships = glueContext.create_dynamic_frame.from_options(
        connection_type="s3",
        format="json",
        connection_options={
            "paths": ['{}/{}'.format(source, 'memberships_parsed.json')]
        },
        format_options={
            "withHeader": False
        },
        transformation_ctx="path={}".format('memberships_df')
    )
    memberships.toDF().write.mode("overwrite").parquet(
    '{}//memberships/'.format(destination))

if(table == "organizations"):
    organizations = glueContext.create_dynamic_frame.from_options(
        connection_type="s3",
        format="json",
        connection_options={
            "paths": ['{}/{}'.format(source, 'organizations_parsed.json')]
        },
        format_options={
            "withHeader": False
        },
        transformation_ctx="path={}".format('organizations_df')
    ).rename_field('id', 'org_id').rename_field('name', 'org_name')
    
    organizations.toDF().write.mode("overwrite").parquet(
    '{}/organizations/'.format(destination))

