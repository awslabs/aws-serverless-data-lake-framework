# Pipeline testing
Testing a data lake

**Installation**
Create a dynamodb table 'datalake-test-config'. Load the src/datalake-test-config.csv. (Add your tests in this csv)
Install the step functions src/state_machines/\*.json, and the lambda functions src/lambdas/\*.py. You will need to ensure that appropriate IAM roles and permissions are set up.

**Execute**
The src/state_machines/DataLakeTestController.json is the controlling step function. Trigger this via any method such as:
- You can simply plug this in to your serverless data lake framework if you like, or
- schedule it to execute in cloudwatch, or
- trigger it via AWS Config, or
- Add it as a stage in your code pipeline.

**Architecture**
The high-level architecture of the data lake testing framework is show in this diagram.

![Architecture](docs/DataLakeTestingArchitecture.jpg)
