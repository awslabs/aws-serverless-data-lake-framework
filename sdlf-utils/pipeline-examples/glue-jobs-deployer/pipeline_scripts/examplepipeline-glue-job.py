import sys
import json
import boto3
import time
import pyspark.sql.functions as F
from datetime import datetime, timedelta
from collections import OrderedDict
from awsglue.transforms import *
from pyspark.sql.window import Window
from awsglue.utils import getResolvedOptions
from pyspark.context import SparkContext
from awsglue.context import GlueContext
from awsglue.job import Job
from awsglue.dynamicframe import DynamicFrame

# context initiation
glueContext = GlueContext(SparkContext.getOrCreate())
log = glueContext.get_logger()
args = getResolvedOptions(sys.argv, ['DATASET', 'JOB_NAME', 'start_date_string', 'end_date_string'])
sc = glueContext
spark = glueContext.spark_session

job = Job(glueContext)
job.init(args['JOB_NAME'], args)


# properties handler
class PropertiesHandler(object):

    def __init__(self, startDateStr='', endDateStr='', startYearStr='', endYearStr='', startMonthStr='', endMonthStr='',
                 startDayStr='', endDayStr='', targetTable='',
                 targetTableBucketLocation='', targetTablePathLocation='', targetTableFQDN='',
                 sourcePartitionYearField='',
                 sourcePartitionMonthField='', sourcePartitionDayField='',
                 maskedTargetDatabase='', maskedTargetTableBucketLocation='', columns2mask='',
                 maskedTargetTableFQDN='', targetDatabase='', redshiftOutputTable='', executeRedshiftExport=False,
                 outputToRedshift=False, redshiftCatalogConnection = '', logger=None, jobName='', logPath='',
                 processStartTime='', useControlTable=False, sendCloudWatchLogs=False,
                 cloudwatchLogGroup='SparkTransform', dynamoOutputTable = '',
                 hasDtPartition=False, partitionValues={},dynamoOutputNumParallelTasks=None,
                 redshiftTempBucket='', targetPartitionDtField='', sourcePartitionDtField='',
                 redshiftDatabase='', createViews=True,
                 useAnalyticsSecLayer=True, redshiftColumnsToExport='', dropDuplicates=False,
                 sourcesDict={}, reprocessDates=[], processDatesCondition='', datePartitionsSeparated=False,
                 isCdcTable=False, cdcTableKey='', jobId=0, executeSparkTransform=True, writeAsTable=True,
                 cdcDatePartitionsToProcess=[], sparkPartitions=0, outputFormat='parquet',
                 redshiftTempFormat='CSV GZIP', outputToDynamo=False, executeDynamoExport=False, env='dev',
                 datasetName=''):

        # FW PROPERTIES
        self.startDateStr = startDateStr
        self.endDateStr = endDateStr
        self.startYearStr = startYearStr
        self.endYearStr = endYearStr
        self.startMonthStr = startMonthStr
        self.endMonthStr = endMonthStr
        self.startDayStr = startDayStr
        self.endDayStr = endDayStr
        self.targetDatabase = targetDatabase
        self.targetTable = targetTable
        self.targetTableFQDN = targetTableFQDN
        self.env = env
        self.targetTableBucketLocation = targetTableBucketLocation
        self.targetTablePathLocation = targetTablePathLocation
        self.targetPartitionDtField = targetPartitionDtField
        self.sourcePartitionDtField = sourcePartitionDtField
        self.sourcePartitionYearField = sourcePartitionYearField
        self.sourcePartitionMonthField = sourcePartitionMonthField
        self.sourcePartitionDayField = sourcePartitionDayField
        self.maskedTargetDatabase = maskedTargetDatabase
        self.maskedTargetTableBucketLocation = maskedTargetTableBucketLocation
        self.maskedTargetTableFQDN = maskedTargetTableFQDN
        self.columns2mask = columns2mask
        self.redshiftOutputTable = redshiftOutputTable
        self.executeRedshiftExport = executeRedshiftExport
        self.outputToRedshift = outputToRedshift
        self.redshiftTempBucket = redshiftTempBucket
        self.redshiftDatabase = redshiftDatabase
        self.redshiftColumnsToExport = redshiftColumnsToExport
        self.redshiftTempFormat = redshiftTempFormat
        self.redshiftCatalogConnection = redshiftCatalogConnection
        self.logger = logger
        self.jobName = jobName
        self.datasetName = datasetName
        self.logPath = logPath
        self.endDateStr = endDateStr
        self.processStartTime = processStartTime
        self.useControlTable = useControlTable
        self.sendCloudWatchLogs = sendCloudWatchLogs
        self.cloudwatchLogGroup = cloudwatchLogGroup
        self.hasDtPartition = hasDtPartition
        self.partitionValues = partitionValues
        self.createViews = createViews
        self.useAnalyticsSecLayer = useAnalyticsSecLayer
        self.sourcesDict = sourcesDict
        self.reprocessDates = reprocessDates
        self.processDatesCondition = processDatesCondition
        self.datePartitionsSeparated = datePartitionsSeparated
        self.isCdcTable = isCdcTable
        self.dropDuplicates = dropDuplicates
        self.cdcTableKey = cdcTableKey
        self.jobId = jobId
        self.cdcDatePartitionsToProcess = cdcDatePartitionsToProcess
        self.sparkPartitions = sparkPartitions
        self.dynamoOutputTable = dynamoOutputTable
        self.dynamoOutputNumParallelTasks = dynamoOutputNumParallelTasks
        self.outputToDynamo = outputToDynamo
        self.executeDynamoExport = executeDynamoExport
        self.executeSparkTransform = executeSparkTransform
        self.writeAsTable = writeAsTable
        self.outputFormat = outputFormat

    def fillProperties(self, config):
        """Fills this object holder with json configs
        """
        # COMMON FRAMEWORK PROPERTIES
        sourceKeys = [key for key in config.keys() if key.startswith("source_database")]
        sourceValues = [config.get(key) for key in config.keys() if key.startswith("source_database")]
        for index, value in enumerate(sourceKeys, start=0):
            self.sourcesDict[sourceKeys[index]] = sourceValues[index]

        if config.get('target_database') is not None:
            self.targetDatabase = str(config.get('target_database'))
            self.targetTable = str(config.get('target_table'))
        else:
            self.targetTable =''

        self.targetTableBucketLocation = str(config.get('target_table_bucket_location'))
        self.targetTablePathLocation = str(config.get('target_table_path_location'))
        self.targetTableFQDN = self.targetDatabase + "." + self.targetTable

        if config.get('source_partition_year_field') is not None:
            self.sourcePartitionYearField = str(config.get('source_partition_year_field'))
            self.sourcePartitionMonthField = str(config.get('source_partition_month_field'))
            self.sourcePartitionDayField = str(config.get('source_partition_day_field'))
            self.datePartitionsSeparated = True
        elif config.get('source_partition_dt_field') is not None:
            self.sourcePartitionDtField = str(config.get('source_partition_dt_field'))
            self.datePartitionsSeparated = False

        if config.get('target_partition_dt_field') is not None:
            self.hasDtPartition = True
            self.targetPartitionDtField = str(config.get('target_partition_dt_field'))
        else:
            self.hasDtPartition = False

        self.processControlTable = str(config.get('process_control_table_name'))

        if config.get('execute_spark_transform') is not None:
            self.executeSparkTransform = str(config.get('execute_spark_transform')) == 'True'

        if config.get('write_as_table') is not None:
            self.writeAsTable = str(config.get('write_as_table')) == 'True'
        else:
            self.writeAsTable = True

        if config.get('output_format') is not None:
            self.outputFormat = str(config.get('output_format'))
        else:
            self.outputFormat = 'parquet'

        if config.get('spark_partitions_number') is not None:
            self.sparkPartitions = int(config.get('spark_partitions_number'))

        if config.get('use_analytics_sec_layer') is not None:
            self.useAnalyticsSecLayer = str(config.get('use_analytics_sec_layer')) == 'True'

        # DYNAMODB OUTPUT PROPERTIES
        if config.get('execute_dynamo_export') is not None:
            self.executeDynamoExport = str(config.get('execute_dynamo_export')) == 'True'
        if self.executeDynamoExport:
            self.dynamoOutputTable = str(config.get('dynamo_output_table'))
            self.dynamoKey = str(config.get('dynamo_key'))
            self.outputToDynamo = True
            self.dynamoOutputNumParallelTasks = str(config.get('dynamo_output_num_parallel_tasks'))

        # REDSHIFT OUTPUT PROPERTIES
        if config.get('execute_redshift_export') is not None:
            self.executeRedshiftExport = str(config.get('execute_redshift_export')) == 'True'
        if self.executeRedshiftExport:
            self.redshiftOutputTable = str(config.get('redshift_output_table'))
            self.outputToRedshift = True
            self.redshiftTempBucket = str(config.get('redshift_temp_bucket'))
            self.redshiftDatabase = str(config.get('redshift_database'))
            if config.get('redshift_columns_to_export') is not None:
                self.redshiftColumnsToExport = str(config.get('redshift_columns_to_export'))
            if config.get('redshift_temp_format') is not None:
                self.redshiftTempFormat = str(config.get('redshift_temp_format'))
            if config.get('redshift_catalog_connection') is not None:
                self.redshiftCatalogConnection = str(config.get('redshift_catalog_connection'))

        if config.get('is_cdc_table') is not None:
            self.isCdcTable = str(config.get('is_cdc_table')) == 'True'
            self.cdcTableKey = str(config.get('cdc_table_key'))
        if config.get('drop_duplicates') is not None:
            self.dropDuplicates = str(config.get('drop_duplicates')) == 'True'

        # MASKET OUTPUT
        self.maskedTargetDatabase = str(config.get('masked_target_database'))
        self.maskedTargetTableFQDN = self.maskedTargetDatabase + "." + self.targetTable
        self.maskedTargetTableBucketLocation = str(config.get('masked_target_table_bucket_location'))
        self.columns2mask = str(config.get('columns2mask'))


