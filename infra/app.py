#!/usr/bin/env python3
"""LOHI-TRADE Platform — AWS CDK App Entry Point."""

import aws_cdk as cdk
from stacks.cdn_stack import CdnStack
from stacks.data_stack import DataStack
from stacks.ecs_stack import EcsStack
from stacks.monitoring_stack import MonitoringStack
from stacks.vpc_stack import VpcStack

app = cdk.App()

env = cdk.Environment(
    account=app.node.try_get_context("account") or None,
    region=app.node.try_get_context("region") or "ap-south-1",
)

vpc_stack = VpcStack(app, "LoHiTradeVpc", env=env)

ecs_stack = EcsStack(
    app,
    "LoHiTradeEcs",
    vpc=vpc_stack.vpc,
    alb_sg=vpc_stack.alb_sg,
    ecs_sg=vpc_stack.ecs_sg,
    env=env,
)
ecs_stack.add_dependency(vpc_stack)

data_stack = DataStack(
    app,
    "LoHiTradeData",
    vpc=vpc_stack.vpc,
    ecs_sg=vpc_stack.ecs_sg,
    redis_sg=vpc_stack.redis_sg,
    rds_sg=vpc_stack.rds_sg,
    env=env,
)
data_stack.add_dependency(vpc_stack)

domain_name = app.node.try_get_context("domain_name") or "lohitrade.in"

cdn_stack = CdnStack(
    app,
    "LoHiTradeCdn",
    alb=ecs_stack.alb,
    domain_name=domain_name,
    env=env,
)
cdn_stack.add_dependency(ecs_stack)

monitoring_stack = MonitoringStack(
    app,
    "LoHiTradeMonitoring",
    ecs_cluster=ecs_stack.cluster,
    ecs_services=ecs_stack.services,
    alb=ecs_stack.alb,
    db_instance=data_stack.db_instance,
    redis_replication_group=data_stack.redis_replication_group,
    env=env,
)
monitoring_stack.add_dependency(ecs_stack)
monitoring_stack.add_dependency(data_stack)

app.synth()
