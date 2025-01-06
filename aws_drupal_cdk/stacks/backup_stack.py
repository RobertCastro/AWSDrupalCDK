# aws_drupal_cdk/stacks/backup_stack.py
from aws_cdk import (
    Stack,
    aws_backup as backup,
    aws_events as events,
    aws_iam as iam,
    aws_rds as rds,
    aws_efs as efs,
    Duration,
    RemovalPolicy
)
from constructs import Construct

class BackupStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, database: rds.IDatabaseCluster, file_system: efs.IFileSystem, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Vault para backups
        vault = backup.BackupVault(
            self, "DrupalBackupVault",
            backup_vault_name="drupal-backup-vault",
            # Removemos la línea de encryption ya que ahora es por defecto
            removal_policy=RemovalPolicy.RETAIN
        )

        # Plan de backup
        plan = backup.BackupPlan(
            self, "DrupalBackupPlan",
            backup_vault=vault  # Añadimos el vault directamente aquí
        )

        # Regla para backups diarios
        plan.add_rule(
            backup.BackupPlanRule(
                completion_window=Duration.hours(2),
                start_window=Duration.hours(1),
                schedule_expression=events.Schedule.cron(
                    hour="3",
                    minute="0"
                ),
                delete_after=Duration.days(30)
            )
        )

        # Selección de recursos para backup
        plan.add_selection(
            "DrupalBackupSelection",
            resources=[
                backup.BackupResource.from_arn(database.cluster_arn),
                backup.BackupResource.from_arn(file_system.file_system_arn)
            ]
        )