# helper functions
def getCurrentMilliTime():
    return int(round(time.time() * 1000))
def eliminateDuplicates(listToVerify):
    return list(dict.fromkeys(listToVerify))
def finish_job_ok():
    job.commit()
def finish_job_fail(err):
    raise Exception("{}:Exception raised: {}".format(args['JOB_NAME'], err))


def getSourceTables(sqlContent, props):
    tables = []
    lines = sqlContent.splitlines()
    for line in lines:
        line = line.replace('\n', '')
        wordsInLine = line.split(" ")
        for word in wordsInLine:
            finalWord = word.strip()
            if finalWord.startswith('$SOURCE_DATABASE'):
                sourceDatabase = props.sourcesDict.get(finalWord.split(".")[0].replace("$", "").lower())
                table = finalWord.split(".")[1]
                tables.append(sourceDatabase + "." + table)
    tables = eliminateDuplicates(tables)
    return tables


def setupConfig():
    """Configures the properties object read from json config_nonprod file
    """
    global sqlContent, params, s3, s3Client, dynamodb_client, stringParams, sourceTables
    s3 = boto3.resource('s3', region_name='us-east-1')
    s3Client = boto3.client('s3', region_name='us-east-1')
    dynamodb_client = boto3.resource('dynamodb', region_name='us-east-1')

    props.jobName = args['JOB_NAME']
    props.datasetName = args['DATASET']
    props.startDateStr = args['start_date_string']
    props.endDateStr = args['end_date_string']

    dateSplit = props.startDateStr.split("-")
    props.startYearStr = dateSplit[0]
    props.startYearStr = dateSplit[0]
    props.startMonthStr = dateSplit[1]
    props.startDayStr = dateSplit[2]

    log.info('Processing: ' + str(props.jobName))

    with open('{}.json'.format(dataset)) as file:
        jsonContent = file.read()
        ssm_client = boto3.client('ssm')
        env = ssm_client.get_parameter(Name='/SDLF/Misc/pEnv')['Parameter']['Value']
        accountid = boto3.client("sts").get_caller_identity().get("Account")
        props.env = env
        jsonContent = jsonContent.replace("$ENV", env)
        jsonContent = jsonContent.replace("$ACCOUNTID", accountid)
        athena_bucket = ssm_client.get_parameter(Name='/SDLF/S3/AthenaBucket')['Parameter']['Value']
        jsonContent = jsonContent.replace("$AthenaBucket", athena_bucket)
        analytics_bucket = ssm_client.get_parameter(Name='/SDLF/S3/AnalyticsBucket')['Parameter']['Value']
        jsonContent = jsonContent.replace("$AnalyticsBucket", analytics_bucket)
        analyticssec_bucket = ssm_client.get_parameter(Name='/SDLF/S3/AnalyticsSecBucket')['Parameter']['Value']
        jsonContent = jsonContent.replace("$AnalyticsSecBucket", analyticssec_bucket)
        params = json.loads(jsonContent)

    props.fillProperties(params)
    props.jobId = getCurrentMilliTime()

    with open('{}.sql'.format(dataset)) as file:
        sqlContent = file.read()

    sourceTables = getSourceTables(sqlContent, props)

    try:
        log.info("target_database: {}".format(props.targetDatabase))
        log.info("target_table: {}".format(props.targetTable))
    except:
        log.error('Error when logging in setupConfig. It could be due to non recognized characters')
    return


