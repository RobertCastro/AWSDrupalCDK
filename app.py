#!/usr/bin/env python3
import os
import aws_cdk as cdk
from aws_drupal_cdk.stacks.network_stack import NetworkStack
from aws_drupal_cdk.stacks.database_stack import DatabaseStack
from aws_drupal_cdk.stacks.service_stack import DrupalServiceStack
from aws_drupal_cdk.stacks.backup_stack import BackupStack
from aws_drupal_cdk.stacks.pipeline_stack import PipelineStack
from aws_drupal_cdk.stacks.ecr_stack import ECRStack

app = cdk.App()

# Configurar el entorno
env = cdk.Environment(
    account=os.getenv('CDK_DEFAULT_ACCOUNT'),
    region=os.getenv('CDK_DEFAULT_REGION')
)

# 1. Infraestructura base
network_stack = NetworkStack(app, "AwsDrupalNetworkStack", env=env)
db_stack = DatabaseStack(app, "AwsDrupalDatabaseStack", vpc=network_stack.vpc, env=env)

# 2. ECR y construcción de imagen inicial
ecr_stack = ECRStack(app, "AwsDrupalECRStack", env=env)

# 3. Servicio y backups
service_stack = DrupalServiceStack(
    app,
    "AwsDrupalServiceStack",
    vpc=network_stack.vpc,
    database=db_stack.cluster,
    repository=ecr_stack.repository,
    env=env
)

backup_stack = BackupStack(
    app,
    "AwsDrupalBackupStack",
    database=db_stack.cluster,
    file_system=service_stack.file_system,
    env=env
)

# 4. Pipeline (opcional, solo si quieres CI/CD)
pipeline_stack = PipelineStack(
    app,
    "AwsDrupalPipelineStack",
    env=env
)

# Dependencias
db_stack.add_dependency(network_stack)
service_stack.add_dependency(db_stack)
service_stack.add_dependency(ecr_stack)  # Asegura que la imagen exista
backup_stack.add_dependency(service_stack)
pipeline_stack.add_dependency(service_stack)

# Tags globales
cdk.Tags.of(app).add("Project", "AWSDrupalCDK")
cdk.Tags.of(app).add("Environment", "Production")

app.synth()