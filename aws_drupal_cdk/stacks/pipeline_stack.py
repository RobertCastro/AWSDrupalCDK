# aws_drupal_cdk/stacks/pipeline_stack.py
from aws_cdk import (
    Stack,
    Stage,
    CfnOutput,
    pipelines,
    aws_codebuild as codebuild,
    aws_codepipeline as codepipeline,
    aws_ecs_patterns as ecs_patterns,
    aws_iam as iam,
    aws_secretsmanager as secretsmanager,
    SecretValue,
    Duration,
    Environment,
    Fn
)
from constructs import Construct
from aws_drupal_cdk.stacks.network_stack import NetworkStack
from aws_drupal_cdk.stacks.database_stack import DatabaseStack
from aws_drupal_cdk.stacks.service_stack import DrupalServiceStack

class DrupalStage(Stage):
    def __init__(self, scope: Construct, construct_id: str, **kwargs):
        super().__init__(scope, construct_id, **kwargs)
        
        # Crear los stacks para la etapa
        network_stack = NetworkStack(self, "Network")
        
        database_stack = DatabaseStack(self, "Database",
            vpc=network_stack.vpc
        )
        
        # Guardar el service_stack como atributo para poder acceder a él desde fuera
        self.service_stack = DrupalServiceStack(self, "Service", 
            vpc=network_stack.vpc,
            database=database_stack.cluster
        )

class PipelineStack(Stack):
    def __init__(self, scope: Construct, 
                 construct_id: str, 
                 service: ecs_patterns.ApplicationLoadBalancedFargateService,
                 **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Role para CodeBuild con permisos necesarios
        codebuild_role = iam.Role(
            self, "CodeBuildRole",
            assumed_by=iam.ServicePrincipal("codebuild.amazonaws.com")
        )

        codebuild_role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name("AWSCodeBuildAdminAccess")
        )
        
        # Agregar políticas adicionales necesarias
        codebuild_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "ecr:GetAuthorizationToken",
                    "ecr:BatchCheckLayerAvailability",
                    "ecr:GetDownloadUrlForLayer",
                    "ecr:GetRepositoryPolicy",
                    "ecr:DescribeRepositories",
                    "ecr:ListImages",
                    "ecr:DescribeImages",
                    "ecr:BatchGetImage",
                    "ecr:PutImage"
                ],
                resources=["*"]
            )
        )

        # Pipeline mejorado con soporte para Docker
        pipeline = pipelines.CodePipeline(
            self, "DrupalPipeline",
            pipeline_name="DrupalPipeline",
            docker_enabled_for_self_mutation=True,
            docker_enabled_for_synth=True,
            synth=pipelines.ShellStep(
                "Synth",
                input=pipelines.CodePipelineSource.git_hub(
                    "RobertCastro/AWSDrupalCDK",  # Reemplazar con tu repositorio
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
                                "python": "3.12",
                                "nodejs": "20"
                            }
                        }
                    }
                })
            )
        )

        # Crear etapas de desarrollo y producción
        deploy_dev = DrupalStage(
            self, "Dev",
            env=kwargs.get("env")
        )

        deploy_prod = DrupalStage(
            self, "Prod",
            env=kwargs.get("env")
        )

        # Agregar etapa de desarrollo con pruebas
        pipeline.add_stage(deploy_dev,
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
                        'sleep 60',  # Asegúrate de que el servicio esté activo antes de probar
                        'curl -Ssf $SERVICE_URL/health',
                        'pytest tests/integration/'
                    ],
                    env={
                        "SERVICE_URL": Fn.import_value("AwsDrupalPipelineStack-ServiceEndpoint")  # Nombre exportado
                    }
                )
            ]
        )

        # Agregar etapa de producción con aprobación manual
        pipeline.add_stage(deploy_prod,
            post=[
                pipelines.ShellStep(
                    "TestService",
                    commands=[
                        'curl -Ssf $SERVICE_URL/health',
                        'echo "Integration tests passed!"'
                    ],
                    env={
                        "SERVICE_URL": Fn.import_value("AwsDrupalPipelineStack-ServiceEndpoint")
                    }
                )
            ]
        )

        # Outputs útiles
        CfnOutput(
            self, "PipelineConsoleUrl",
            value=f"https://{Stack.of(self).region}.console.aws.amazon.com/codesuite/codepipeline/pipelines/DrupalPipeline/view?region={Stack.of(self).region}",
            description="URL de la consola del Pipeline"
        )
