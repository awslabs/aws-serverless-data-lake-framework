import com.amazonaws.services.glue.ChoiceOption
import com.amazonaws.services.glue.GlueContext
import com.amazonaws.services.glue.MappingSpec
import com.amazonaws.services.glue.ResolveSpec
import com.amazonaws.services.glue.errors.CallSite
import com.amazonaws.services.glue.util.GlueArgParser
import com.amazonaws.services.glue.util.Job
import com.amazonaws.services.glue.util.JsonOptions
import org.apache.spark.SparkContext

import scala.collection.JavaConverters._
import org.apache.spark.sql.{DataFrame, Row, SQLContext}
import org.apache.spark.sql.types._
import org.apache.spark.sql.functions._
import org.apache.spark.rdd.RDD

import scala.util.matching.Regex
import java.util.HashMap

import com.amazonaws.services.dynamodbv2.model.AttributeValue
import org.apache.hadoop.io.Text
import org.apache.hadoop.dynamodb.DynamoDBItemWritable

/* Importing DynamoDBInputFormat and DynamoDBOutputFormat */
import org.apache.hadoop.dynamodb.read.DynamoDBInputFormat
import org.apache.hadoop.dynamodb.write.DynamoDBOutputFormat
import org.apache.hadoop.mapred.JobConf
import org.apache.hadoop.io.LongWritable

//Amazon Deequ Import
import com.amazon.deequ.constraints.Constraint
import com.amazon.deequ.suggestions.{ConstraintSuggestion, ConstraintSuggestionResult, ConstraintSuggestionRunner, Rules}
//Verification and Analysis Imports
import com.amazon.deequ.analyzers.runners.AnalysisRunner
import com.amazon.deequ.{VerificationSuite, VerificationResult}
import com.amazon.deequ.VerificationResult.checkResultsAsDataFrame
import com.amazon.deequ.checks.{Check, CheckLevel}
import com.amazon.deequ.constraints.ConstrainableDataTypes
import com.amazon.deequ.analyzers.runners.{AnalysisRunner, AnalyzerContext}
import com.amazon.deequ.analyzers.runners.AnalyzerContext.successMetricsAsDataFrame
import com.amazon.deequ.analyzers._
import com.amazon.deequ.analyzers.Analyzer
import com.amazon.deequ.metrics.Metric

import java.time.LocalDate
import java.time.format.DateTimeFormatter
import java.text.SimpleDateFormat
import java.util.Date


