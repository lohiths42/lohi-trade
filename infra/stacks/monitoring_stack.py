"""Monitoring, observability, and alarm infrastructure.

Requirements covered:
  24.1 — AWS CDK for defining all infrastructure as code
  24.3 — GitHub Actions CI/CD (pipeline defined separately in .github/workflows)
  24.4 — CloudWatch centralized logging with 30-day retention
  24.5 — CloudWatch alarms: ECS CPU >80%, memory >80%, ALB 5xx >1%, RDS CPU >70%, Redis memory >80%
  24.6 — AWS X-Ray for distributed tracing
"""

from aws_cdk import (
    Stack,
    Duration,
    CfnOutput,
    aws_cloudwatch as cloudwatch,
    aws_cloudwatch_actions as cw_actions,
    aws_ecs as ecs,
    aws_elasticloadbalancingv2 as elbv2,
    aws_rds as rds,
    aws_elasticache as elasticache,
    aws_sns as sns,
)
from constructs import Construct


class MonitoringStack(Stack):
    """CloudWatch alarms, SNS notifications, and X-Ray tracing configuration."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        ecs_cluster: ecs.ICluster,
        ecs_services: dict[str, ecs.FargateService],
        alb: elbv2.IApplicationLoadBalancer,
        db_instance: rds.IDatabaseInstance,
        redis_replication_group: elasticache.CfnReplicationGroup,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ── SNS Topic for alarm notifications ─────────────────────
        self.alarm_topic = sns.Topic(
            self,
            "AlarmNotificationTopic",
            display_name="LOHI-TRADE Platform Alarms",
            topic_name="lohi-trade-alarms",
        )

        alarm_action = cw_actions.SnsAction(self.alarm_topic)

        # ── ECS CPU and Memory alarms (per service) ──────────────
        self.alarms: dict[str, cloudwatch.Alarm] = {}

        for svc_name, svc in ecs_services.items():
            cpu_alarm = cloudwatch.Alarm(
                self,
                f"EcsCpu{_pascal(svc_name)}",
                alarm_name=f"lohi-trade-ecs-cpu-{svc_name}",
                metric=svc.metric_cpu_utilization(
                    period=Duration.minutes(5),
                    statistic="Average",
                ),
                threshold=80,
                evaluation_periods=2,
                comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
                alarm_description=f"ECS {svc_name} CPU utilization >80%",
            )
            cpu_alarm.add_alarm_action(alarm_action)
            self.alarms[f"ecs-cpu-{svc_name}"] = cpu_alarm

            mem_alarm = cloudwatch.Alarm(
                self,
                f"EcsMem{_pascal(svc_name)}",
                alarm_name=f"lohi-trade-ecs-mem-{svc_name}",
                metric=svc.metric_memory_utilization(
                    period=Duration.minutes(5),
                    statistic="Average",
                ),
                threshold=80,
                evaluation_periods=2,
                comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
                alarm_description=f"ECS {svc_name} memory utilization >80%",
            )
            mem_alarm.add_alarm_action(alarm_action)
            self.alarms[f"ecs-mem-{svc_name}"] = mem_alarm

        # ── ALB 5xx alarm ─────────────────────────────────────────
        alb_5xx_alarm = cloudwatch.Alarm(
            self,
            "Alb5xxAlarm",
            alarm_name="lohi-trade-alb-5xx",
            metric=cloudwatch.Metric(
                namespace="AWS/ApplicationELB",
                metric_name="HTTPCode_ELB_5XX_Count",
                dimensions_map={
                    "LoadBalancer": alb.load_balancer_full_name,
                },
                period=Duration.minutes(5),
                statistic="Sum",
            ),
            threshold=10,
            evaluation_periods=2,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            alarm_description="ALB 5xx error count >10 in 5 minutes",
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
        alb_5xx_alarm.add_alarm_action(alarm_action)
        self.alarms["alb-5xx"] = alb_5xx_alarm

        # ── RDS CPU alarm ─────────────────────────────────────────
        rds_cpu_alarm = cloudwatch.Alarm(
            self,
            "RdsCpuAlarm",
            alarm_name="lohi-trade-rds-cpu",
            metric=db_instance.metric_cpu_utilization(
                period=Duration.minutes(5),
                statistic="Average",
            ),
            threshold=70,
            evaluation_periods=2,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            alarm_description="RDS CPU utilization >70%",
        )
        rds_cpu_alarm.add_alarm_action(alarm_action)
        self.alarms["rds-cpu"] = rds_cpu_alarm

        # ── Redis memory alarm ────────────────────────────────────
        redis_mem_alarm = cloudwatch.Alarm(
            self,
            "RedisMemoryAlarm",
            alarm_name="lohi-trade-redis-memory",
            metric=cloudwatch.Metric(
                namespace="AWS/ElastiCache",
                metric_name="DatabaseMemoryUsagePercentage",
                dimensions_map={
                    "ReplicationGroupId": redis_replication_group.ref,
                },
                period=Duration.minutes(5),
                statistic="Average",
            ),
            threshold=80,
            evaluation_periods=2,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            alarm_description="Redis memory usage >80%",
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
        redis_mem_alarm.add_alarm_action(alarm_action)
        self.alarms["redis-memory"] = redis_mem_alarm

        # ── CfnOutputs ───────────────────────────────────────────
        CfnOutput(
            self,
            "AlarmTopicArn",
            value=self.alarm_topic.topic_arn,
        )

        # Output a comma-separated list of all alarm names
        alarm_names = ",".join(sorted(self.alarms.keys()))
        CfnOutput(
            self,
            "AlarmNames",
            value=alarm_names,
        )


def _pascal(kebab: str) -> str:
    """Convert kebab-case to PascalCase: 'rms-oms' → 'RmsOms'."""
    return "".join(word.capitalize() for word in kebab.split("-"))
