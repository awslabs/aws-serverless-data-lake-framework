# Serverless Data Lake Framework (SDLF)

## GitLab

![diagram](SDLF_GitLab.png "Modification")

1. The foundations stacks are still created from the deploy script
2. The team repositories creation is delegated to GitLab using the following features:
    1. An user and an [access token](https://docs.gitlab.com/ee/user/profile/personal_access_tokens.html): This allows to use a dedicated access from the pipelines to allow the team and pipelines repositories creation and execution.
    2. An AWS credentials access key and secret key (with the option to assume a specific role). This allows to create the repositories on CodeCommit.
  These feature are triggered from the file gitlab-team-pipelines.yml
3. The git mirroring is setup using the [push mirroring](https://docs.gitlab.com/ee/user/project/repository/mirror/push.html#set-up-a-push-mirror-from-gitlab-to-aws-codecommit) feature from GitLab. It requires [CodeCommit HTTPS credentials](https://docs.aws.amazon.com/codecommit/latest/userguide/setting-up-gc.html#setting-up-gc-iam).
3. The **api_token** parameter is stored as pipeline variables for the prefix-sdlf-team repository. Be careful as it automatically expires and needs updating every now and then.
4. The **sdlf_\*** parameters are stored in the sdlf-team repository variables ([source](https://docs.gitlab.com/ee/ci/variables/#add-a-cicd-variable-to-a-project)) from GitLab, in order to be available for the pipelines in a secured way.

## Prerequisites:

1. A [personal access token](https://docs.gitlab.com/ee/user/profile/personal_access_tokens.html) with the following permissions:
    - api
    - read_repository, write_repository
2. [CodeCommit HTTPS credentials](https://docs.aws.amazon.com/codecommit/latest/userguide/setting-up-gc.html#setting-up-gc-iam) for the AWS user handling git mirroring to CodeCommit.
3. An IAM user (or role) with the next policy attached:
```
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
              "codecommit:*"
            ],
            "Resource": "arn:aws:codecommit:*:*:sdlf-*"
        }
    ]
}
```
4. JQ: If you're using the linux subsystem, you can install it with:
   
    - sudo apt install -y jq
    
    Otherwise, you can install it from the github page: https://stedolan.github.io/jq/download/
5. [AWS-cli](https://aws.amazon.com/cli/)
6. SED: If you're using the linux subsystem, you can install it with:
   
   - sudo apt install -y sed
    
   or if you're using MacOS:    
   
    - brew install gnu-sed

project private, repos privates

## Setup before deploy

1. Go to the thirdparty-scms/gitlab directory
2. Modify the file parameters.json according to your GitLab company policies and configuration:
   
   - **gitlab_host**: The URL of the GitLab instance. `https://` is assumed.
   - **group**: The name of the GitLab group where SDLF repositories will be created. User namespaces cannot be used.
   - **api_token**: API tokens are substitute passwords for a user account which you can use for scripts and integrating tools to avoid putting your real password into configuration files. (more)[https://docs.gitlab.com/ee/user/profile/personal_access_tokens.html]
   - **repository_prefix**: The prefix of the repositories for the SDLF project
   - **sldf_aws_access_key_id**: The AWS access key ID for signing programmatic requests. Example: AKIAIOSFODNN7EXAMPLE. 
   - **sdlf_aws_secret_access_key**: The AWS secret access key for signing programmatic requests. Example: wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY
   - **sdlf_session_token**: (Optional) The AWS session token for signing programmatic requests. Note: Only use this if you have an external rotation mechanism)
   - **sdlf_role_to_assume**: (Optional) The Amazon Resource Name (ARN) of the role to assume. If a role ARN is specified the access and secret keys configured in the endpoint will be used to generate temporary session credentials, scoped to the specified role, and used be used by the pipeline.
   - **sldf_aws_codecommit_username**: The AWS CodeCommit HTTPS username. Example: sdlf-at-1111111111
   - **sdlf_aws_codecommit_password**: The AWS CodeCommit HTTPS password.

3. Execute the foundations *deploy.sh* script with the option extra option **-x gitlab** from the root folder according to the SDLF installation instructions
