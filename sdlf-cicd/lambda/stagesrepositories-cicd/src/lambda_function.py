import logging
import os

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

codecommit_endpoint_url = "https://codecommit." + os.getenv("AWS_REGION") + ".amazonaws.com"
codecommit = boto3.client("codecommit", endpoint_url=codecommit_endpoint_url)
codepipeline_endpoint_url = "https://codepipeline." + os.getenv("AWS_REGION") + ".amazonaws.com"
codepipeline = boto3.client("codepipeline", endpoint_url=codepipeline_endpoint_url)


def lambda_handler(event, context):
    try:
        sdlf_stage_repositories = []
        next_token = None
        while True:
            if next_token:
                response = codecommit.list_repositories(nextToken=next_token)
            else:
                response = codecommit.list_repositories()
            repos = response["repositories"]
            sdlf_stage_repositories.extend(
                [
                    repo["repositoryName"]
                    for repo in repos
                    if repo["repositoryName"].startswith(os.getenv("STAGES_REPOSITORIES_PREFIX"))
                ]
            )
            next_token = response.get("nextToken")
            if not next_token:
                break

        logger.info("sdlf_stage_repositories: %s", sdlf_stage_repositories)

    except Exception as e:
        message = "Function exception: " + str(e)
        codepipeline.put_job_failure_result(
            jobId=event["CodePipeline.job"]["id"],
            failureDetails={"message": message, "type": "JobFailed"},
        )
        raise

    codepipeline.put_job_success_result(
        jobId=event["CodePipeline.job"]["id"],
        outputVariables={
            "StagesRepositories": ",".join(sdlf_stage_repositories),
            "StagesRepositoriesCount": ",".join(list(map(str, range(0, len(sdlf_stage_repositories))))),
        },
    )
    return "Success"
