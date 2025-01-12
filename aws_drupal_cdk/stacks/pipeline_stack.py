# aws_drupal_cdk/stacks/pipeline_stack.py
from aws_cdk import (
    Stack,
    Stage,
    CfnOutput,
    pipelines,
    aws_codebuild as codebuild,
    aws_codepipeline as codepipeline,
    aws_iam as iam,
    aws_secretsmanager as secretsmanager,
    SecretValue,
    Duration,
    Fn
)
from constructs import Construct

from aws_drupal_cdk.stacks.network_stack import NetworkStack
from aws_drupal_cdk.stacks.database_stack import DatabaseStack
from aws_drupal_cdk.stacks.service_stack import DrupalServiceStack

class DrupalStage(Stage):
    def __init__(self, scope: Construct, construct_id: str, **kwargs):
        super().__init__(scope, construct_id, **kwargs)

        network_stack = NetworkStack(self, "Network")
        
        database_stack = DatabaseStack(self, "Database",
            vpc=network_stack.vpc
        )

        self.service_stack = DrupalServiceStack(self, "Service", 
            vpc=network_stack.vpc,
            database=database_stack.cluster
        )

        self.service_endpoint = self.service_stack.service_endpoint_output

class PipelineStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        codebuild_role = iam.Role(
            self, "CodeBuildRole",
            assumed_by=iam.ServicePrincipal("codebuild.amazonaws.com")
        )

        codebuild_role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name("AWSCodeBuildAdminAccess")
        )

        codebuild_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "ecr:GetAuthorizationToken",
                    "ecr:BatchCheckLayerAvailability",
                    "ecr:CompleteLayerUpload",
                    "ecr:UploadLayerPart",
                    "ecr:PutImage",
                    "ecr:CreateRepository",
                    "ecr:PutLifecyclePolicy",
                    "ecr:GetRepositoryPolicy",
                    "ecr:ListImages",
                    "ecr:DescribeRepositories",
                    "ecr:BatchCheckLayerAvailability",
                    "ecr:InitiateLayerUpload",
                    "ecr:GetDownloadUrlForLayer"
                ],
                resources=["*"]
            )
        )

        pipeline = pipelines.CodePipeline(
            self, "DrupalPipeline",
            pipeline_name="DrupalPipeline",
            docker_enabled_for_self_mutation=True,
            docker_enabled_for_synth=True,
            synth=pipelines.ShellStep(
                "Synth",
                input=pipelines.CodePipelineSource.git_hub(
                    "RobertCastro/AWSDrupalCDK",
                    "main",
                    authentication=SecretValue.secrets_manager("github-token")
                ),
                commands=[
                    "pip install -r requirements.txt",
                    "pip install -r requirements-dev.txt",
                    "npm install -g aws-cdk",
                    "pytest",
                    "cdk synth"
                ],
                primary_output_directory="cdk.out"
            ),
            code_build_defaults=pipelines.CodeBuildOptions(
                build_environment=codebuild.BuildEnvironment(
                    privileged=True,
                    build_image=codebuild.LinuxBuildImage.STANDARD_7_0
                ),
                partial_build_spec=codebuild.BuildSpec.from_object({
                    "version": "0.2",
                    "phases": {
                        "install": {
                            "runtime-versions": {
                                "python": "3.11",
                                "nodejs": "20"
                            }
                        }
                    }
                })
            )
        )

        dev_stage = DrupalStage(
            self, "Dev",
            env=kwargs.get("env")
        )

        prod_stage = DrupalStage(
            self, "Prod",
            env=kwargs.get("env")
        )

        pipeline.add_stage(
            dev_stage,
            pre=[
                pipelines.ShellStep(
                    "UnitTest",
                    commands=["pytest"]
                )
            ],
            post=[
                pipelines.ShellStep(
                    "IntegrationTest",
                    commands=[
                        'echo "Running integration tests..."',
                        'sleep 280',
                        'curl -Ssf $SERVICE_URL/health',
                        'pytest tests/integration/'
                    ],
                    env_from_cfn_outputs={
                        "SERVICE_URL": dev_stage.service_endpoint
                    }
                )
            ]
        )

        pipeline.add_stage(
            prod_stage,
            post=[
                pipelines.ShellStep(
                    "TestService",
                    commands=[
                        'curl -Ssf $SERVICE_URL/health',
                        'echo "Integration tests passed!"'
                    ],
                    env_from_cfn_outputs={
                        "SERVICE_URL": prod_stage.service_endpoint
                    }
                )
            ]
        )

        CfnOutput(
            self, "PipelineConsoleUrl",
            value=f"https://{self.region}.console.aws.amazon.com/codesuite/codepipeline/pipelines/DrupalPipeline/view?region={self.region}",
            description="URL de la consola del Pipeline"
        )