import os
import json
import math

import boto3

from datalake_library.commons import init_logger
from datalake_library.configuration.resource_configs import SQSConfiguration,\
    StateMachineConfiguration, S3Configuration
from datalake_library.interfaces.sqs_interface import SQSInterface
from datalake_library.interfaces.states_interface import StatesInterface

logger = init_logger(__name__)


def lambda_handler(event, context):
    """Checks if any items need processing and triggers state machine
    Arguments:
        event {dict} -- Dictionary with no relevant details
        context {dict} -- Dictionary with details on Lambda context 
    """

    # TODO Implement Redrive Logic (through message_group_id)
    try:
        team = event['team']
        pipeline = event['pipeline']
        stage = event['pipeline_stage']
        dataset = event['dataset']
        org = event['org']
        app = event['app']
        env = event['env']
        stage_bucket = S3Configuration().stage_bucket
        
        sqs_config = SQSConfiguration(team, dataset, stage)
        
        #Workload management changes
        #--------------------------- 
        #---------------------------
        
        max_sfn_executions = 3
        
        state_config = StateMachineConfiguration(team, pipeline, stage)
        STEPFUNCTION_ARN=state_config.get_stage_state_machine_arn
        #SFN processing code 
        #---------------------------------
        executions = StatesInterface().list_state_executions(STEPFUNCTION_ARN, 'RUNNING', 50)
        
        current_sfn_exeuction = len(executions)
        logger.info(f"current_sfn_exeuctions:{current_sfn_exeuction}")
        
        if(current_sfn_exeuction < max_sfn_executions):
            sfn_available_slots = max_sfn_executions - current_sfn_exeuction
            logger.info(f"sfn_available_slots:{sfn_available_slots}")
        else:
            logger.info("No step function slot empty ----- exiting")
            return
        #-----------------------------------
        
        
        keys_to_process = []
        #Dynamically manging workload from different priority queues
        #------------------------------------
        for priority in ["HIGH", "LOW"]:  #high=10 #low=30 sfn slots=40
            print(priority)
            sqs_config = SQSConfiguration(team, dataset, stage, priority)
            queue_interface = SQSInterface(sqs_config.get_stage_queue_name_wlm)
            
            message_queue = queue_interface._message_queue
            num_messages_queue = int(
            message_queue.attributes['ApproximateNumberOfMessages'])
            logger.info(f"Number of messages in {message_queue}:{num_messages_queue}")
            
            if(num_messages_queue == 0):
                logger.info(f"Not enough messages in {message_queue}, trying next prority queue")
            else:
                if(num_messages_queue >= sfn_available_slots): #Example  40>20 12>8 for high priority sqs
                    num_messages_queue = sfn_available_slots
                    
                keys_to_process = queue_interface.wlm_receive_max_messages(keys_to_process, num_messages_queue)
                logger.info(f"messages:{keys_to_process}")
                sfn_available_slots = sfn_available_slots - num_messages_queue
                logger.info(f"sfn_available_slots:{sfn_available_slots}")
            if(sfn_available_slots==0):
                break
        #-------------------------------------
        
    
        
        #Running step function for processed messages
        #--------------------------------------
        if(len(keys_to_process)>0):
            for key in keys_to_process:
                response = {
                        'statusCode': 200,
                        'body': {
                            "bucket": stage_bucket,
                            "keysToProcess": [key],
                            "team": team,
                            "pipeline": pipeline,
                            "pipeline_stage": stage,
                            "dataset": dataset,
                            "org": org,
                            "app": app,
                            "env": env
                        }
                    }
                StatesInterface().run_state_machine(state_config.get_stage_state_machine_arn, response)
            logger.info(f"{len(keys_to_process)} messages sent to step function ")
        else:
            logger.info(f"Not enough messages in any queue --- exiting")
        #----------------------------------------
        #---------------------------------------

    except Exception as e:
        # If failure send to DLQ
        if keys_to_process:
            for key in keys_to_process:
                dlq_interface = SQSInterface(sqs_config.get_stage_dlq_name)
                dlq_interface.send_message_to_fifo_queue(
                    json.dumps(key), 'failed')
        logger.error("Fatal error", exc_info=True)
        raise e
    return