object GlueApp {
  def main(sysArgs: Array[String]) {
    val sparkContext: SparkContext = new SparkContext()
    val glueContext: GlueContext = new GlueContext(sparkContext)
    val sqlContext = new SQLContext(sparkContext)
    val spark = glueContext.getSparkSession
    val args = GlueArgParser.getResolvedOptions(sysArgs, Seq("JOB_NAME", "dynamodbSuggestionTableName", "dynamodbAnalysisTableName", "team", "dataset", "glueDatabase", "glueTables", "targetBucketName").toArray)
    Job.init(args("JOB_NAME"), glueContext, args.asJava)

    val dynamodbSuggestionTableName = args("dynamodbSuggestionTableName")
    val dynamodbAnalysisTableName = args("dynamodbAnalysisTableName")
    val team = args("team")
    val dataset = args("dataset")
    val dbName = args("glueDatabase")
    val tabNames = args("glueTables").split(",").map(_.trim)
    val getYear = LocalDate.now().format(DateTimeFormatter.ofPattern("yyyy"))
    val getMonth = LocalDate.now().format(DateTimeFormatter.ofPattern("MM"))
    val getDay = LocalDate.now().format(DateTimeFormatter.ofPattern("dd"))
    val getTimestamp = new SimpleDateFormat("HH-mm-ss").format(new Date)

    // Configure connection to DynamoDB
    var jobConf_add = new JobConf(spark.sparkContext.hadoopConfiguration)
    jobConf_add.set("mapred.output.format.class", "org.apache.hadoop.dynamodb.write.DynamoDBOutputFormat")
    jobConf_add.set("mapred.input.format.class", "org.apache.hadoop.dynamodb.read.DynamoDBInputFormat")

    import spark.implicits._

    for (tabName <- tabNames) {

      val glueDF = glueContext.getCatalogSource(database = dbName, tableName = tabName, redshiftTmpDir = "", transformationContext = "dataset").getDynamicFrame().toDF()

      val suggestionResult = {
        ConstraintSuggestionRunner()
          .onData(glueDF)
          .addConstraintRules(Rules.DEFAULT)
          .run()
      }

      val allConstraints: Seq[com.amazon.deequ.constraints.Constraint] = suggestionResult.constraintSuggestions.flatMap
      { case (_, suggestions) => suggestions.map {
        _.constraint
      }
      }.toSeq

      val suggestionDataFrame = suggestionResult.constraintSuggestions.flatMap {
        case (column, suggestions) =>
          suggestions.map { constraint =>
            (column, constraint.description, constraint.codeForConstraint)
          }
      }.toSeq.toDS().withColumn("uniqueID", monotonicallyIncreasingId)

      suggestionDataFrame.createOrReplaceTempView("suggestionDataFrame")

      val suggestionDataFrame_UniqId = spark.sql("select row_number() over (order by uniqueID) as row_num, * from suggestionDataFrame")

      val suggestionDataFrameRenamed = suggestionDataFrame_UniqId
        .withColumn("suggestion_hash_key", concat(lit("##"), lit(team), lit("##"), lit(dataset), lit("##"), lit(tabName), lit("##"), $"_1", lit("##"), $"row_num"))
        .withColumnRenamed("_1", "column")
        .withColumnRenamed("_2", "constraint")
        .withColumnRenamed("_3", "constraint_code")
        .withColumn("enable", lit("Y"))
        .withColumn("table_hash_key", concat(lit(team), lit("-"), lit(dataset), lit("-"), lit(tabName)))
        .drop("uniqueID").drop("row_num")

      writeDStoS3(suggestionDataFrameRenamed, args("targetBucketName"), "constraint-suggestion-results", team, dataset, tabName, getYear, getMonth, getDay, getTimestamp)

      writeToDynamoDB(suggestionDataFrameRenamed, dynamodbSuggestionTableName)

      verificationRunner(glueDF, allConstraints, team, dataset, tabName, getYear, getMonth, getDay, getTimestamp)
      analysisRunner(glueDF, allConstraints, team, dataset, tabName, getYear, getMonth, getDay, getTimestamp)
    }

    Job.commit()


    def verificationRunner(glueDF: DataFrame, allConstraints: Seq[com.amazon.deequ.constraints.Constraint], team: String, dataset: String, tabName: String, getYear: String, getMonth: String, getDay: String, getTimestamp: String) = {
      val autoGeneratedChecks = Check(CheckLevel.Error, "data constraints", allConstraints)
      val verificationResult = VerificationSuite().onData(glueDF).addChecks(Seq(autoGeneratedChecks)).run()
      val resultDataFrame = checkResultsAsDataFrame(spark, verificationResult)
      writeDStoS3(resultDataFrame, args("targetBucketName"), "constraints-verification-results", team, dbName, tabName, getYear, getMonth, getDay, getTimestamp)
    }


    def analysisRunner(glueDF: DataFrame, allConstraints: Seq[com.amazon.deequ.constraints.Constraint], team: String, dataset: String, tabName: String, getYear: String, getMonth: String, getDay: String, getTimestamp: String) = {
      val autoGeneratedChecks = Check(CheckLevel.Error, "data constraints", allConstraints)
      val analyzersFromChecks = Seq(autoGeneratedChecks).flatMap { _.requiredAnalyzers() }
      val analysisResult: AnalyzerContext = {
        AnalysisRunner
          .onData(glueDF)
          .addAnalyzers(analyzersFromChecks)
          .run()
      }
      val resultDataFrame = successMetricsAsDataFrame(spark, analysisResult)
      writeDStoS3(resultDataFrame, args("targetBucketName"), "constraints-analysis-results", team, dbName, tabName, getYear, getMonth, getDay, getTimestamp)
    }

    def writeToDynamoDB(dataFrameRenamed: DataFrame, dynoTable: String) = {

      val ddbWriteConf = new JobConf(spark.sparkContext.hadoopConfiguration)
      ddbWriteConf.set("dynamodb.output.tableName", dynoTable)
      ddbWriteConf.set("dynamodb.throughput.write.percent", "1.5")
      ddbWriteConf.set("mapred.input.format.class", "org.apache.hadoop.dynamodb.read.DynamoDBInputFormat")
      ddbWriteConf.set("mapred.output.format.class", "org.apache.hadoop.dynamodb.write.DynamoDBOutputFormat")
      ddbWriteConf.set("mapred.output.committer.class", "org.apache.hadoop.mapred.FileOutputCommitter")

      val schema_ddb = dataFrameRenamed.dtypes

      var ddbInsertFormattedRDD = dataFrameRenamed.rdd.map(a => {
        val ddbMap = new HashMap[String, AttributeValue]()

        for (i <- 0 to schema_ddb.length - 1) {
          val value = a.get(i)
          if (value != null) {
            val att = new AttributeValue()
            att.setS(value.toString)
            ddbMap.put(schema_ddb(i)._1, att)
          }
        }

        val item = new DynamoDBItemWritable()
        item.setItem(ddbMap)

        (new Text(""), item)
      }
      )

      ddbInsertFormattedRDD.saveAsHadoopDataset(ddbWriteConf)
    }


    def writeDStoS3(resultDF: DataFrame, s3Bucket: String, s3Prefix: String, team: String, dbName: String, tabName: String, getYear: String, getMonth: String, getDay: String, getTimestamp: String) = {

      resultDF.write.mode("append").parquet(s3Bucket + "/"
        + s3Prefix + "/"
        + "team=" + team + "/"
        + "database=" + dbName + "/"
        + "table=" + tabName + "/"
        + "year=" + getYear + "/"
        + "month=" + getMonth + "/"
        + "day=" + getDay + "/"
        + "hour=" + getTimestamp.split("-")(0) + "/"
        + "min=" + getTimestamp.split("-")(1) + "/"
      )

    }

  }


}
