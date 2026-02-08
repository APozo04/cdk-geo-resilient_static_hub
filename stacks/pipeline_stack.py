from aws_cdk import (
    Stack,
    aws_codebuild as codebuild,
    aws_codepipeline as codepipeline,
    aws_codepipeline_actions as actions,
    aws_iam as iam,
)
from constructs import Construct

class PipelineStack(Stack):
    """
    Deploys the CI/CD Pipeline for the Portfolio website.
    
    This stack automates the following workflow:
    1. Source: Pulls the latest code from GitHub via CodeStar Connections.
    2. Build: Compiles the Next.js project using CodeBuild and generates a static export.
    3. Deploy: Uploads the build artifacts to the Source S3 Bucket and invalidates the CloudFront cache.
    """

    def __init__(self, scope: Construct, construct_id: str, config, source_bucket, distribution, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # =================================================================
        # 1. CODEBUILD PROJECT CONFIGURATION (BUILD ENGINE)
        # =================================================================
        # Defines the environment and commands to build the Next.js application
        build_project = codebuild.PipelineProject(self, "PortfolioBuild",
            environment=codebuild.BuildEnvironment(
                build_image=codebuild.LinuxBuildImage.AMAZON_LINUX_2_5, # Includes Node.js 20+
                privileged=True,
            ),
            # Injects the CloudFront Distribution ID into the build environment
            # This is used by the buildspec to run 'aws cloudfront create-invalidation'
            environment_variables={
                "CLOUDFRONT_ID": codebuild.BuildEnvironmentVariable(
                    value=distribution.distribution_id
                )
            },
            # Path to the build instruction file located in the GitHub repository root
            build_spec=codebuild.BuildSpec.from_source_filename("buildspec.yml")
        )

        # Grant CodeBuild permissions to clear the CloudFront cache post-deployment
        distribution_arn = f"arn:aws:cloudfront::{self.account}:distribution/{distribution.distribution_id}"
        build_project.add_to_role_policy(iam.PolicyStatement(
            actions=["cloudfront:CreateInvalidation"],
            resources=[distribution_arn]
        ))

        # =================================================================
        # 2. PIPELINE ARTIFACTS
        # =================================================================
        # Temporary storage for data passing between pipeline stages
        source_output = codepipeline.Artifact()
        build_output = codepipeline.Artifact()

        # =================================================================
        # 3. CODEPIPELINE ORCHESTRATION
        # =================================================================
        codepipeline.Pipeline(self, "PortfolioPipeline",
            pipeline_name=f"Portfolio-CI-CD-{config.name}",
            stages=[
                # STAGE 1: Download source code from GitHub
                codepipeline.StageProps(
                    stage_name="Source",
                    actions=[
                        actions.CodeStarConnectionsSourceAction(
                            action_name="GitHub_Source",
                            owner=config.github_username,
                            repo=config.github_repository,
                            output=source_output,
                            connection_arn=config.github_connection_arn,
                            branch="main" # Ensure this matches your primary GitHub branch
                        )
                    ]
                ),
                # STAGE 2: Run Next.js Build (Static Export)
                codepipeline.StageProps(
                    stage_name="Build",
                    actions=[
                        actions.CodeBuildAction(
                            action_name="NextJS_Build",
                            project=build_project,
                            input=source_output,
                            outputs=[build_output]
                        )
                    ]
                ),
                # STAGE 3: Deploy artifacts to S3
                codepipeline.StageProps(
                    stage_name="Deploy",
                    actions=[
                        actions.S3DeployAction(
                            action_name="S3_Deploy",
                            bucket=source_bucket,
                            input=build_output,
                            extract=True # Unzips the build output directly into the bucket root
                        )
                    ]
                )
            ]
        )