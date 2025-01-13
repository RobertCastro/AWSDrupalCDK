#!/usr/bin/env python3
import os
import aws_cdk as cdk
from aws_drupal_cdk.stacks.pipeline_stack import PipelineStack
from aws_drupal_cdk.stacks.ecr_stack import ECRStack

app = cdk.App()

# Configurar el entorno
env = cdk.Environment(
    account=os.getenv('CDK_DEFAULT_ACCOUNT'),
    region=os.getenv('CDK_DEFAULT_REGION')
)

# ECR Stack
ecr_stack = ECRStack(app, "AwsDrupalECRStack", env=env)

# Pipeline Stack
pipeline_stack = PipelineStack(
    scope=app,
    construct_id="AwsDrupalPipelineStack",
    github_owner="RobertCastro",  # Reemplaza con tu usuario de GitHub
    github_repo="AWSDrupalCDK",   # Reemplaza con el nombre de tu repositorio
    github_branch="main",         # O la rama que desees usar
    env=env
)

# Tags globales
cdk.Tags.of(app).add("Project", "AWSDrupalCDK")
cdk.Tags.of(app).add("Environment", "Production")

app.synth()