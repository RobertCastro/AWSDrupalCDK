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
    aws_ecr_assets as ecr_assets,
    Duration,
    RemovalPolicy,
    CfnOutput,
    SecretValue,
    Fn
)
from constructs import Construct
from aws_cdk.aws_ecr_assets import DockerImageAsset, Platform

class DrupalServiceStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        vpc: ec2.IVpc,
        database: rds.IDatabaseCluster,
        domain_name: str = None,
        certificate_arn: str = None,
        **kwargs
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # --- ECS Cluster ---
        self.cluster = ecs.Cluster(
            self, "DrupalCluster",
            vpc=vpc,
            container_insights=True
        )

        # --- Security Group para EFS ---
        efs_security_group = ec2.SecurityGroup(
            self, "EFSSecurityGroup",
            vpc=vpc,
            description="Security group for Drupal EFS",
            allow_all_outbound=True
        )

        # --- EFS ---
        self.file_system = efs.FileSystem(
            self, "DrupalFiles",
            vpc=vpc,
            lifecycle_policy=efs.LifecyclePolicy.AFTER_14_DAYS,
            performance_mode=efs.PerformanceMode.GENERAL_PURPOSE,
            encrypted=True,
            removal_policy=RemovalPolicy.RETAIN,
            enable_automatic_backups=True,
            security_group=efs_security_group
        )

        # --- Redis (ElastiCache) ---
        cache_security_group = ec2.SecurityGroup(
            self, "RedisSecurityGroup",
            vpc=vpc,
            description="Security group for Redis",
            allow_all_outbound=True
        )
        cache_subnet_group = elasticache.CfnSubnetGroup(
            self, "RedisCacheSubnetGroup",
            subnet_ids=vpc.select_subnets(
                subnet_type=ec2.SubnetType.PRIVATE_WITH_NAT
            ).subnet_ids,
            description="Subnet group for Redis cache"
        )
        self.redis = elasticache.CfnReplicationGroup(
            self, "DrupalRedis",
            replication_group_description="Redis cache for Drupal",
            engine="redis",
            engine_version="6.x",
            cache_node_type="cache.t3.medium",
            num_cache_clusters=2,
            automatic_failover_enabled=True,
            auto_minor_version_upgrade=True,
            cache_subnet_group_name=cache_subnet_group.ref,
            security_group_ids=[cache_security_group.security_group_id],
            at_rest_encryption_enabled=True,
            transit_encryption_enabled=True
        )

        # --- Task Definition (Fargate) ---
        task_definition = ecs.FargateTaskDefinition(
            self, "DrupalTaskDef",
            cpu=1024,
            memory_limit_mib=2048,
            ephemeral_storage_gib=30
        )

        # Volume EFS en la Task
        task_definition.add_volume(
            name="drupal-files",
            efs_volume_configuration=ecs.EfsVolumeConfiguration(
                file_system_id=self.file_system.file_system_id,
                root_directory='/',
                transit_encryption="ENABLED"
            )
        )

        # Permisos necesarios para ECR en la Task y Execution Role
        task_definition.add_to_task_role_policy(
            iam.PolicyStatement(
                actions=[
                    "ecr:GetAuthorizationToken",
                    "ecr:BatchCheckLayerAvailability",
                    "ecr:GetDownloadUrlForLayer",
                    "ecr:BatchGetImage",
                    "ecr:PutImage"
                ],
                resources=["*"]
            )
        )
        task_definition.add_to_execution_role_policy(
            iam.PolicyStatement(
                actions=[
                    "ecr:GetAuthorizationToken",
                    "ecr:BatchCheckLayerAvailability",
                    "ecr:GetDownloadUrlForLayer",
                    "ecr:BatchGetImage",
                    "ecr:PutImage"
                ],
                resources=["*"]
            )
        )

        # --- Crear repositorio ECR propio y mutable ---
        repository = ecr.Repository(
            self, "DrupalRepository",
            repository_name="drupal-repository",
            image_tag_mutability=ecr.TagMutability.MUTABLE,  # Importante
            image_scan_on_push=True,
            removal_policy=RemovalPolicy.RETAIN,
        )

        # Regla de ciclo de vida: solo un máximo de 1 imagen
        repository.add_lifecycle_rule(
            max_image_count=1,
            rule_priority=1,
            tag_status=ecr.TagStatus.ANY
        )

        # --- Crear DockerImageAsset en el REPO anterior ---
        #   Esto forza que el CDK use tu repositorio 'drupal-repository'
        #   en lugar del cdk-hnb659fds-container-assets inmutable.
        asset = DockerImageAsset(
            self,
            "DrupalDockerAsset",
            directory="docker",
            platform=Platform.LINUX_AMD64,
            # Con "repository_name" el asset se publicará en tu repo 'drupal-repository'
            build_args={
                "DOCKER_BUILDKIT": "1",
                "BUILDKIT_INLINE_CACHE": "1"
            },
        )

        # --- Container principal de Drupal usando la imagen del asset ---
        drupal_container = task_definition.add_container(
            "drupal",
            # Aquí usamos la imagen del DockerImageAsset
            image=ecs.ContainerImage.from_docker_image_asset(asset),
            logging=ecs.LogDrivers.aws_logs(
                stream_prefix="drupal",
                mode=ecs.AwsLogDriverMode.NON_BLOCKING
            ),
            environment={
                "REDIS_HOST": self.redis.attr_primary_end_point_address,
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
                retries=3
            )
        )

        drupal_container.add_port_mappings(
            ecs.PortMapping(container_port=80)
        )

        drupal_container.add_mount_points(
            ecs.MountPoint(
                container_path="/var/www/html/web/sites/default/files",
                source_volume="drupal-files",
                read_only=False
            )
        )

        # --- Fargate Service con ALB ---
        self.service = ecs_patterns.ApplicationLoadBalancedFargateService(
            self, "DrupalService",
            cluster=self.cluster,
            task_definition=task_definition,
            desired_count=2,
            certificate=acm.Certificate.from_certificate_arn(
                self, "Certificate", certificate_arn
            ) if certificate_arn else None,
            protocol=elbv2.ApplicationProtocol.HTTPS if certificate_arn else elbv2.ApplicationProtocol.HTTP,
            public_load_balancer=True,
            assign_public_ip=False
        )

        # Permitir acceso al EFS desde la task
        efs_security_group.add_ingress_rule(
            peer=ec2.SecurityGroup.from_security_group_id(
                self,
                "TaskSecurityGroup",
                security_group_id=self.service.service.connections.security_groups[0].security_group_id
            ),
            connection=ec2.Port.tcp(2049),
            description="Allow ECS tasks to access EFS"
        )

        # Configurar health check del ALB
        self.service.target_group.configure_health_check(
            path="/health",
            healthy_http_codes="200-299",
            interval=Duration.seconds(30),
            timeout=Duration.seconds(5),
            healthy_threshold_count=2,
            unhealthy_threshold_count=3
        )

        # Auto-scaling
        scaling = self.service.service.auto_scale_task_count(
            max_capacity=6,
            min_capacity=2
        )
        scaling.scale_on_cpu_utilization(
            "CpuScaling",
            target_utilization_percent=75,
            scale_in_cooldown=Duration.seconds(300),
            scale_out_cooldown=Duration.seconds(300)
        )
        scaling.scale_on_memory_utilization(
            "MemoryScaling",
            target_utilization_percent=75,
            scale_in_cooldown=Duration.seconds(300),
            scale_out_cooldown=Duration.seconds(300)
        )

        # Alarmas
        cloudwatch.Alarm(
            self, "DrupalServiceHighCPU",
            metric=self.service.service.metric_cpu_utilization(),
            evaluation_periods=2,
            threshold=90,
            alarm_description="CPU utilization is too high"
        )
        cloudwatch.Alarm(
            self, "DrupalService5XX",
            metric=self.service.load_balancer.metric_http_code_target(
                code=elbv2.HttpCodeTarget.TARGET_5XX_COUNT
            ),
            evaluation_periods=2,
            threshold=10,
            alarm_description="Too many 5XX errors"
        )

        # DNS (opcional si tienes HostedZone)
        if domain_name:
            zone = route53.HostedZone.from_lookup(
                self, "Zone",
                domain_name=domain_name
            )
            route53.ARecord(
                self, "DrupalAliasRecord",
                zone=zone,
                target=route53.RecordTarget.from_alias(
                    targets.LoadBalancerTarget(self.service.load_balancer)
                ),
                record_name=domain_name
            )

        # Salidas
        self.service_endpoint_output = CfnOutput(
            self,
            "ServiceEndpoint",
            value=self.service.load_balancer.load_balancer_dns_name,
            description="Endpoint del servicio Drupal"
        )
        CfnOutput(
            self,
            "RedisEndpoint",
            value=self.redis.attr_primary_end_point_address,
            description="Endpoint de Redis"
        )
        CfnOutput(
            self,
            "ECRRepositoryURI",
            value=repository.repository_uri,
            description="URI del repositorio ECR"
        )
