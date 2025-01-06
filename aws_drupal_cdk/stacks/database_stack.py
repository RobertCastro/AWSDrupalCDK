# aws_drupal_cdk/stacks/database_stack.py
from aws_cdk import (
    Stack,
    aws_rds as rds,
    aws_ec2 as ec2,
    aws_secretsmanager as secretsmanager,
    Duration,
    RemovalPolicy
)
from constructs import Construct

class DatabaseStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, vpc: ec2.IVpc, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Grupo de seguridad para la base de datos
        self.db_security_group = ec2.SecurityGroup(
            self, "DBSecurityGroup",
            vpc=vpc,
            description="Security group for Drupal database"
        )

        # Secreto para credenciales
        self.database_secret = secretsmanager.Secret(
            self, "DBCredentials",
            generate_secret_string=secretsmanager.SecretStringGenerator(
                secret_string_template='{"username": "admin"}',
                exclude_punctuation=True,
                include_space=False,
                generate_string_key="password"
            )
        )

        # Cluster Aurora MySQL
        self.cluster = rds.DatabaseCluster(
            self, "DrupalDB",
            engine=rds.DatabaseClusterEngine.aurora_mysql(
                version=rds.AuroraMysqlEngineVersion.VER_2_11_2  # Corregido a VER_2_11_2
            ),
            credentials=rds.Credentials.from_secret(self.database_secret),
            instance_props=rds.InstanceProps(
                instance_type=ec2.InstanceType.of(
                    ec2.InstanceClass.T3,
                    ec2.InstanceSize.MEDIUM
                ),
                vpc_subnets=ec2.SubnetSelection(
                    subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS  # Actualizado a PRIVATE_WITH_EGRESS
                ),
                vpc=vpc,
                security_groups=[self.db_security_group]
            ),
            instances=2,
            backup=rds.BackupProps(
                retention=Duration.days(7),
                preferred_window="03:00-04:00"
            ),
            storage_encrypted=True,
            removal_policy=RemovalPolicy.RETAIN,
            deletion_protection=True,
            default_database_name="drupal"
        )