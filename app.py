#!/usr/bin/env python3
import os
import aws_cdk as cdk
from aws_drupal_cdk.stacks.network_stack import NetworkStack
from aws_drupal_cdk.stacks.database_stack import DatabaseStack
from aws_drupal_cdk.stacks.service_stack import DrupalServiceStack
from aws_drupal_cdk.stacks.backup_stack import BackupStack
from aws_drupal_cdk.stacks.pipeline_stack import PipelineStack

app = cdk.App()

# Configurar el entorno
env = cdk.Environment(
    account=os.getenv('CDK_DEFAULT_ACCOUNT'),
    region=os.getenv('CDK_DEFAULT_REGION')
)

# Crear stacks
network_stack = NetworkStack(app, "AwsDrupalNetworkStack",
    env=env
)

db_stack = DatabaseStack(app, "AwsDrupalDatabaseStack",
    vpc=network_stack.vpc,
    env=env
)

service_stack = DrupalServiceStack(app, "AwsDrupalServiceStack",
    vpc=network_stack.vpc,
    database=db_stack.cluster,
    env=env
)

backup_stack = BackupStack(app, "AwsDrupalBackupStack",
    database=db_stack.cluster,
    file_system=service_stack.file_system,
    env=env
)

pipeline_stack = PipelineStack(app, "AwsDrupalPipelineStack",
    service=service_stack.service,
    env=env
)

# Tags globales para todos los stacks
cdk.Tags.of(app).add("Project", "AWSDrupalCDK")
cdk.Tags.of(app).add("Environment", "Production")

app.synth()