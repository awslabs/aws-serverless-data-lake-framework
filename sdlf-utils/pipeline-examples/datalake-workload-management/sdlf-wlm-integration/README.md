# Chnages required to SDLF in order to accomodate work load management solution.
1. We need to add a new table along with its paramters store in sdlf-foundations --> nested-stacks --> template-dynamodb.yaml
    ```bash
        rDynamoOctagonWlm:
            Type: AWS::DynamoDB::Table
            Properties:
                KeySchema:
                  - AttributeName: name
                    KeyType: HASH
                AttributeDefinitions:
                  - AttributeName: name
                    AttributeType: S
                BillingMode: PAY_PER_REQUEST
                TableName: !Sub octagon-wlm-${pEnvironment}
                SSESpecification:
                  SSEEnabled: True
                  SSEType: KMS
                  KMSMasterKeyId: !Ref pKMSKeyId
            UpdateReplacePolicy: Retain
            DeletionPolicy: Delete

        rDynamoWlmSsm:
            Type: AWS::SSM::Parameter
            Properties:
                Name: /SDLF/Dynamo/wlm
                Type: String
                Value: !Ref rDynamoOctagonWlm
                Description: Name of the DynamoDB used to store wlm dataset-table priority metadata
    ```

2. We need make changes in the sdlf-team --> nested stack ---> template-iam.yaml. Below changes are required.
    ```bash
        rTeamIAMManagedPolicy:--> Add states:ListExecutions permission to the sdlf permissions boundry

        rCICDCodeBuildRole: --> Add octagon-wlm-${pEnvironment} at the resource section of the dynamodo actions
    ```

3. Changes required in sdlf-datalakelibrary/python/datalake_library. copy the below files to the actual sdlf repo. These files are modified with new handler functions and source code updates to work with wlm demo
    ```bash
        configuration --> resource_configs.py

        interfaces --> dynamo_interface.py/sqs_interface.py/states_interface.py

        transforms --> stage_a_transforms --> light_transform_blueprint.py

        transforms --> stage_b_transforms --> heavy_transform_blueprint.py
    ```
4. sdlf-dataset changes are most crucial in order to make wlm solution work. copy the below files and directory to the origional sdlf-dataset directory
    ```bash
        wlm/scripts/fill_ddb.py --> This script will put the items in the wlm ddb table for WLM solution

        wlm/wlm-team-dataset-tables-priority.json --> All dataset priority metadata need to be in this json file for WLM solution to work

        deploy.sh --> script is changed to execute the fill_ddb.py python script to put data into wlm ddb table

        template.yaml --> High/Low Priority sqs queues and their respective ssm are added.
    ```

5. sdlf-stageA and sdlf-stageB will hold the updated source code for WLM which uses sdlf handler function from datalake library. Copy the files and replace the original code with the below
    ```bash
        sdlf-stageA --> lambda --> stage-a-postupdate-metadata/src/lambda_function.py --> code changes that will evaluate which priority sqs queue to send the message based on the metadata defined at the wlm ddb table

        sdlf-stageB --> lambda --> stage-b-routing/src/lambda_function.py --> code changes that will figure out if there are available execution steps available in step function, based on available slots it will evaluate the messages to pull based on work load management logic

        sdlf-stageB --> lambda --> stage-b-redrive/src/lambda_function.py  --> After any failure, once the error is resolved, take the original message from step function for failed execution and use lambda console to execute using the event. This lambda will put it into the relevant priority sqs queues based on metadata in WLM ddb table
        
        sdlf-stageB --> template.yaml --> rRoleLambdaExecutionRoutingStep --> add states:ListExecutions permission action
    ```

# Demoing the WLM solution with SDLF 
    The Demo folder contains all required data and script need to start the demo with usual SDLF templates. Make sure the above changes are already implemented with atleast one team/pipeline/dataset before starting the demo.

    Use the deploy.sh script to start the demo. It will deploy the glue role and glue job as a cloudformation stack and copy the data to the s3 bucket