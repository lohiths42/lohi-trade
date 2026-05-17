"""Tests for ECS Fargate stack — validates cluster, ALB, services, ECR, auto-scaling.

Covers requirements:
  22.1 — FastAPI gateway on ECS Fargate with auto-scaling (2-10 tasks)
  22.2 — Trading engine components on ECS Fargate with dedicated task definitions
  22.3 — ALB with health check /api/health
  24.2 — ECR repositories for all service Docker images
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import aws_cdk as cdk
from aws_cdk.assertions import Match, Template
from stacks.ecs_stack import EcsStack
from stacks.vpc_stack import VpcStack


def _get_template() -> Template:
    app = cdk.App()
    vpc_stack = VpcStack(app, "TestVpc")
    ecs_stack = EcsStack(
        app,
        "TestEcs",
        vpc=vpc_stack.vpc,
        alb_sg=vpc_stack.alb_sg,
        ecs_sg=vpc_stack.ecs_sg,
    )
    return Template.from_stack(ecs_stack)


# ── ECS Cluster ───────────────────────────────────────────────────


class TestEcsCluster:
    """Verify ECS cluster creation."""

    def test_cluster_exists(self):
        template = _get_template()
        template.resource_count_is("AWS::ECS::Cluster", 1)


# ── ECR Repositories ─────────────────────────────────────────────


class TestEcrRepositories:
    """Verify ECR repositories for all services."""

    def test_seven_ecr_repos_created(self):
        template = _get_template()
        template.resource_count_is("AWS::ECR::Repository", 7)

    def test_gateway_ecr_repo(self):
        template = _get_template()
        template.has_resource_properties(
            "AWS::ECR::Repository",
            {"RepositoryName": "lohi-trade/gateway"},
        )

    def test_soldier_ecr_repo(self):
        template = _get_template()
        template.has_resource_properties(
            "AWS::ECR::Repository",
            {"RepositoryName": "lohi-trade/soldier"},
        )

    def test_commander_ecr_repo(self):
        template = _get_template()
        template.has_resource_properties(
            "AWS::ECR::Repository",
            {"RepositoryName": "lohi-trade/commander"},
        )

    def test_rms_oms_ecr_repo(self):
        template = _get_template()
        template.has_resource_properties(
            "AWS::ECR::Repository",
            {"RepositoryName": "lohi-trade/rms-oms"},
        )

    def test_market_data_collector_ecr_repo(self):
        template = _get_template()
        template.has_resource_properties(
            "AWS::ECR::Repository",
            {"RepositoryName": "lohi-trade/market-data-collector"},
        )

    def test_verification_ecr_repo(self):
        template = _get_template()
        template.has_resource_properties(
            "AWS::ECR::Repository",
            {"RepositoryName": "lohi-trade/verification"},
        )

    def test_chatbot_ecr_repo(self):
        template = _get_template()
        template.has_resource_properties(
            "AWS::ECR::Repository",
            {"RepositoryName": "lohi-trade/chatbot"},
        )


# ── Task Definitions ─────────────────────────────────────────────


class TestTaskDefinitions:
    """Verify Fargate task definitions for all services."""

    def test_seven_task_definitions(self):
        template = _get_template()
        template.resource_count_is("AWS::ECS::TaskDefinition", 7)

    def test_all_task_defs_use_fargate(self):
        template = _get_template()
        resources = template.to_json()["Resources"]
        task_defs = [r for r in resources.values() if r.get("Type") == "AWS::ECS::TaskDefinition"]
        for td in task_defs:
            assert td["Properties"]["RequiresCompatibilities"] == ["FARGATE"]

    def test_gateway_task_def_cpu_memory(self):
        template = _get_template()
        template.has_resource_properties(
            "AWS::ECS::TaskDefinition",
            {"Cpu": "512", "Memory": "1024"},
        )

    def test_soldier_task_def_cpu_memory(self):
        template = _get_template()
        template.has_resource_properties(
            "AWS::ECS::TaskDefinition",
            {"Cpu": "256", "Memory": "512"},
        )


# ── Fargate Services ─────────────────────────────────────────────


class TestFargateServices:
    """Verify Fargate services for all components."""

    def test_seven_fargate_services(self):
        template = _get_template()
        template.resource_count_is("AWS::ECS::Service", 7)

    def test_gateway_desired_count_2(self):
        template = _get_template()
        resources = template.to_json()["Resources"]
        gateway_svcs = [
            r
            for r in resources.values()
            if r.get("Type") == "AWS::ECS::Service"
            and r.get("Properties", {}).get("DesiredCount") == 2
        ]
        assert len(gateway_svcs) == 1, "Expected exactly 1 service with DesiredCount=2 (gateway)"

    def test_other_services_desired_count_1(self):
        template = _get_template()
        resources = template.to_json()["Resources"]
        single_svcs = [
            r
            for r in resources.values()
            if r.get("Type") == "AWS::ECS::Service"
            and r.get("Properties", {}).get("DesiredCount") == 1
        ]
        assert (
            len(single_svcs) == 6
        ), f"Expected 6 services with DesiredCount=1, got {len(single_svcs)}"

    def test_all_services_use_fargate_launch_type(self):
        template = _get_template()
        resources = template.to_json()["Resources"]
        ecs_services = [r for r in resources.values() if r.get("Type") == "AWS::ECS::Service"]
        for svc in ecs_services:
            assert svc["Properties"]["LaunchType"] == "FARGATE"


# ── ALB ───────────────────────────────────────────────────────────


class TestAlb:
    """Verify ALB configuration and health check."""

    def test_alb_exists(self):
        template = _get_template()
        template.resource_count_is("AWS::ElasticLoadBalancingV2::LoadBalancer", 1)

    def test_alb_internet_facing(self):
        template = _get_template()
        template.has_resource_properties(
            "AWS::ElasticLoadBalancingV2::LoadBalancer",
            {"Scheme": "internet-facing"},
        )

    def test_http_listener_on_80(self):
        """HTTP listener — upgraded to HTTPS with ACM cert in task 23.4."""
        template = _get_template()
        template.has_resource_properties(
            "AWS::ElasticLoadBalancingV2::Listener",
            {"Port": 80, "Protocol": "HTTP"},
        )

    def test_target_group_health_check(self):
        template = _get_template()
        template.has_resource_properties(
            "AWS::ElasticLoadBalancingV2::TargetGroup",
            {
                "HealthCheckPath": "/api/health",
                "Port": 8000,
                "Protocol": "HTTP",
                "TargetType": "ip",
            },
        )


# ── Auto-Scaling ──────────────────────────────────────────────────


class TestAutoScaling:
    """Verify gateway auto-scaling configuration (2-10 tasks)."""

    def test_scalable_target_exists(self):
        template = _get_template()
        template.has_resource_properties(
            "AWS::ApplicationAutoScaling::ScalableTarget",
            {"MinCapacity": 2, "MaxCapacity": 10},
        )

    def test_cpu_scaling_policy_exists(self):
        template = _get_template()
        template.has_resource_properties(
            "AWS::ApplicationAutoScaling::ScalingPolicy",
            {
                "PolicyType": "TargetTrackingScaling",
                "TargetTrackingScalingPolicyConfiguration": Match.object_like(
                    {
                        "PredefinedMetricSpecification": {
                            "PredefinedMetricType": "ECSServiceAverageCPUUtilization",
                        },
                        "TargetValue": 70,
                    }
                ),
            },
        )


# ── Log Groups ────────────────────────────────────────────────────


class TestLogGroups:
    """Verify CloudWatch log groups for all services."""

    def test_seven_log_groups(self):
        template = _get_template()
        template.resource_count_is("AWS::Logs::LogGroup", 7)

    def test_gateway_log_group(self):
        template = _get_template()
        template.has_resource_properties(
            "AWS::Logs::LogGroup",
            {
                "LogGroupName": "/ecs/lohi-trade/gateway",
                "RetentionInDays": 30,
            },
        )


# ── Outputs ───────────────────────────────────────────────────────


class TestOutputs:
    """Verify stack exports key resource identifiers."""

    def test_cluster_arn_output(self):
        template = _get_template()
        template.has_output("ClusterArn", {})

    def test_alb_dns_output(self):
        template = _get_template()
        template.has_output("AlbDnsName", {})
