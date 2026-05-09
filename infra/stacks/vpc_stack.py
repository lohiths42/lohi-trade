"""VPC, networking, and security groups for LOHI-TRADE platform.

Requirements covered:
  22.4 — VPC with public subnets (ALB) and private subnets (ECS tasks, databases)
  22.5 — NAT Gateway for outbound internet from private subnets
  22.7 — Security groups: ALB HTTPS-only, ECS from ALB only, Redis from ECS only
"""

from aws_cdk import (
    Stack,
    aws_ec2 as ec2,
    CfnOutput,
)
from constructs import Construct


class VpcStack(Stack):
    """Defines the VPC, subnets, NAT Gateway, and security groups."""

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ── VPC with 2 AZs, public + private subnets ──────────────
        self.vpc = ec2.Vpc(
            self,
            "LoHiTradeVpc",
            ip_addresses=ec2.IpAddresses.cidr("10.0.0.0/16"),
            max_azs=2,
            nat_gateways=1,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="Public",
                    subnet_type=ec2.SubnetType.PUBLIC,
                    cidr_mask=24,
                ),
                ec2.SubnetConfiguration(
                    name="Private",
                    subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
                    cidr_mask=24,
                ),
            ],
        )

        # ── Security Group: ALB — accepts HTTPS (443) only ────────
        self.alb_sg = ec2.SecurityGroup(
            self,
            "AlbSecurityGroup",
            vpc=self.vpc,
            description="ALB — accepts inbound HTTPS (443) only",
            allow_all_outbound=False,
        )
        self.alb_sg.add_ingress_rule(
            peer=ec2.Peer.any_ipv4(),
            connection=ec2.Port.tcp(443),
            description="Allow HTTPS from internet",
        )

        # ── Security Group: ECS — accepts traffic from ALB only ───
        self.ecs_sg = ec2.SecurityGroup(
            self,
            "EcsSecurityGroup",
            vpc=self.vpc,
            description="ECS tasks — accepts traffic from ALB only",
            allow_all_outbound=True,
        )
        self.ecs_sg.add_ingress_rule(
            peer=self.alb_sg,
            connection=ec2.Port.tcp(8000),
            description="Allow traffic from ALB on app port",
        )

        # ── Security Group: Redis — accepts traffic from ECS only ─
        self.redis_sg = ec2.SecurityGroup(
            self,
            "RedisSecurityGroup",
            vpc=self.vpc,
            description="ElastiCache Redis — accepts traffic from ECS only",
            allow_all_outbound=False,
        )
        self.redis_sg.add_ingress_rule(
            peer=self.ecs_sg,
            connection=ec2.Port.tcp(6379),
            description="Allow Redis traffic from ECS tasks",
        )

        # ── Security Group: RDS — accepts traffic from ECS only ───
        self.rds_sg = ec2.SecurityGroup(
            self,
            "RdsSecurityGroup",
            vpc=self.vpc,
            description="RDS PostgreSQL — accepts traffic from ECS only",
            allow_all_outbound=False,
        )
        self.rds_sg.add_ingress_rule(
            peer=self.ecs_sg,
            connection=ec2.Port.tcp(5432),
            description="Allow PostgreSQL traffic from ECS tasks",
        )

        # ALB needs to reach ECS (outbound on 8000)
        self.alb_sg.add_egress_rule(
            peer=self.ecs_sg,
            connection=ec2.Port.tcp(8000),
            description="Allow ALB to forward to ECS tasks",
        )

        # ── Outputs ───────────────────────────────────────────────
        CfnOutput(self, "VpcId", value=self.vpc.vpc_id)
        CfnOutput(self, "AlbSecurityGroupId", value=self.alb_sg.security_group_id)
        CfnOutput(self, "EcsSecurityGroupId", value=self.ecs_sg.security_group_id)
        CfnOutput(self, "RedisSecurityGroupId", value=self.redis_sg.security_group_id)
        CfnOutput(self, "RdsSecurityGroupId", value=self.rds_sg.security_group_id)
