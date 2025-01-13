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
    aws_ecr as ecr,
    SecretValue,
    Duration,
    Environment
)
from constructs import Construct
from typing import Optional

from .network_stack import NetworkStack
from .database_stack import DatabaseStack
from .service_stack import DrupalServiceStack
from .ecr_stack import ECRStack

class ApplicationStage(Stage):
    """Stage para el despliegue de la aplicación"""
    def __init__(
        self, 
        scope: Construct, 
        id: str,
        **kwargs
    ):
        super().__init__(scope, id, **kwargs)

        # Crear red
        network = NetworkStack(self, "Network")
        
        # Crear base de datos
        database = DatabaseStack(
            self, 
            "Database",
            vpc=network.vpc
        )

        # Crear ECR
        ecr = ECRStack(self, "ECR")

        # Crear servicio
        service = DrupalServiceStack(
            self, 
            "Service", 
            vpc=network.vpc,
            database=database.cluster,
            repository=ecr.repository
        )

        # Establecer dependencias
        database.add_dependency(network)
        service.add_dependency(database)
        service.add_dependency(ecr)

        self.service_endpoint = service.service_endpoint_output

class PipelineStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        github_owner: str,
        github_repo: str,
        github_branch: str = "main",
        **kwargs
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Obtener el token de GitHub usando el mismo secreto que ECR stack
        github_token = SecretValue.secrets_manager('github-token-codebuild')

        pipeline = pipelines.CodePipeline(
            self,
            "Pipeline",
            pipeline_name="DrupalPipeline",
            synth=pipelines.ShellStep(
                "Synth",
                input=pipelines.CodePipelineSource.git_hub(
                    f"{github_owner}/{github_repo}",
                    github_branch,
                    authentication=github_token
                ),
                commands=[
                    "npm install -g aws-cdk",
                    "pip install -r requirements.txt",
                    "pip install -r requirements-dev.txt",
                    "pytest tests/unit/",
                    "cdk synth"
                ],
                primary_output_directory="cdk.out"
            )
        )

        # Agregar stage de desarrollo
        dev = ApplicationStage(
            self,
            "Dev",
            env=kwargs.get('env')
        )

        pipeline.add_stage(dev, 
            pre=[
                pipelines.ShellStep(
                    "UnitTest",
                    commands=["pytest tests/unit/"]
                )
            ],
            post=[
                pipelines.ShellStep(
                    "IntegrationTest",
                    commands=[
                        'echo "Running integration tests..."',
                        'sleep 180',
                        'curl -Ssf $SERVICE_URL/health',
                        'pytest tests/integration/'
                    ],
                    env_from_cfn_outputs={
                        "SERVICE_URL": dev.service_endpoint
                    }
                )
            ]
        )

        # Agregar stage de producción
        prod = ApplicationStage(
            self,
            "Prod",
            env=kwargs.get('env')
        )

        pipeline.add_stage(
            prod,
            pre=[
                pipelines.ManualApprovalStep(
                    "PromoteToProd",
                    comment="¿Deseas promover los cambios a producción?"
                )
            ],
            post=[
                pipelines.ShellStep(
                    "SmokeTest",
                    commands=[
                        'echo "Running production tests..."',
                        'sleep 180',
                        'curl -Ssf $SERVICE_URL/health',
                        'pytest tests/smoke/',
                        'echo "Production deployment successful!"'
                    ],
                    env_from_cfn_outputs={
                        "SERVICE_URL": prod.service_endpoint
                    }
                )
            ]
        )