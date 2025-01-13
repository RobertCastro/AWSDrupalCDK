# aws_drupal_cdk/stacks/service_stack.py

from aws_cdk import (
    Stack,
    aws_ecs as ecs,
    aws_ec2 as ec2,
    aws_efs as efs,
    aws_rds as rds,
    aws_iam as iam,
    aws_ecr as ecr,
    aws_elasticache as elasticache,
    aws_certificatemanager as acm,
    aws_ecs_patterns as ecs_patterns,
    aws_cloudwatch as cloudwatch,
    aws_route53 as route53,
    aws_route53_targets as targets,
    aws_elasticloadbalancingv2 as elbv2,
    aws_logs as logs,
    Duration,
    RemovalPolicy,
    CfnOutput,
    Fn,
    Tags
)
from constructs import Construct
from typing import Optional

class DrupalServiceStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        vpc: ec2.IVpc,
        database: rds.IDatabaseCluster,
        repository: ecr.IRepository,
        domain_name: Optional[str] = None,
        certificate_arn: Optional[str] = None,
        **kwargs
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Validación inicial de parámetros
        self._validate_parameters(vpc, database, repository)

        # --- ECS Cluster ---
        self.cluster = self._create_ecs_cluster(vpc)

        # --- EFS Setup ---
        self.file_system, efs_security_group = self._create_efs(vpc)

        # --- Redis (ElastiCache) ---
        self.redis = self._create_redis_cluster(vpc)

        # --- Task Definition ---
        task_definition = self._create_task_definition(repository)
        
        # --- EFS Volume Configuration ---
        self._configure_efs_volume(task_definition)

        # --- Container Configuration ---
        container = self._create_container_definition(
            task_definition, 
            repository, 
            database,
            self.redis
        )

        # --- Fargate Service ---
        self.service = self._create_fargate_service(
            task_definition,
            certificate_arn,
            domain_name
        )

        # --- Security Group Rules ---
        self._configure_security_groups(efs_security_group)

        # --- Auto Scaling ---
        self._configure_auto_scaling()

        # --- Monitoring ---
        self._configure_monitoring()

        # --- Outputs ---
        self._create_outputs(repository)

    def _validate_parameters(self, vpc: ec2.IVpc, database: rds.IDatabaseCluster, repository: ecr.IRepository):
        """Validar los parámetros requeridos"""
        if not vpc:
            raise ValueError("VPC must be provided")
        if not database:
            raise ValueError("Database cluster must be provided")
        if not repository:
            raise ValueError("ECR repository must be provided")

        # Verificar que el repositorio existe
        if not repository.repository_name:
            raise ValueError("ECR repository name is not valid")

    def _create_ecs_cluster(self, vpc: ec2.IVpc) -> ecs.Cluster:
        """Crear el cluster ECS"""
        cluster = ecs.Cluster(
            self, "DrupalCluster",
            vpc=vpc,
            container_insights=True,
            enable_fargate_capacity_providers=True
        )
        
        Tags.of(cluster).add("Name", "drupal-cluster")
        return cluster

    def _create_efs(self, vpc: ec2.IVpc) -> tuple[efs.FileSystem, ec2.SecurityGroup]:
        """Crear el sistema de archivos EFS y su grupo de seguridad"""
        security_group = ec2.SecurityGroup(
            self, "EFSSecurityGroup",
            vpc=vpc,
            description="Security group for Drupal EFS",
            allow_all_outbound=True
        )

        file_system = efs.FileSystem(
            self, "DrupalFiles",
            vpc=vpc,
            lifecycle_policy=efs.LifecyclePolicy.AFTER_14_DAYS,
            performance_mode=efs.PerformanceMode.GENERAL_PURPOSE,
            encrypted=True,
            removal_policy=RemovalPolicy.RETAIN,
            enable_automatic_backups=True,
            security_group=security_group
        )

        return file_system, security_group

    def _create_redis_cluster(self, vpc: ec2.IVpc) -> elasticache.CfnReplicationGroup:
        """Crear el cluster de Redis"""
        security_group = ec2.SecurityGroup(
            self, "RedisSecurityGroup",
            vpc=vpc,
            description="Security group for Redis",
            allow_all_outbound=True
        )

        subnet_group = elasticache.CfnSubnetGroup(
            self, "RedisCacheSubnetGroup",
            subnet_ids=vpc.select_subnets(
                subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
            ).subnet_ids,
            description="Subnet group for Redis cache"
        )

        return elasticache.CfnReplicationGroup(
            self, "DrupalRedis",
            replication_group_description="Redis cache for Drupal",
            engine="redis",
            engine_version="7.0",
            cache_node_type="cache.t4g.medium",
            num_cache_clusters=2,
            automatic_failover_enabled=True,
            auto_minor_version_upgrade=True,
            cache_subnet_group_name=subnet_group.ref,
            security_group_ids=[security_group.security_group_id],
            at_rest_encryption_enabled=True,
            transit_encryption_enabled=True
        )

    def _create_task_definition(self, repository: ecr.IRepository) -> ecs.FargateTaskDefinition:
        """Crear la definición de tarea de Fargate"""
        task_definition = ecs.FargateTaskDefinition(
            self, "DrupalTaskDef",
            cpu=1024,
            memory_limit_mib=2048,
            ephemeral_storage_gib=30
        )

        # Añadir permisos necesarios
        self._add_task_permissions(task_definition, repository)
        
        return task_definition

    def _add_task_permissions(self, task_definition: ecs.FargateTaskDefinition, repository: ecr.IRepository):
        """Añadir los permisos necesarios a la tarea"""
        # Permisos para ECR
        task_definition.add_to_task_role_policy(
            iam.PolicyStatement(
                actions=[
                    "ecr:GetAuthorizationToken",
                    "ecr:BatchCheckLayerAvailability",
                    "ecr:GetDownloadUrlForLayer",
                    "ecr:BatchGetImage"
                ],
                resources=["*"]
            )
        )

        # Permisos de ejecución
        task_definition.add_to_execution_role_policy(
            iam.PolicyStatement(
                actions=[
                    "ecr:GetAuthorizationToken",
                    "ecr:BatchCheckLayerAvailability",
                    "ecr:GetDownloadUrlForLayer",
                    "ecr:BatchGetImage",
                    "logs:CreateLogGroup",
                    "logs:CreateLogStream",
                    "logs:PutLogEvents",
                    "secretsmanager:GetSecretValue",
                    "ssm:GetParameters",
                    "kms:Decrypt"
                ],
                resources=["*"]
            )
        )

        # Permisos específicos para el repositorio
        repository.grant_pull(task_definition.execution_role)

    def _configure_efs_volume(self, task_definition: ecs.FargateTaskDefinition):
        """Configurar el volumen EFS en la definición de tarea"""
        task_definition.add_volume(
            name="drupal-files",
            efs_volume_configuration=ecs.EfsVolumeConfiguration(
                file_system_id=self.file_system.file_system_id,
                root_directory='/',
                transit_encryption="ENABLED"
            )
        )

    def _create_container_definition(
        self, 
        task_definition: ecs.FargateTaskDefinition,
        repository: ecr.IRepository,
        database: rds.IDatabaseCluster,
        redis: elasticache.CfnReplicationGroup
    ) -> ecs.ContainerDefinition:
        """Crear la definición del contenedor"""
        # Log group con retención configurada
        log_group = logs.LogGroup(
            self, "DrupalContainerLogs",
            retention=logs.RetentionDays.ONE_MONTH,
            removal_policy=RemovalPolicy.DESTROY
        )

        container = task_definition.add_container(
            "drupal",
            image=ecs.ContainerImage.from_ecr_repository(repository, "latest"),
            logging=ecs.AwsLogDriver(
                stream_prefix="drupal",
                log_group=log_group,
                mode=ecs.AwsLogDriverMode.NON_BLOCKING
            ),
            environment={
                "REDIS_HOST": redis.attr_primary_end_point_address,
                "DB_HOST": database.cluster_endpoint.hostname,
                "DB_NAME": "drupal",
                "DRUPAL_ENV": "production",
                "PHP_MEMORY_LIMIT": "512M",
                "PHP_MAX_EXECUTION_TIME": "300",
                "PHP_POST_MAX_SIZE": "64M",
                "PHP_UPLOAD_MAX_FILESIZE": "64M",
                "PHP_MAX_INPUT_VARS": "4000"
            },
            secrets={
                "DB_USER": ecs.Secret.from_secrets_manager(database.secret, "username"),
                "DB_PASSWORD": ecs.Secret.from_secrets_manager(database.secret, "password")
            },
            health_check=ecs.HealthCheck(
                command=["CMD-SHELL", "curl -f http://localhost/health || exit 1"],
                interval=Duration.seconds(30),
                timeout=Duration.seconds(5),
                retries=3,
                start_period=Duration.seconds(90)
            )
        )

        container.add_port_mappings(
            ecs.PortMapping(container_port=80)
        )

        container.add_mount_points(
            ecs.MountPoint(
                container_path="/var/www/html/web/sites/default/files",
                source_volume="drupal-files",
                read_only=False
            )
        )

        return container

    def _create_fargate_service(
        self, 
        task_definition: ecs.FargateTaskDefinition,
        certificate_arn: Optional[str],
        domain_name: Optional[str]
    ) -> ecs_patterns.ApplicationLoadBalancedFargateService:
        """Crear el servicio Fargate con ALB"""
        service = ecs_patterns.ApplicationLoadBalancedFargateService(
            self, "DrupalService",
            cluster=self.cluster,
            task_definition=task_definition,
            desired_count=2,
            certificate=acm.Certificate.from_certificate_arn(
                self, "Certificate", certificate_arn
            ) if certificate_arn else None,
            protocol=elbv2.ApplicationProtocol.HTTPS if certificate_arn else elbv2.ApplicationProtocol.HTTP,
            public_load_balancer=True,
            assign_public_ip=False,
            deployment_controller=ecs.DeploymentController(
                type=ecs.DeploymentControllerType.ECS
            ),
            circuit_breaker=ecs.DeploymentCircuitBreaker(
                rollback=True
            )
        )

        # Configurar health check
        service.target_group.configure_health_check(
            path="/health",
            healthy_http_codes="200-299",
            interval=Duration.seconds(30),
            timeout=Duration.seconds(5),
            healthy_threshold_count=2,
            unhealthy_threshold_count=3
        )

        # Configurar DNS si se proporciona
        if domain_name:
            self._configure_dns(service, domain_name)

        return service

    def _configure_dns(
        self, 
        service: ecs_patterns.ApplicationLoadBalancedFargateService,
        domain_name: str
    ):
        """Configurar DNS para el servicio"""
        zone = route53.HostedZone.from_lookup(
            self, "Zone",
            domain_name=domain_name
        )
        route53.ARecord(
            self, "DrupalAliasRecord",
            zone=zone,
            target=route53.RecordTarget.from_alias(
                targets.LoadBalancerTarget(service.load_balancer)
            ),
            record_name=domain_name
        )

    def _configure_security_groups(self, efs_security_group: ec2.SecurityGroup):
        """Configurar reglas de grupos de seguridad"""
        efs_security_group.add_ingress_rule(
            peer=ec2.SecurityGroup.from_security_group_id(
                self,
                "TaskSecurityGroup",
                security_group_id=self.service.service.connections.security_groups[0].security_group_id
            ),
            connection=ec2.Port.tcp(2049),
            description="Allow ECS tasks to access EFS"
        )

    def _configure_auto_scaling(self):
        """Configurar auto-scaling para el servicio"""
        scaling = self.service.service.auto_scale_task_count(
            max_capacity=6,
            min_capacity=2
        )

        # Escalar basado en CPU
        scaling.scale_on_cpu_utilization(
            "CpuScaling",
            target_utilization_percent=75,
            scale_in_cooldown=Duration.seconds(300),
            scale_out_cooldown=Duration.seconds(300)
        )

        # Escalar basado en memoria
        scaling.scale_on_memory_utilization(
            "MemoryScaling",
            target_utilization_percent=75,
            scale_in_cooldown=Duration.seconds(300),
            scale_out_cooldown=Duration.seconds(300)
        )

    def _configure_monitoring(self):
        """Configurar monitoreo y alarmas"""
        # Alarma de CPU alta
        cloudwatch.Alarm(
            self, "DrupalServiceHighCPU",
            metric=self.service.service.metric_cpu_utilization(),
            evaluation_periods=2,
            threshold=90,
            alarm_description="CPU utilization is too high"
        )

        # Alarma de errores 5XX
        cloudwatch.Alarm(
            self, "DrupalService5XX",
            metric=self.service.load_balancer.metric_http_code_target(
                code=elbv2.HttpCodeTarget.TARGET_5XX_COUNT,
                period=Duration.minutes(1)
            ),
            evaluation_periods=2,
            threshold=10,
            alarm_description="Too many 5XX errors",
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD
        )

        # Alarma de latencia alta
        cloudwatch.Alarm(
            self, "DrupalServiceHighLatency",
            metric=self.service.load_balancer.metrics.target_response_time(
                period=Duration.minutes(1),
                statistic="p95"
            ),
            evaluation_periods=3,
            threshold=5,  # 5 segundos
            alarm_description="Service latency is too high",
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD
        )

        # Alarma de errores de healthcheck
        cloudwatch.Alarm(
            self, "DrupalServiceHealthCheckFailures",
            metric=self.service.target_group.metrics.unhealthy_host_count(
                period=Duration.minutes(1)
            ),
            evaluation_periods=2,
            threshold=1,
            alarm_description="Service health checks are failing",
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD
        )

    def _create_outputs(self, repository: ecr.IRepository):
        """Crear outputs del stack"""
        self.service_endpoint_output = CfnOutput(
            self,
            "ServiceEndpoint",
            value=self.service.load_balancer.load_balancer_dns_name,
            description="Drupal service endpoint"
        )

        CfnOutput(
            self,
            "RedisEndpoint",
            value=self.redis.attr_primary_end_point_address,
            description="Redis endpoint"
        )

        CfnOutput(
            self,
            "ECRRepositoryURI",
            value=repository.repository_uri,
            description="ECR repository URI"
        )

        CfnOutput(
            self,
            "TaskDefinitionArn",
            value=self.service.task_definition.task_definition_arn,
            description="Task definition ARN"
        )

        CfnOutput(
            self,
            "EFSFileSystemId",
            value=self.file_system.file_system_id,
            description="EFS file system ID"
        )

        CfnOutput(
            self,
            "LoadBalancerDNS",
            value=self.service.load_balancer.load_balancer_dns_name,
            description="Load balancer DNS name"
        )