def getTablePartitionFields():
    global tablePartitionFields
    schemaDF = spark.sql("describe " + props.targetTableFQDN)
    schemaTmp = schemaDF.collect()
    tablePartitionFields = []
    inPartitionSection = False
    for elem in schemaTmp:
        if elem[0] == ('# col_name'):
            inPartitionSection = True
            continue
        if inPartitionSection:
            tablePartitionFields.append(elem[0])
    return


def getTableFields():
    global schemaDict
    schemaDF = spark.sql("describe " + props.targetTableFQDN)
    schemaTmp = schemaDF.collect()
    schemaDict = OrderedDict()
    for elem in schemaTmp:
        if elem[0] not in ('# col_name', '# Partition Information'):
            schemaDict[elem[0]] = elem[1]
        else:
            break  # this is to avoid the partition fields in the describe


def getDateRange(props):
    dates = []
    startDate = datetime.strptime(props.startDateStr, "%Y-%m-%d")
    endDate = datetime.strptime(props.endDateStr, "%Y-%m-%d")
    for n in range(int((endDate - startDate).days) + 1):
        generatedDate = startDate + timedelta(n)
        generatedDateStr = generatedDate.strftime("%Y-%m-%d")
        dates.append(generatedDateStr)
    return dates


def getSourceTimeCondition(props):
    condition = '( '
    parameterDates = getDateRange(props)
    parameterDates = parameterDates + props.reprocessDates
    datesToProcess = eliminateDuplicates(parameterDates)
    if props.datePartitionsSeparated:
        for date in datesToProcess:
            year = date.split("-")[0]
            month = date.split("-")[1]
            day = date.split("-")[2]
            condition += "( " + props.sourcePartitionYearField + " = '" + year + "' AND " \
                         + props.sourcePartitionMonthField + " = '" + month + "' AND " \
                         + props.sourcePartitionDayField + " = '" + day + "' ) OR "
    else:
        for date in datesToProcess:
            condition += "( " + props.sourcePartitionDtField + " = '" + date + "' )  OR "
    condition = condition[:-3]
    condition += ')'
    return condition


