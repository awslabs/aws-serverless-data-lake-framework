## Alternative Source Control Systems:

By default, the SDLF relies on AWS CodeCommit as a source code layer. Occasionally, enterprise customers use a different Source Control Management system. In this section, we provide instructions and documentation to delegate version control to alternative tools.

To completely replace CodeCommit with a third-party Git repository, please follow this [AWS Blog](https://aws.amazon.com/blogs/devops/event-driven-architecture-for-using-third-party-git-repositories-as-source-for-aws-codepipeline/). To mirror your repositories to CodeCommit, use the below provider specific instructions:

- [Azure DevOps](ado/README.md)
- [BitBucket](bbucket/README.md)