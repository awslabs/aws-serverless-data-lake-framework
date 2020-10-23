import boto3
import tarfile
import io
from io import StringIO
import pandas as pd


from datalake_library.commons import init_logger
from datalake_library import octagon
from datalake_library.octagon import Artifact, EventReasonEnum, peh
from datalake_library.configuration.resource_configs import S3Configuration, KMSConfiguration
from datalake_library.interfaces.s3_interface import S3Interface

logger = init_logger(__name__)
client = boto3.client('s3')
s3_interface = S3Interface()

def lambda_handler(event, context):
    """Compile Data to a CSV with Topic Model Output

    Arguments:
        event {dict} -- Dictionary with details on Bucket and Keys
        context {dict} -- Dictionary with details on Lambda context

    Returns:
        {dict} -- Dictionary with Processed Bucket and Keys Path
    """
    try:
        # Get Information about the Step Function 
        logger.info('Fetching event data from previous step')
        team = event['body']['team']
        stage = event['body']['pipeline_stage']
        dataset = event['body']['dataset']
        bucket = event['body']['bucket']
        
        # Start Connection to Octagon Client
        logger.info('Initializing Octagon client')
        component = context.function_name.split('-')[-2].title()
        octagon_client = (
            octagon.OctagonClient()
            .with_run_lambda(True)
            .with_configuration_instance(event['body']['env'])
            .build()
        )
        peh.PipelineExecutionHistoryAPI(octagon_client).retrieve_pipeline_execution(
            event['body']['job']['peh_id'])
        
        logger.info('Starting to Compile Results')
        
        
        # Here we will get associate topics and add to our existing metadata
        # for each of the abstract text files  we have in the pre-stage bucket:
        
        # Get the s3 location of the zipped topic model output
        key = "post-stage/{}/{}/".format(team, dataset)
        my_bucket = client.list_objects_v2(Bucket = bucket, Prefix = key)
        for objects in my_bucket["Contents"]:
            if ".tar.gz" in objects["Key"]:
                key = (objects["Key"])

        # Extract the Topic Model Data from the zipped file
        s3_object = client.get_object(Bucket=bucket, Key=key)
        wholefile = s3_object['Body'].read()
        fileobj = io.BytesIO(wholefile)
        tarf = tarfile.open(fileobj=fileobj)
        csv_files = [f.name for f in tarf.getmembers() if f.name.endswith('.csv')]
        
        # Read in both the Doc-Topics and Topic-Terms csv files using Pandas DataFrames
        #   doc-topics.csv (The topics for each abstract document)
        #   topic-terms.csv (The terms associated to each topic - up to 10 terms)
        for i in csv_files:
            if "doc-topics" in i:
                csv_contents = tarf.extractfile(i).read()
                doc_topics = pd.read_csv(io.BytesIO(csv_contents), encoding='utf8')
            
            if "topic-terms" in i:
                csv_contents1 = tarf.extractfile(i).read()
                topic_terms = pd.read_csv(io.BytesIO(csv_contents1), encoding='utf8')
              
              
        # Group All of the Topics as a List for Each Abstract Docname 
        doc_topics_grouped = doc_topics.groupby("docname")["topic"].apply(list).reset_index(name='topic_list')
        
        # Group All of the Terms Associated to each of the Topics Found
        topic_terms_grouped = topic_terms.groupby("topic")["term"].apply(list).reset_index(name='term_list')
        
        
        # For Each Abstract We Will Add a Column with the Associated Topic Terms (i.e. 'term_list')
        main_list = []
        for index, row in doc_topics_grouped.iterrows():
            labels = []
            for topic in row[1]:
                l = topic_terms_grouped.loc[topic][1]
                labels.extend(l)
            main_list.append(labels)
        doc_topics_grouped['term_list'] = main_list


        # Now Lets Pull All the PreStage Metadata we Have for Each Abstract Document:
        
        # List csv Files in the Pre-stage Bucket
        key = "pre-stage/{}/{}/medical_data".format(team, dataset)
        response = client.list_objects_v2(Bucket = bucket, Prefix = key)

        # Combine All the Metadata into one Large Pandas DataFrame
        count = 0
        for contents in response['Contents']:
            if contents['Size'] > 0:
                if count < 1:
                    obj = client.get_object(Bucket = bucket, Key = contents["Key"])
                    metadata = pd.read_csv(io.BytesIO(obj['Body'].read()), encoding='utf8')
                else:
                    obj = client.get_object(Bucket = bucket, Key = contents["Key"])
                    df = pd.read_csv(io.BytesIO(obj['Body'].read()), encoding='utf8')
                    metadata = metadata.append(df, ignore_index = True)
                count = count + 1
            
        
        # IMPORTANT: Now we can merge the Topics and Terms
        # we found for each document with the existing Metadata
        doc_topics_final = pd.merge(metadata,doc_topics_grouped,on = 'docname')
        
        
        # We will also create a training data csv (including topics and text only) so new documents 
        # can be associated to one of these topics using  Multi-Label Classification:
        label_list = []
        for index, row in doc_topics_final.iterrows():
            if len(doc_topics_final["topic_list"][index])>1:
                listToStr = '|'.join([str(elem) for elem in doc_topics_final["topic_list"][index]])
                label_list.append(listToStr)
            else:
                label_list.append(str(doc_topics_final["topic_list"][index][0]))
        
        # Create Training Data DataFrame from the two columns
        training_data = pd.DataFrame(list(zip(label_list, doc_topics_final["abstract"])), columns =['Labels', 'Abstracts'])

        # Get KMS Key to Encrypt Data
        kms_key = KMSConfiguration(team).get_kms_arn
        
        # Write Our DataFrames with Output to S3 Post-Stage:
        # Write Training data to s3 Post-Stage Bucket
        output_path = "training_data.csv"
        s3_path_key = "post-stage/{}/{}/multilabel_classification/{}".format(team, dataset,output_path)
        training_data.to_csv('/tmp/' + output_path,index = False, header = False)
        s3_interface.upload_object('/tmp/' + output_path, bucket, s3_path_key, kms_key=kms_key)
        
        # Write Final df to s3 Post-Stage Bucket
        output_path = "compile_topics_data.csv"
        s3_path_key = "post-stage/{}/{}/{}".format(team, dataset, output_path)
        doc_topics_final.to_csv('/tmp/' + output_path)
        s3_interface.upload_object('/tmp/' + output_path, bucket, s3_path_key, kms_key=kms_key)

        # Write doc_topics df to s3 Post-Stage Bucket
        output_path = "doc_topics.csv"
        s3_path_key = "post-stage/{}/{}/topic_data/{}".format(team, dataset, output_path)
        doc_topics.to_csv('/tmp/' + output_path)
        s3_interface.upload_object('/tmp/' + output_path, bucket, s3_path_key, kms_key=kms_key)
    
        # Write topic_terms df to s3 Post-Stage Bucket
        output_path = "topic_terms.csv"
        s3_path_key = "post-stage/{}/{}/topic_data/{}".format(team, dataset, output_path)
        topic_terms.to_csv('/tmp/' + output_path)
        s3_interface.upload_object('/tmp/' + output_path, bucket, s3_path_key, kms_key=kms_key)
        
        
        # Update Pipeline Execution in Octagon
        octagon_client.update_pipeline_execution(
            status="{} {} Processing".format(stage, component), component=component)
    except Exception as e:
        logger.error("Fatal error", exc_info=True)
        octagon_client.end_pipeline_execution_failed(component=component,
                                                     issue_comment="{} {} Error: {}".format(stage, component, repr(e)))
        raise e
    return 200
