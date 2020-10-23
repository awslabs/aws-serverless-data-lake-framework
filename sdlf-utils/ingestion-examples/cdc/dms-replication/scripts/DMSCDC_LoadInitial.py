import sys

from awsglue.job import Job
from pyspark.context import SparkContext
from pyspark.sql import SQLContext
from pyspark.sql import SparkSession
from pyspark.sql.functions import *
from awsglue.utils import getResolvedOptions
from awsglue.context import GlueContext

args = getResolvedOptions(sys.argv, [
    'JOB_NAME',
    'bucket',
    'prefix',
    'folder',
    'out_path',
    'partitionKey'])

sparkContext = SparkContext.getOrCreate()
glueContext = GlueContext(sparkContext)
spark = glueContext.spark_session
job = Job(glueContext)
job.init(args['JOB_NAME'], args)

s3_inputpath = 's3://' + args['bucket'] + '/' + args['prefix'] + args['folder']
s3_outputpath = 's3://' + args['out_path'] + args['folder']

input = spark.read.parquet(s3_inputpath+"/LOAD*.parquet").withColumn("Op", lit("I")).withColumn(
    'last_modified_at', unix_timestamp("last_modified_at", 'yyyy-MM-dd HH:mm:ss').cast("timestamp"))

partition_keys = args['partitionKey']
if partition_keys != "null":
    partitionKeys = partition_keys.split(",")
    input.repartition(partitionKeys[0]).write.mode(
        'overwrite').partitionBy(partitionKeys).parquet(s3_outputpath)
else:
    input.write.mode('overwrite').parquet(s3_outputpath)

job.commit()