def deleteBucketPath(pathToDelete, targetTableBucketLocation):
    log.info('prefix to delete:::' + targetTableBucketLocation + '/' + pathToDelete)
    try:
        bucket = s3.Bucket(targetTableBucketLocation)
        bucket.objects.filter(Prefix=pathToDelete).delete()
        if not props.hasDtPartition:
            time.sleep(1)
            s3Client.put_object(Bucket=targetTableBucketLocation, Body='', Key=pathToDelete + '/')
    except Exception as x:
        err = 'Unable to delete partition from S3. ERROR : ' + str(x)
        log.error(err)
        finish_job_fail(err)


def getDateRangePartitions(props):
    dates = []
    datePartitions = []
    startDate = datetime.strptime(props.startDateStr, "%Y-%m-%d")
    endDate = datetime.strptime(props.endDateStr, "%Y-%m-%d")
    for n in range(int((endDate - startDate).days) + 1):
        generatedDate = startDate + timedelta(n)
        generatedDateStr = generatedDate.strftime("%Y-%m-%d")
        dates.append(generatedDateStr)

    dates = dates + props.reprocessDates
    dates = eliminateDuplicates(dates)
    for datePartition in dates:
        datePartitionPath = props.targetPartitionDtField + "=" + datePartition
        datePartitions.append(datePartitionPath)
    return datePartitions


