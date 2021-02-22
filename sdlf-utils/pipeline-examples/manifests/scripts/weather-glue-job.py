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
    sys.argv, ['JOB_NAME', 'SOURCE_LOCATION', 'OUTPUT_LOCATION', 'FILE_NAMES'])
source = args['SOURCE_LOCATION']
destination = args['OUTPUT_LOCATION']
file_list = args['FILE_NAMES']

glueContext = GlueContext(SparkContext.getOrCreate())
job = Job(glueContext)
job.init(args['JOB_NAME'], args)

for file in file_list.split("|"):
    weather_data = glueContext.create_dynamic_frame.from_options(
        connection_type="s3",
        format="csv",
        connection_options={
            "paths": ["{}{}".format(source,file)]
        },
        format_options={
            "withHeader": False,
            "separator": ","
        },
        transformation_ctx="datasource"
    )
    weather_renamed = weather_data.apply_mapping([
        ("col0", "string", "weather_station", "string"), 
        ("col1", "string", "measurement_date", "string"), 
        ("col2", "string", "measurement_type", "string"), 
        ("col3", "string", "measured_value", "double")])
    weather_renamed.toDF().write.mode(
        "append").parquet('{}/'.format(destination))

job.commit()
