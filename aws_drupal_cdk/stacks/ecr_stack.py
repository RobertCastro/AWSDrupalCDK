# aws_drupal_cdk/stacks/ecr_stack.py
from aws_cdk import (
    Stack,
    aws_ecr as ecr,
    aws_codebuild as codebuild,
    aws_iam as iam,
    aws_events as events,
    aws_events_targets as events_targets,
    SecretValue,
    CfnOutput,
    RemovalPolicy,
)
from constructs import Construct

class ECRStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Crear el repositorio ECR
        self.repository = ecr.Repository(
            self, "DrupalRepository",
            repository_name="drupal-repository",
            image_tag_mutability=ecr.TagMutability.MUTABLE,
            image_scan_on_push=True,
            removal_policy=RemovalPolicy.RETAIN,
        )

        # Reglas de ciclo de vida
        self.repository.add_lifecycle_rule(
            max_image_count=5,
            rule_priority=1,
            tag_status=ecr.TagStatus.TAGGED,
            tag_prefix_list=["v"]
        )

        # Crear rol para CodeBuild
        build_role = iam.Role(
            self, "CodeBuildRole",
            assumed_by=iam.ServicePrincipal("codebuild.amazonaws.com")
        )

        # Permisos necesarios
        build_role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name("AWSCodeBuildAdminAccess")
        )

        # Permisos para ECR
        build_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "ecr:GetAuthorizationToken",
                    "ecr:BatchCheckLayerAvailability",
                    "ecr:BatchGetImage",
                    "ecr:CompleteLayerUpload",
                    "ecr:CreateRepository",
                    "ecr:DescribeImages",
                    "ecr:DescribeRepositories",
                    "ecr:GetDownloadUrlForLayer",
                    "ecr:GetRepositoryPolicy",
                    "ecr:InitiateLayerUpload",
                    "ecr:ListImages",
                    "ecr:PutImage",
                    "ecr:UploadLayerPart"
                ],
                effect=iam.Effect.ALLOW,
                resources=["*"]
            )
        )

        # Permisos para Secrets Manager
        secret_arn = f"arn:aws:secretsmanager:{self.region}:{self.account}:secret:dockerhub-credentials-*"
        build_role.add_to_policy(
            iam.PolicyStatement(
                actions=["secretsmanager:GetSecretValue"],
                resources=[secret_arn]
            )
        )

        # Permisos para logs
        build_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "logs:CreateLogGroup",
                    "logs:CreateLogStream",
                    "logs:PutLogEvents"
                ],
                resources=["*"]
            )
        )

        # Dar permisos pull/push al repositorio
        self.repository.grant_pull_push(build_role)

        # Crear proyecto CodeBuild
        build = codebuild.Project(
            self, "DrupalImageBuild",
            role=build_role,
            environment=codebuild.BuildEnvironment(
                privileged=True,
                build_image=codebuild.LinuxBuildImage.STANDARD_7_0
            ),
            source=codebuild.Source.git_hub(
                owner="RobertCastro",
                repo="AWSDrupalCDK",
                branch_or_ref="main",
                webhook=True,
                webhook_filters=[
                    codebuild.FilterGroup.in_event_of(
                        codebuild.EventAction.PUSH
                    ).and_branch_is("main")
                    .and_file_path_is("docker/*")
                ]
            ),
            environment_variables={
                "ECR_REPO_URI": codebuild.BuildEnvironmentVariable(
                    value=self.repository.repository_uri
                ),
                "AWS_DEFAULT_REGION": codebuild.BuildEnvironmentVariable(
                    value=self.region
                ),
                "AWS_ACCOUNT_ID": codebuild.BuildEnvironmentVariable(
                    value=self.account
                )
            },
            build_spec=codebuild.BuildSpec.from_object({
                "version": "0.2",
                "phases": {
                    "install": {
                        "runtime-versions": {
                            "python": "3.11",
                            "nodejs": "18"
                        },
                        "commands": [
                            "apt-get update",
                            "apt-get install -y jq"
                        ]
                    },
                    "pre_build": {
                        "commands": [
                            "echo Retrieving Docker Hub credentials...",
                            "DOCKERHUB_CREDS=$(aws secretsmanager get-secret-value --secret-id dockerhub-credentials --query SecretString --output text)",
                            "export DOCKERHUB_USERNAME=$(echo $DOCKERHUB_CREDS | jq -r .username)",
                            "export DOCKERHUB_PASSWORD=$(echo $DOCKERHUB_CREDS | jq -r .password)",
                            "echo Logging in to Docker Hub...",
                            "docker login -u $DOCKERHUB_USERNAME -p $DOCKERHUB_PASSWORD",
                            "echo Logging in to Amazon ECR...",
                            "aws ecr get-login-password --region $AWS_DEFAULT_REGION | docker login --username AWS --password-stdin $ECR_REPO_URI",
                            "echo Directory contents:",
                            "ls -la"
                        ]
                    },
                    "build": {
                        "commands": [
                            "echo Build started on `date`",
                            "cd docker",
                            "docker build --build-arg COMPOSER_ALLOW_SUPERUSER=1 --build-arg DRUPAL_VERSION=10.2.4 --no-cache -t $ECR_REPO_URI:latest ."
                        ]
                    },
                    "post_build": {
                        "commands": [
                            "echo Pushing the Docker image...",
                            "docker push $ECR_REPO_URI:latest",
                            'printf \'{"ImageURI":"%s"}\' $ECR_REPO_URI:latest > imageDefinitions.json'
                        ]
                    }
                },
                "artifacts": {
                    "files": ["imageDefinitions.json"]
                }
            })
        )

        # Configuración de GitHub
        codebuild.GitHubSourceCredentials(
            self, "GitHubCredentials",
            access_token=SecretValue.secrets_manager('github-token-codebuild')
        )

        # Trigger programado semanal
        events.Rule(
            self, "WeeklyBuildRule",
            schedule=events.Schedule.cron(
                minute="0",
                hour="0",
                week_day="SUN"
            ),
            targets=[events_targets.CodeBuildProject(build)]
        )

        # Outputs
        CfnOutput(
            self, "RepositoryUri",
            value=self.repository.repository_uri,
            description="URI del repositorio ECR"
        )
        
        CfnOutput(
            self, "BuildProjectName",
            value=build.project_name,
            description="Nombre del proyecto CodeBuild"
        )