def deleteOldData(targetTableBucketLocation):
    """Drops data directly in s3 to overwrite insert into operations in partitioned tables
    """
    # spark.sql("DROP TABLE IF EXISTS " + props.targetTableFQDN )
    # spark.sql("TRUNCATE TABLE " + props.targetTableFQDN )
    log.info('Table Bucket:::' + targetTableBucketLocation)

    partitions = []
    partitionToDelete = ''
    # KillAndFill table
    if not props.hasDtPartition and len(props.partitionValues) == 0:
        pathToDelete = props.targetTablePathLocation
        deleteBucketPath(pathToDelete, targetTableBucketLocation)
    else:
        select = " show partitions " + props.targetTableFQDN
        partitions = spark.sql(select).rdd.map(lambda x: x[0]).collect()
    # Incremental table
    # Case 1 - Only has dt partition
    if props.hasDtPartition and len(props.partitionValues) == 0:
        datePartitions = getDateRangePartitions(props)
        if props.isCdcTable:
            datePartitions = [props.targetPartitionDtField + "=" + datePartition for datePartition in
                              props.cdcDatePartitionsToProcess]
        for partitionToDelete in datePartitions:
            # if the table has other partition different than 1 date partitions, but are asking only for the date partition
            if len(tablePartitionFields) > 1:
                partitions = list(set(map(lambda x: x.split("/")[0], partitions)))
            if partitionToDelete in partitions:
                pathToDelete = props.targetTablePathLocation + "/" + partitionToDelete
                deleteBucketPath(pathToDelete, targetTableBucketLocation)
    # Case 2 - doesn't have date partition but has other partitions.  Assumption: you can ask only for one value per partition level.
    elif not props.hasDtPartition and len(props.partitionValues) > 0:
        for partitionFieldNameToDelete in props.partitionValues:
            partitionToDelete += partitionFieldNameToDelete + "=" + props.partitionValues[
                partitionFieldNameToDelete] + "/"
        partitionToDelete = partitionToDelete[:-1]
        if partitionToDelete in partitions:
            pathToDelete = props.targetTablePathLocation + "/" + partitionToDelete
            deleteBucketPath(pathToDelete, targetTableBucketLocation)
    # Case 3 - have date partition and other partitions. Assumption: date partition is the first partition level. for the other partitions, you can ask only for one value per partition level.
    elif props.hasDtPartition and len(props.partitionValues) > 0:
        for dtPartitionToDelete in getDateRangePartitions(props):
            for partitionFieldNameToDelete in props.partitionValues:
                partitionToDelete += partitionFieldNameToDelete + "=" + props.partitionValues[
                    partitionFieldNameToDelete] + "/"
            partitionToDelete = partitionToDelete[:-1]
            completePartition = dtPartitionToDelete + "/" + partitionToDelete

            if completePartition in partitions:
                pathToDelete = props.targetTablePathLocation + "/" + completePartition
                deleteBucketPath(pathToDelete, targetTableBucketLocation)
            partitionToDelete = ''


def getCdcPartitionsToProcess(dfSource):
    dfDates = dfSource.select(props.targetPartitionDtField).distinct()
    dtList = [str(row[0]) for row in dfDates.collect()]
    return dtList


def createAnalyticsFolderIfNotExists(props):
    pathToCreate = props.targetTablePathLocation + '/'
    log.info('prefix to create for cdc kill and fill:::' + pathToCreate)
    try:
        s3Client.put_object(Bucket=props.targetTableBucketLocation, Body='', Key=pathToCreate)
        time.sleep(1)
    except Exception as x:
        log.error('cdc kill and fill path already exists ... continue : ')


def createCdcTempTableSQL(props):
    createTempTableSql = "select * from " + props.targetTableFQDN
    if props.hasDtPartition:
        createTempTableSql += " where " + props.targetPartitionDtField + " in ("
        for date in props.cdcDatePartitionsToProcess:
            createTempTableSql += "'" + date + "',"
        createTempTableSql = createTempTableSql[:-1]
        createTempTableSql += ')'
    tempDf = spark.sql(createTempTableSql)
    tempDf.write.mode("overwrite").format("parquet").saveAsTable(
        props.targetDatabase + "._" + props.targetTable + "_temp")
    return createTempTableSql


