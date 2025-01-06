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
    Duration
)
from constructs import Construct

class DrupalStage(Stage):
    def __init__(self, scope: Construct, construct_id: str, **kwargs):
        super().__init__(scope, construct_id, **kwargs)
        
        # Aquí puedes recrear los stacks necesarios para cada etapa
        # network_stack = NetworkStack(self, "Network")
        # database_stack = DatabaseStack(self, "Database", vpc=network_stack.vpc)
        # service_stack = DrupalServiceStack(self, "Service", 
        #     vpc=network_stack.vpc,
        #     database=database_stack.cluster
        # )

class PipelineStack(Stack):
    def __init__(self, scope: Construct, 
                 construct_id: str, 
                 service: ecs_patterns.ApplicationLoadBalancedFargateService,
                 **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Crear un secreto para el token de GitHub si no existe
        github_token = secretsmanager.Secret(
            self, "GitHubToken",
            description="Token for GitHub access",
            generate_secret_string=secretsmanager.SecretStringGenerator(
                password_length=100,
                exclude_characters='/@"'
            )
        )

        # Role para CodeBuild con permisos necesarios
        codebuild_role = iam.Role(
            self, "CodeBuildRole",
            assumed_by=iam.ServicePrincipal("codebuild.amazonaws.com"),
            description="Role for CodeBuild projects in Drupal pipeline"
        )

        # Agregar políticas necesarias al rol
        codebuild_role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name("AWSCodeBuildAdminAccess")
        )

        # Pipeline mejorado
        pipeline = pipelines.CodePipeline(
            self, "DrupalPipeline",
            pipeline_name="DrupalPipeline",
            docker_enabled_for_self_mutation=True,  # Importante para build de Docker
            docker_enabled_for_synth=True,
            synth=pipelines.ShellStep(
                "Synth",
                input=pipelines.CodePipelineSource.git_hub(
                    "RobertCastro/AWSDrupalCDK",  # Reemplazar con tu repositorio
                    "main",
                    authentication=SecretValue.secrets_manager("github-token"),
                    trigger=pipelines.GitHubTrigger('PUSH')  # Trigger en cada push
                ),
                commands=[
                    "pip install -r requirements.txt",
                    "pip install -r requirements-dev.txt",
                    "npm install -g aws-cdk",
                    "pytest",  # Ejecutar pruebas unitarias
                    "cdk synth"
                ],
                primary_output_directory="cdk.out"
            ),
            code_build_defaults=pipelines.CodeBuildOptions(
                role=codebuild_role,
                build_environment=codebuild.BuildEnvironment(
                    privileged=True,  # Necesario para builds de Docker
                    build_image=codebuild.LinuxBuildImage.STANDARD_5_0
                ),
                timeout=Duration.minutes(60)
            )
        )

        # Agregar etapas de desarrollo y producción
        deploy_dev = DrupalStage(
            self, "Dev",
            env=kwargs.get("env")  # Usar el mismo env que el stack principal
        )

        deploy_prod = DrupalStage(
            self, "Prod",
            env=kwargs.get("env")
        )

        # Agregar etapas al pipeline con pruebas
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
                        'sleep 60',  # Esperar a que el servicio esté disponible
                        'curl -Ssf ${SERVICE_URL}',  # Verificar que el servicio responde
                        'pytest tests/integration/'  # Ejecutar pruebas de integración
                    ],
                    env={
                        "SERVICE_URL": service.load_balancer.load_balancer_dns_name
                    }
                )
            ]
        )

        # Agregar etapa de producción con aprobación manual
        pipeline.add_stage(deploy_prod,
            pre=[
                pipelines.ManualApproval("PromoteToProd")
            ],
            post=[
                pipelines.ShellStep(
                    "SmokeTest",
                    commands=[
                        'echo "Running smoke tests in production..."',
                        'curl -Ssf ${SERVICE_URL}',
                        'pytest tests/smoke/'
                    ],
                    env={
                        "SERVICE_URL": service.load_balancer.load_balancer_dns_name
                    }
                )
            ]
        )

        # Outputs
        CfnOutput(
            self, "PipelineConsoleUrl",
            value=f"https://{self.region}.console.aws.amazon.com/codesuite/codepipeline/pipelines/{pipeline.pipeline.pipeline_name}/view?region={self.region}",
            description="URL de la consola del Pipeline"
        )