# sdlf-stage-dataquality

!!! note
    `sdlf-stage-dataquality` is defined in the [sdlf-stageA](https://github.com/awslabs/aws-serverless-data-lake-framework/tree/main/sdlf-stage-dataquality) folder of the [SDLF repository](https://github.com/awslabs/aws-serverless-data-lake-framework).

## Infrastructure

![SDLF Stage Data Quality](../_static/sdlf-stage-dataquality.png)

Create a Glue Data Quality ruleset from recommendations then apply this ruleset to a given Glue table.

## Usage

### CloudFormation with [sdlf-cicd](cicd.md)

Read the official [SDLF workshop](https://sdlf.workshop.aws/) for an end-to-end deployment example.

```
rMainDq:
    Type: proserve::iot::dataquality::MODULE
    Properties:
        pPipelineReference: !Ref pPipelineReference
        pStageName: DQ
        pPipeline: main
        pTeamName: iot
        pTriggerType: event
        pEventPattern: !Sub >-
            {
                "source": ["aws.states"],
                "detail-type": ["Step Functions Execution Status Change"],
                "detail": {
                    "status": ["SUCCEEDED"],
                    "stateMachineArn": ["arn:${AWS::Partition}:states:${AWS::Region}:${AWS::AccountId}:stateMachine:sdlf-iot-main-sm-b"]
                }
            }
        pEnableTracing: false
```

## Interface

Interfacing with other modules is done through [SSM Parameters](https://docs.aws.amazon.com/systems-manager/latest/userguide/systems-manager-parameter-store.html). `sdlf-stage-dataquality` publishes the following parameters:

| SSM Parameter                                        | Description                                                      | Comment                                      |
| ---------------------------------------------------- | ---------------------------------------------------------------- | -------------------------------------------- |
| `/SDLF/SM/{team}/{pipeline}{stage}SM`                | Step Function                                                    |                                              |