def mergeCdcData(mergedDfTarget, primaryKeyArray, orderByField):
    """ Combine data and get the latest row out for a primary key based on the change_order_by key
    :param mergeddfTarget: dataframe with old and new records
    :param primary_key: database primary
    :param change_order_by: by time - last updated timestamp
    :return: dataframe - with the merged records
    """
    win = Window().partitionBy(primaryKeyArray).orderBy(F.col(orderByField).desc())
    mergedTargetRanked = mergedDfTarget.withColumn("order_inc_rank", F.row_number().over(win))
    mergeTargetRankedWithoutDuplicates = mergedTargetRanked.dropDuplicates()
    rowsWithLatestUpdatesDf = mergeTargetRankedWithoutDuplicates.filter(
        mergeTargetRankedWithoutDuplicates.order_inc_rank == 1)
    rowsWithLatestUpdatesDf = rowsWithLatestUpdatesDf.drop("order_inc_rank")
    return rowsWithLatestUpdatesDf


def processCdcFlow(props, newDF):
    tempTableSQL = "select * from " + props.targetDatabase + "._" + props.targetTable + "_temp "
    log.info("CDC  Temp Table Select: " + tempTableSQL)
    existingTarget = spark.sql(tempTableSQL)
    unionTarget = existingTarget.union(newDF)
    updatedTarget = mergeCdcData(unionTarget, props.cdcTableKey.split(","), "job_id")
    if props.isCdcTable:
        deleteOldData(props.targetTableBucketLocation)
    if props.sparkPartitions > 0:
        updatedTarget.coalesce(props.sparkPartitions).write.mode("overwrite").format("parquet").insertInto(
            props.targetTableFQDN)
    else:
        updatedTarget.write.mode("overwrite").format("parquet").insertInto(props.targetTableFQDN)


def writeTableToTargetBucket():
    # Initialize metadata objects related to target table
    if props.writeAsTable:
        getTablePartitionFields()
        getTableFields()
    props.processDatesCondition = getSourceTimeCondition(props)

    queryHql = sqlContent.replace('\t', '    ')
    queryHql = queryHql.replace("$TARGET_DATABASE", "'" + props.targetDatabase + "'")
    queryHql = queryHql.replace("$START_DATE", "'" + props.startDateStr + "'")
    queryHql = queryHql.replace("$END_DATE", "'" + props.endDateStr + "'")
    queryHql = queryHql.replace("$START_YEAR", "'" + props.startYearStr + "'")
    queryHql = queryHql.replace("$START_MONTH", "'" + props.startMonthStr + "'")
    queryHql = queryHql.replace("$START_DAY", "'" + props.startDayStr + "'")
    queryHql = queryHql.replace("$END_YEAR", "'" + props.endYearStr + "'")
    queryHql = queryHql.replace("$END_MONTH", "'" + props.endMonthStr + "'")
    queryHql = queryHql.replace("$END_DAY", "'" + props.endDayStr + "'")
    queryHql = queryHql.replace("$TIME_CONDITION", props.processDatesCondition)

    for index, value in enumerate(props.partitionValues.values(), start=1):
        queryHql = queryHql.replace("$VALUE_" + str(index), value)

    for value in props.sourcesDict.keys():
        if value == 'source_database':
            queryHql = queryHql.replace("$SOURCE_DATABASE.", props.sourcesDict[value] + ".")
        else:
            queryHql = queryHql.replace("$SOURCE_DATABASE_" + value.split("_")[-1] + ".",
                                        props.sourcesDict[value] + ".")

    log.info("JOB_ID::: " + str(props.jobId))

    queryHql = queryHql.replace('$JOB_ID', str(props.jobId))

    if not props.isCdcTable:
        deleteOldData(props.targetTableBucketLocation)

    spark.conf.set("spark.sql.sources.partitionOverwriteMode", "dynamic")
    spark.conf.set("spark.sql.crossJoin.enabled", "true")
    spark.conf.set("hive.exec.dynamic.partition.mode", "nonstrict")
    if props.writeAsTable:
        spark.sql("use " + props.targetDatabase)

    log.info("sql: " + queryHql)
    try:
        resultDf = spark.sql(queryHql)
        log.info('Query executed')
        if props.isCdcTable:
            if props.hasDtPartition:
                props.cdcDatePartitionsToProcess = getCdcPartitionsToProcess(resultDf)
            else:
                createAnalyticsFolderIfNotExists(props)
            createCdcTempTableSQL(props)
            time.sleep(2)

    except Exception as x:
        err = 'Unable to process SQL query. ERROR : ' + str(x)
        log.error(err)
        finish_job_fail(err)

    if props.dropDuplicates==True:
        resultDf = resultDf.dropDuplicates()

    if props.isCdcTable:
        processCdcFlow(props, resultDf)
    else:
        if props.sparkPartitions > 0:
            if props.writeAsTable:
                resultDf.coalesce(props.sparkPartitions)\
                    .write.mode("overwrite")\
                    .format(props.outputFormat)\
                    .insertInto(props.targetTableFQDN, overwrite=True)
            else:
                resultDf.coalesce(props.sparkPartitions).write.mode("overwrite")\
                    .format(props.outputFormat) \
                    .option('header','true') \
                    .save('s3://'+props.targetTableBucketLocation+'/'+props.targetTablePathLocation+'/')
        else:
            if props.writeAsTable:
                resultDf.write.mode("overwrite")\
                    .format(props.outputFormat)\
                    .insertInto(props.targetTableFQDN, overwrite=True)
            else:
                resultDf.write.mode("overwrite")\
                    .format(props.outputFormat) \
                    .option('header', 'true') \
                    .save('s3://'+props.targetTableBucketLocation+'/'+props.targetTablePathLocation+'/')

    log.info("Query finished.")
    return


