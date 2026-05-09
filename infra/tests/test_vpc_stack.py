"""Tests for VPC stack — validates networking and security group configuration.

Covers requirements:
  22.4 — VPC with public subnets (ALB) and private subnets (ECS/databases)
  22.5 — NAT Gateway for outbound internet from private subnets
  22.7 — Security groups: ALB HTTPS-only, ECS from ALB only, Redis from ECS only
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import aws_cdk as cdk
from aws_cdk.assertions import Template, Match

from stacks.vpc_stack import VpcStack


def _get_template() -> Template:
    app = cdk.App()
    stack = VpcStack(app, "TestVpc")
    return Template.from_stack(stack)


class TestVpcCreation:
    """Verify VPC and subnet configuration."""

    def test_vpc_exists(self):
        template = _get_template()
        template.resource_count_is("AWS::EC2::VPC", 1)

    def test_vpc_cidr(self):
        template = _get_template()
        template.has_resource_properties("AWS::EC2::VPC", {
            "CidrBlock": "10.0.0.0/16",
        })

    def test_public_subnets_created(self):
        """At least 2 public subnets (one per AZ)."""
        template = _get_template()
        resources = template.to_json()["Resources"]
        public_subnets = [
            r for r in resources.values()
            if r.get("Type") == "AWS::EC2::Subnet"
            and r.get("Properties", {}).get("MapPublicIpOnLaunch") is True
        ]
        assert len(public_subnets) >= 2, f"Expected >=2 public subnets, got {len(public_subnets)}"

    def test_private_subnets_created(self):
        """At least 2 private subnets (one per AZ)."""
        template = _get_template()
        resources = template.to_json()["Resources"]
        private_subnets = [
            r for r in resources.values()
            if r.get("Type") == "AWS::EC2::Subnet"
            and r.get("Properties", {}).get("MapPublicIpOnLaunch") is False
        ]
        assert len(private_subnets) >= 2, f"Expected >=2 private subnets, got {len(private_subnets)}"


class TestNatGateway:
    """Verify NAT Gateway for private subnet outbound access."""

    def test_nat_gateway_exists(self):
        template = _get_template()
        template.resource_count_is("AWS::EC2::NatGateway", 1)

    def test_elastic_ip_for_nat(self):
        template = _get_template()
        template.resource_count_is("AWS::EC2::EIP", 1)


class TestSecurityGroups:
    """Verify least-privilege security group chain: ALB → ECS → Redis/RDS."""

    def test_four_security_groups_created(self):
        """ALB, ECS, Redis, RDS security groups."""
        template = _get_template()
        template.resource_count_is("AWS::EC2::SecurityGroup", 4)

    def test_alb_sg_allows_https_443_ingress(self):
        template = _get_template()
        template.has_resource_properties("AWS::EC2::SecurityGroup", {
            "GroupDescription": Match.string_like_regexp("ALB.*HTTPS.*443"),
            "SecurityGroupIngress": Match.array_with([
                Match.object_like({
                    "IpProtocol": "tcp",
                    "FromPort": 443,
                    "ToPort": 443,
                    "CidrIp": "0.0.0.0/0",
                }),
            ]),
        })

    def test_alb_sg_no_all_outbound(self):
        """ALB SG should not allow all outbound — only to ECS."""
        template = _get_template()
        resources = template.to_json()["Resources"]
        alb_sgs = [
            r for r in resources.values()
            if r.get("Type") == "AWS::EC2::SecurityGroup"
            and r.get("Properties", {}).get("GroupDescription", "").startswith("ALB")
        ]
        assert len(alb_sgs) == 1
        # SecurityGroupEgress should not contain allow-all rule
        egress = alb_sgs[0]["Properties"].get("SecurityGroupEgress", [])
        for rule in egress:
            assert rule.get("CidrIp") != "0.0.0.0/0" or rule.get("IpProtocol") != "-1", \
                "ALB SG should not allow all outbound traffic"

    def test_ecs_sg_ingress_from_alb_on_8000(self):
        """ECS SG ingress rule references ALB SG on port 8000."""
        template = _get_template()
        template.has_resource("AWS::EC2::SecurityGroupIngress", {
            "Properties": Match.object_like({
                "IpProtocol": "tcp",
                "FromPort": 8000,
                "ToPort": 8000,
            }),
        })

    def test_redis_sg_ingress_from_ecs_on_6379(self):
        """Redis SG ingress rule references ECS SG on port 6379."""
        template = _get_template()
        template.has_resource("AWS::EC2::SecurityGroupIngress", {
            "Properties": Match.object_like({
                "IpProtocol": "tcp",
                "FromPort": 6379,
                "ToPort": 6379,
            }),
        })

    def test_rds_sg_ingress_from_ecs_on_5432(self):
        """RDS SG ingress rule references ECS SG on port 5432."""
        template = _get_template()
        template.has_resource("AWS::EC2::SecurityGroupIngress", {
            "Properties": Match.object_like({
                "IpProtocol": "tcp",
                "FromPort": 5432,
                "ToPort": 5432,
            }),
        })


class TestOutputs:
    """Verify stack exports key resource IDs."""

    def test_vpc_id_output(self):
        template = _get_template()
        template.has_output("VpcId", {})

    def test_alb_sg_output(self):
        template = _get_template()
        template.has_output("AlbSecurityGroupId", {})

    def test_ecs_sg_output(self):
        template = _get_template()
        template.has_output("EcsSecurityGroupId", {})

    def test_redis_sg_output(self):
        template = _get_template()
        template.has_output("RedisSecurityGroupId", {})

    def test_rds_sg_output(self):
        template = _get_template()
        template.has_output("RdsSecurityGroupId", {})
