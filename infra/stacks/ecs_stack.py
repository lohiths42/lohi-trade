"""ECS Fargate services, ALB, ECR repositories, and auto-scaling.

Requirements covered:
  22.1 — FastAPI gateway on ECS Fargate with auto-scaling (2-10 tasks)
  22.2 — Trading engine components on ECS Fargate with dedicated task definitions
  22.3 — ALB distributing traffic with health check /api/health
  24.2 — ECR repositories for all service Docker images
"""

from aws_cdk import (
    Stack,
    Duration,
    RemovalPolicy,
    CfnOutput,
    aws_ec2 as ec2,
    aws_ecs as ecs,
    aws_ecr as ecr,
    aws_iam as iam,
    aws_elasticloadbalancingv2 as elbv2,
    aws_logs as logs,
)
from constructs import Construct


# Service definitions: (name, cpu, memory_mib, container_port, desired_count)
_SERVICES = [
    ("gateway", 512, 1024, 8000, 2),
    ("soldier", 256, 512, 8001, 1),
    ("commander", 256, 512, 8002, 1),
    ("rms-oms", 256, 512, 8003, 1),
    ("market-data-collector", 256, 512, 8004, 1),
    ("verification", 256, 512, 8005, 1),
    ("chatbot", 512, 1024, 8006, 1),
]


class EcsStack(Stack):
    """ECS Fargate cluster, ALB, task definitions, services, and ECR repos."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        vpc: ec2.IVpc,
        alb_sg: ec2.ISecurityGroup,
        ecs_sg: ec2.ISecurityGroup,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ── ECS Cluster (Fargate) ─────────────────────────────────
        self.cluster = ecs.Cluster(
            self,
            "LoHiTradeCluster",
            vpc=vpc,
            container_insights_v2=ecs.ContainerInsights.ENABLED,
        )

        # ── ECR Repositories ──────────────────────────────────────
        self.ecr_repos: dict[str, ecr.Repository] = {}
        for svc_name, *_ in _SERVICES:
            repo = ecr.Repository(
                self,
                f"Ecr{_pascal(svc_name)}",
                repository_name=f"lohi-trade/{svc_name}",
                removal_policy=RemovalPolicy.RETAIN,
                image_tag_mutability=ecr.TagMutability.MUTABLE,
            )
            self.ecr_repos[svc_name] = repo

        # ── Application Load Balancer ─────────────────────────────
        self.alb = elbv2.ApplicationLoadBalancer(
            self,
            "LoHiTradeAlb",
            vpc=vpc,
            internet_facing=True,
            security_group=alb_sg,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
        )

        # ── Task execution role (shared) ──────────────────────────
        execution_role = iam.Role(
            self,
            "EcsTaskExecutionRole",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AmazonECSTaskExecutionRolePolicy"
                ),
            ],
        )
        # Allow pulling from ECR
        for repo in self.ecr_repos.values():
            repo.grant_pull(execution_role)

        # ── Task role (shared) ────────────────────────────────────
        task_role = iam.Role(
            self,
            "EcsTaskRole",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
        )

        # ── Create Fargate task definitions + services ────────────
        self.services: dict[str, ecs.FargateService] = {}
        gateway_service: ecs.FargateService | None = None

        for svc_name, cpu, mem, port, desired in _SERVICES:
            log_group = logs.LogGroup(
                self,
                f"Logs{_pascal(svc_name)}",
                log_group_name=f"/ecs/lohi-trade/{svc_name}",
                retention=logs.RetentionDays.ONE_MONTH,
                removal_policy=RemovalPolicy.DESTROY,
            )

            task_def = ecs.FargateTaskDefinition(
                self,
                f"TaskDef{_pascal(svc_name)}",
                cpu=cpu,
                memory_limit_mib=mem,
                execution_role=execution_role,
                task_role=task_role,
            )

            task_def.add_container(
                f"{svc_name}-container",
                image=ecs.ContainerImage.from_ecr_repository(
                    self.ecr_repos[svc_name], tag="latest"
                ),
                logging=ecs.LogDrivers.aws_logs(
                    stream_prefix=svc_name,
                    log_group=log_group,
                ),
                port_mappings=[
                    ecs.PortMapping(container_port=port, protocol=ecs.Protocol.TCP)
                ],
                environment={
                    "SERVICE_NAME": svc_name,
                },
            )

            fargate_svc = ecs.FargateService(
                self,
                f"Svc{_pascal(svc_name)}",
                cluster=self.cluster,
                task_definition=task_def,
                desired_count=desired,
                security_groups=[ecs_sg],
                vpc_subnets=ec2.SubnetSelection(
                    subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
                ),
                assign_public_ip=False,
            )

            self.services[svc_name] = fargate_svc

            if svc_name == "gateway":
                gateway_service = fargate_svc

        # ── ALB listener + target group (gateway only) ────────────
        target_group = elbv2.ApplicationTargetGroup(
            self,
            "GatewayTargetGroup",
            vpc=vpc,
            port=8000,
            protocol=elbv2.ApplicationProtocol.HTTP,
            target_type=elbv2.TargetType.IP,
            health_check=elbv2.HealthCheck(
                path="/api/health",
                interval=Duration.seconds(30),
                timeout=Duration.seconds(5),
                healthy_threshold_count=2,
                unhealthy_threshold_count=3,
                healthy_http_codes="200",
            ),
        )
        gateway_service.attach_to_application_target_group(target_group)

        # HTTP listener — upgraded to HTTPS with ACM certificate in task 23.4
        self.listener = self.alb.add_listener(
            "HttpListener",
            port=80,
            protocol=elbv2.ApplicationProtocol.HTTP,
            default_target_groups=[target_group],
            open=False,
        )

        # ── Auto-scaling for gateway (2-10 tasks, CPU-based) ─────
        scaling = gateway_service.auto_scale_task_count(
            min_capacity=2,
            max_capacity=10,
        )
        scaling.scale_on_cpu_utilization(
            "GatewayCpuScaling",
            target_utilization_percent=70,
            scale_in_cooldown=Duration.seconds(60),
            scale_out_cooldown=Duration.seconds(60),
        )

        # ── Outputs ───────────────────────────────────────────────
        CfnOutput(self, "ClusterArn", value=self.cluster.cluster_arn)
        CfnOutput(self, "AlbDnsName", value=self.alb.load_balancer_dns_name)
        for svc_name, repo in self.ecr_repos.items():
            CfnOutput(
                self,
                f"EcrUri{_pascal(svc_name)}",
                value=repo.repository_uri,
            )


def _pascal(kebab: str) -> str:
    """Convert kebab-case to PascalCase: 'rms-oms' → 'RmsOms'."""
    return "".join(word.capitalize() for word in kebab.split("-"))