def getTargetTimeCondition(props):
    condition = '( '
    parameterDates = getDateRange(props)
    parameterDates = parameterDates + props.reprocessDates
    datesToProcess = eliminateDuplicates(parameterDates)
    if props.isCdcTable:
        datesToProcess = props.cdcDatePartitionsToProcess
    for date in datesToProcess:
        condition += "( " + props.targetPartitionDtField + " = '" + date + "' )  OR "
    condition = condition[:-3]
    condition += ')'
    return condition


def constructQueryPredicate(table):
    select = " from " + table
    if props.hasDtPartition:
        select += " where " + getTargetTimeCondition(props)
    if len(props.partitionValues) > 0:  # if there are additional partitions as parameters
        if not props.hasDtPartition:
            select += " where "
        else:
            select += " and "
        for field in props.partitionValues:
            select += str(field) + " = "
            if [field] == "string":
                select += "'"
            select += props.partitionValues[field]
            if schemaDict[field] == "string":
                select += "'"
            select += " and "
        select = select[:-4]
    return select

def writeTableToRedshift():
    selectExportSQL = 'select '

    if not props.executeSparkTransform:
        getTableFields()

    if props.redshiftColumnsToExport != '':
        selectExportSQL += props.redshiftColumnsToExport + " "
    else:
        for field in schemaDict:
            configField = field
            selectExportSQL += configField + ','
        selectExportSQL = selectExportSQL[:-1]
    selectExportSQL += constructQueryPredicate(props.targetTableFQDN)

    resultDf = spark.sql(selectExportSQL)
    log.info("EXPORT SQL::" + selectExportSQL)
    resultDynamicFrame = DynamicFrame.fromDF(resultDf, glueContext, props.dynamoOutputTable)
    sqlDeleteRedshift = "delete " + constructQueryPredicate(props.redshiftOutputTable)

    try:
        glueContext.write_dynamic_frame.from_jdbc_conf(frame=resultDynamicFrame,
                                                       catalog_connection=props.redshiftCatalogConnection,
                                                       connection_options={
                                                           "preactions": sqlDeleteRedshift,
                                                           "dbtable": props.redshiftOutputTable,
                                                           "database": props.redshiftDatabase},
                                                       redshift_tmp_dir="s3://" + props.redshiftTempBucket + "/")
    except Exception as x:
        err = 'Unable to export data in Redshift Table. ERROR : ' + str(x)
        log.error(err)
        finish_job_fail(err)


