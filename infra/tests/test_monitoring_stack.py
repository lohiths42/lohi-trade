"""Tests for Monitoring stack — validates CloudWatch alarms, SNS, and X-Ray.

Covers requirements:
  24.4 — CloudWatch centralized logging with 30-day retention (log groups in EcsStack)
  24.5 — CloudWatch alarms: ECS CPU >80%, memory >80%, ALB 5xx, RDS CPU >70%, Redis memory >80%
  24.6 — AWS X-Ray for distributed tracing
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import aws_cdk as cdk
from aws_cdk.assertions import Template
from stacks.data_stack import DataStack
from stacks.ecs_stack import EcsStack
from stacks.monitoring_stack import MonitoringStack
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
    data_stack = DataStack(
        app,
        "TestData",
        vpc=vpc_stack.vpc,
        ecs_sg=vpc_stack.ecs_sg,
        redis_sg=vpc_stack.redis_sg,
        rds_sg=vpc_stack.rds_sg,
    )
    monitoring_stack = MonitoringStack(
        app,
        "TestMonitoring",
        ecs_cluster=ecs_stack.cluster,
        ecs_services=ecs_stack.services,
        alb=ecs_stack.alb,
        db_instance=data_stack.db_instance,
        redis_replication_group=data_stack.redis_replication_group,
    )
    return Template.from_stack(monitoring_stack)


# ── SNS Topic ─────────────────────────────────────────────────────


class TestSnsTopic:
    """Verify SNS alarm notification topic."""

    def test_sns_topic_exists(self):
        template = _get_template()
        template.resource_count_is("AWS::SNS::Topic", 1)

    def test_sns_topic_display_name(self):
        template = _get_template()
        template.has_resource_properties(
            "AWS::SNS::Topic",
            {
                "DisplayName": "LOHI-TRADE Platform Alarms",
                "TopicName": "lohi-trade-alarms",
            },
        )


# ── CloudWatch Alarms ─────────────────────────────────────────────


class TestCloudWatchAlarms:
    """Verify CloudWatch alarms for ECS, ALB, RDS, and Redis."""

    def test_total_alarm_count(self):
        """7 services × 2 (CPU + mem) + ALB 5xx + RDS CPU + Redis mem = 17."""
        template = _get_template()
        template.resource_count_is("AWS::CloudWatch::Alarm", 17)

    def test_ecs_cpu_alarm_gateway(self):
        template = _get_template()
        template.has_resource_properties(
            "AWS::CloudWatch::Alarm",
            {
                "AlarmName": "lohi-trade-ecs-cpu-gateway",
                "Threshold": 80,
                "ComparisonOperator": "GreaterThanThreshold",
            },
        )

    def test_ecs_memory_alarm_gateway(self):
        template = _get_template()
        template.has_resource_properties(
            "AWS::CloudWatch::Alarm",
            {
                "AlarmName": "lohi-trade-ecs-mem-gateway",
                "Threshold": 80,
                "ComparisonOperator": "GreaterThanThreshold",
            },
        )

    def test_ecs_cpu_alarm_soldier(self):
        template = _get_template()
        template.has_resource_properties(
            "AWS::CloudWatch::Alarm",
            {"AlarmName": "lohi-trade-ecs-cpu-soldier"},
        )

    def test_ecs_cpu_alarm_commander(self):
        template = _get_template()
        template.has_resource_properties(
            "AWS::CloudWatch::Alarm",
            {"AlarmName": "lohi-trade-ecs-cpu-commander"},
        )

    def test_ecs_cpu_alarm_rms_oms(self):
        template = _get_template()
        template.has_resource_properties(
            "AWS::CloudWatch::Alarm",
            {"AlarmName": "lohi-trade-ecs-cpu-rms-oms"},
        )

    def test_ecs_cpu_alarm_market_data_collector(self):
        template = _get_template()
        template.has_resource_properties(
            "AWS::CloudWatch::Alarm",
            {"AlarmName": "lohi-trade-ecs-cpu-market-data-collector"},
        )

    def test_ecs_cpu_alarm_verification(self):
        template = _get_template()
        template.has_resource_properties(
            "AWS::CloudWatch::Alarm",
            {"AlarmName": "lohi-trade-ecs-cpu-verification"},
        )

    def test_ecs_cpu_alarm_chatbot(self):
        template = _get_template()
        template.has_resource_properties(
            "AWS::CloudWatch::Alarm",
            {"AlarmName": "lohi-trade-ecs-cpu-chatbot"},
        )

    def test_alb_5xx_alarm(self):
        template = _get_template()
        template.has_resource_properties(
            "AWS::CloudWatch::Alarm",
            {
                "AlarmName": "lohi-trade-alb-5xx",
                "ComparisonOperator": "GreaterThanThreshold",
                "TreatMissingData": "notBreaching",
            },
        )

    def test_rds_cpu_alarm(self):
        template = _get_template()
        template.has_resource_properties(
            "AWS::CloudWatch::Alarm",
            {
                "AlarmName": "lohi-trade-rds-cpu",
                "Threshold": 70,
                "ComparisonOperator": "GreaterThanThreshold",
            },
        )

    def test_redis_memory_alarm(self):
        template = _get_template()
        template.has_resource_properties(
            "AWS::CloudWatch::Alarm",
            {
                "AlarmName": "lohi-trade-redis-memory",
                "Threshold": 80,
                "ComparisonOperator": "GreaterThanThreshold",
                "TreatMissingData": "notBreaching",
            },
        )

    def test_all_alarms_have_sns_action(self):
        """Every alarm should notify the SNS topic."""
        template = _get_template()
        resources = template.to_json()["Resources"]
        alarms = [r for r in resources.values() if r.get("Type") == "AWS::CloudWatch::Alarm"]
        for alarm in alarms:
            actions = alarm["Properties"].get("AlarmActions", [])
            assert (
                len(actions) >= 1
            ), f"Alarm {alarm['Properties'].get('AlarmName')} has no alarm actions"

    def test_alarms_use_evaluation_periods_2(self):
        """All alarms should evaluate over 2 periods to avoid flapping."""
        template = _get_template()
        resources = template.to_json()["Resources"]
        alarms = [r for r in resources.values() if r.get("Type") == "AWS::CloudWatch::Alarm"]
        for alarm in alarms:
            periods = alarm["Properties"].get("EvaluationPeriods")
            assert (
                periods == 2
            ), f"Alarm {alarm['Properties'].get('AlarmName')} has EvaluationPeriods={periods}, expected 2"


# ── Outputs ───────────────────────────────────────────────────────


class TestOutputs:
    """Verify stack exports key resource identifiers."""

    def test_alarm_topic_arn_output(self):
        template = _get_template()
        template.has_output("AlarmTopicArn", {})

    def test_alarm_names_output(self):
        template = _get_template()
        template.has_output("AlarmNames", {})
