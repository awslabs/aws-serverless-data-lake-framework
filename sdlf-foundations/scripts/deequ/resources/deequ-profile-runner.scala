import java.time.LocalDate
import java.time.format.DateTimeFormatter
import java.text.SimpleDateFormat
import java.util.Date

import com.amazonaws.services.glue.ChoiceOption
import com.amazonaws.services.glue.GlueContext
import com.amazonaws.services.glue.MappingSpec
import com.amazonaws.services.glue.ResolveSpec
import com.amazonaws.services.glue.errors.CallSite
import com.amazonaws.services.glue.util.GlueArgParser
import com.amazonaws.services.glue.util.Job
import com.amazonaws.services.glue.util.JsonOptions
import org.apache.spark.SparkContext
import org.apache.spark.sql.functions._
import org.apache.spark.sql.DataFrame

import scala.collection.JavaConverters._
import org.apache.spark.sql.{Row, SQLContext}
import org.apache.spark.sql.types

import com.amazon.deequ.profiles.{ColumnProfilerRunner, NumericColumnProfile}

object GlueApp {

  val sc: SparkContext = new SparkContext()
  val glueContext: GlueContext = new GlueContext(sc)
  val spark = glueContext.getSparkSession
  val getYear = LocalDate.now().format(DateTimeFormatter.ofPattern("yyyy"))
  val getMonth = LocalDate.now().format(DateTimeFormatter.ofPattern("MM"))
  val getDay = LocalDate.now().format(DateTimeFormatter.ofPattern("dd"))
  val getTimestamp = new SimpleDateFormat("HH-mm-ss").format(new Date)
  import spark.implicits._

  def main(sysArgs: Array[String]) {

    val args = GlueArgParser.getResolvedOptions(sysArgs, Seq("JOB_NAME",
      "team",
      "dataset",
      "glueDatabase",
      "glueTables",
      "targetBucketName").toArray)

    Job.init(args("JOB_NAME"), glueContext, args.asJava)

    val team = args("team")
    val dataset = args("dataset")
    val dbName = args("glueDatabase")
    val tabNames = args("glueTables").split(",").map(_.trim)

    for (tabName <- tabNames) {
        val profiler_df = glueContext.getCatalogSource(database = dbName,
        tableName = tabName,
        redshiftTmpDir = "",
        transformationContext = "datasource0").getDynamicFrame().toDF()

        val profileResult = ColumnProfilerRunner()
        .onData(profiler_df)
        .run()

        val profileResultDataset = profileResult.profiles.map {
        case (productName, profile) => (
            productName,
            profile.completeness,
            profile.dataType.toString,
            profile.approximateNumDistinctValues)
        }.toSeq.toDS

        val finalDataset = profileResultDataset
            .withColumnRenamed("_1", "column")
            .withColumnRenamed("_2", "completeness")
            .withColumnRenamed("_3", "inferred_datatype")
            .withColumnRenamed("_4", "approx_distinct_values")
            .withColumn("timestamp", lit(current_timestamp()))

        writeDStoS3(finalDataset, args("targetBucketName"), "profile-results", team, dbName, tabName, getYear, getMonth, getDay, getTimestamp)
    }

    Job.commit()

  }

  /***
   * Write results data set to S3
   * @param resultDF
   * @param s3Bucket
   * @param s3Prefix
   * @param team
   * @param dataset
   * @param tabName
   * @return
   */
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