def writeTableToDynamo():
    selectViewSQL = 'select * '
    selectViewSQL += constructQueryPredicate(props.targetTableFQDN)
    #should be unique value to be able to inster in dynamodb
    resultDf = spark.sql(selectViewSQL).dropDuplicates([props.dynamoKey])
    resultDynamicFrame = DynamicFrame.fromDF(resultDf, glueContext, props.dynamoOutputTable)
    log.info("field Types:" + str(resultDynamicFrame.schema()))
    try:
        if props.dynamoOutputNumParallelTasks is not None:
            glueContext.write_dynamic_frame_from_options(
                frame=resultDynamicFrame,
                connection_type="dynamodb",
                connection_options={
                    "dynamodb.output.tableName": props.dynamoOutputTable,
                    "dynamodb.output.key": props.dynamoKey,
                    "dynamodb.throughput.write.percent": "1.5",
                    "dynamodb.output.numParallelTasks": props.dynamoOutputNumParallelTasks
                }
            )
            log.info('Result exported to DynamoDB')
        else:
            glueContext.write_dynamic_frame_from_options(
                frame=resultDynamicFrame,
                connection_type="dynamodb",
                connection_options={
                    "dynamodb.output.tableName": props.dynamoOutputTable,
                    "dynamodb.output.key": props.dynamoKey,
                    "dynamodb.throughput.write.percent": "1.5"
                }
            )
            log.info('Result exported to DynamoDB')
    except Exception as x:
        err = 'Unable to export data in DynamoDB Table. ERROR : ' + str(x)
        log.error(err)
        finish_job_fail(err)


def writeTableToMaskedBucket():
    deleteOldData(props.maskedTargetTableBucketLocation)
    spark.sql("use " + props.maskedTargetDatabase)
    select = "select "

    colslist = {}
    for col in props.columns2mask.split(';'):
        colsdir = {}
        colsdir["prefixLength"] = col.rsplit('(', 1)[1].replace(')', '').split(',')[0]
        colsdir["sufixLength"] = col.rsplit('(', 1)[1].replace(')', '').split(',')[1]
        colslist[col.rsplit('(', 1)[0]] = colsdir

    for field in schemaDict:
        if field in colslist.keys():
            configField = colslist[field]
            select += ' CONCAT( '
            select += ' substring(cast(' + field + ' as string), 0 ,' + configField['prefixLength'] + ') , '
            select += ' md5(cast(' + field + ' as string))'
            select += ' , substring(cast(' + field + ' as string), -' + configField['sufixLength'] + ' ,' + configField['sufixLength'] + ') '
            select += ' ) '
            select += ' as ' + field + ' ,'
        elif props.targetPartitionDtField != field and field not in tablePartitionFields:
            select += field + ','
    for field in tablePartitionFields:
        select += field + ','

    select = select[:-1]
    select += constructQueryPredicate(props.targetTableFQDN)
    log.info("MASKED SQL::" + select)
    resultDf = spark.sql(select)

    resultDf.write.mode("overwrite").format("parquet").insertInto(props.maskedTargetTableFQDN)
    log.info("Mask Query finished.")
    return


# Main flow
dataset = args['DATASET']
global props
processStartTime = getCurrentMilliTime()
props = PropertiesHandler()
props.processStartTime = processStartTime
setupConfig()
log.info("EXECUTE SPARK TRANSFORM::" + str(props.executeSparkTransform))
log.info("EXECUTE OUTPUT TO REDSHIFT::" + str(props.outputToRedshift))
log.info("CREATE VIEWS ::" + str(props.createViews))
log.info("EXECUTE ANALYTICS MASKED LAYER ::" + str(props.useAnalyticsSecLayer))
log.info("EXECUTE OUTPUT TO DYNAMO::::" + str(props.outputToDynamo))
if props.executeSparkTransform:
    writeTableToTargetBucket()
if props.useAnalyticsSecLayer:
    writeTableToMaskedBucket()
if props.outputToRedshift:
    writeTableToRedshift()
if props.outputToDynamo:
    writeTableToDynamo()
finish_job_ok()
