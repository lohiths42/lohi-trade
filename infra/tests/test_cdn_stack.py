"""Tests for CDN stack — validates S3, CloudFront, Route 53, and ACM configuration.

Covers requirements:
  24.7 — React web app as static site on S3 with CloudFront CDN distribution
  24.8 — Route 53 for DNS management with platform domain
  24.9 — ACM certificates for TLS on ALB and CloudFront
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import aws_cdk as cdk
from aws_cdk.assertions import Template, Match

from stacks.vpc_stack import VpcStack
from stacks.ecs_stack import EcsStack
from stacks.cdn_stack import CdnStack

TEST_DOMAIN = "lohitrade.example.com"


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
    cdn_stack = CdnStack(
        app,
        "TestCdn",
        alb=ecs_stack.alb,
        domain_name=TEST_DOMAIN,
    )
    return Template.from_stack(cdn_stack)


# ── S3 Bucket ─────────────────────────────────────────────────────


class TestS3Bucket:
    """Verify S3 bucket for React web app static hosting."""

    def test_s3_bucket_exists(self):
        template = _get_template()
        template.resource_count_is("AWS::S3::Bucket", 1)

    def test_s3_bucket_blocks_public_access(self):
        template = _get_template()
        template.has_resource_properties(
            "AWS::S3::Bucket",
            {
                "PublicAccessBlockConfiguration": {
                    "BlockPublicAcls": True,
                    "BlockPublicPolicy": True,
                    "IgnorePublicAcls": True,
                    "RestrictPublicBuckets": True,
                },
            },
        )

    def test_s3_bucket_encrypted(self):
        template = _get_template()
        template.has_resource_properties(
            "AWS::S3::Bucket",
            {
                "BucketEncryption": Match.object_like(
                    {
                        "ServerSideEncryptionConfiguration": Match.array_with(
                            [
                                Match.object_like(
                                    {
                                        "ServerSideEncryptionByDefault": {
                                            "SSEAlgorithm": "AES256",
                                        },
                                    }
                                ),
                            ]
                        ),
                    }
                ),
            },
        )


# ── CloudFront Origin Access Identity ─────────────────────────────


class TestCloudFrontOAI:
    """Verify CloudFront OAI for S3 access."""

    def test_oai_exists(self):
        template = _get_template()
        template.resource_count_is(
            "AWS::CloudFront::CloudFrontOriginAccessIdentity", 1
        )

    def test_s3_bucket_policy_grants_oai_read(self):
        template = _get_template()
        template.has_resource_properties(
            "AWS::S3::BucketPolicy",
            {
                "PolicyDocument": Match.object_like(
                    {
                        "Statement": Match.array_with(
                            [
                                Match.object_like(
                                    {
                                        "Action": Match.any_value(),
                                        "Effect": "Allow",
                                        "Principal": Match.any_value(),
                                    }
                                ),
                            ]
                        ),
                    }
                ),
            },
        )


# ── CloudFront Distribution ──────────────────────────────────────


class TestCloudFrontDistribution:
    """Verify CloudFront distribution configuration."""

    def test_distribution_exists(self):
        template = _get_template()
        template.resource_count_is("AWS::CloudFront::Distribution", 1)

    def test_distribution_default_root_object(self):
        template = _get_template()
        template.has_resource_properties(
            "AWS::CloudFront::Distribution",
            {
                "DistributionConfig": Match.object_like(
                    {"DefaultRootObject": "index.html"}
                ),
            },
        )

    def test_distribution_has_domain_aliases(self):
        template = _get_template()
        template.has_resource_properties(
            "AWS::CloudFront::Distribution",
            {
                "DistributionConfig": Match.object_like(
                    {
                        "Aliases": Match.array_with(
                            [TEST_DOMAIN, f"www.{TEST_DOMAIN}"]
                        ),
                    }
                ),
            },
        )

    def test_distribution_viewer_protocol_redirect_https(self):
        template = _get_template()
        template.has_resource_properties(
            "AWS::CloudFront::Distribution",
            {
                "DistributionConfig": Match.object_like(
                    {
                        "DefaultCacheBehavior": Match.object_like(
                            {"ViewerProtocolPolicy": "redirect-to-https"}
                        ),
                    }
                ),
            },
        )

    def test_distribution_spa_error_responses(self):
        """403 and 404 should redirect to /index.html for SPA routing."""
        template = _get_template()
        template.has_resource_properties(
            "AWS::CloudFront::Distribution",
            {
                "DistributionConfig": Match.object_like(
                    {
                        "CustomErrorResponses": Match.array_with(
                            [
                                Match.object_like(
                                    {
                                        "ErrorCode": 403,
                                        "ResponseCode": 200,
                                        "ResponsePagePath": "/index.html",
                                    }
                                ),
                                Match.object_like(
                                    {
                                        "ErrorCode": 404,
                                        "ResponseCode": 200,
                                        "ResponsePagePath": "/index.html",
                                    }
                                ),
                            ]
                        ),
                    }
                ),
            },
        )


# ── Route 53 ──────────────────────────────────────────────────────


class TestRoute53:
    """Verify Route 53 hosted zone and DNS records."""

    def test_hosted_zone_exists(self):
        template = _get_template()
        template.resource_count_is("AWS::Route53::HostedZone", 1)

    def test_hosted_zone_domain_name(self):
        template = _get_template()
        template.has_resource_properties(
            "AWS::Route53::HostedZone",
            {"Name": f"{TEST_DOMAIN}."},
        )

    def test_a_records_created(self):
        """At least 2 A records: one for CloudFront, one for ALB."""
        template = _get_template()
        resources = template.to_json()["Resources"]
        a_records = [
            r
            for r in resources.values()
            if r.get("Type") == "AWS::Route53::RecordSet"
            and r.get("Properties", {}).get("Type") == "A"
        ]
        assert len(a_records) >= 2, f"Expected >=2 A records, got {len(a_records)}"

    def test_cloudfront_a_record(self):
        """A record for root domain pointing to CloudFront."""
        template = _get_template()
        template.has_resource_properties(
            "AWS::Route53::RecordSet",
            {
                "Name": f"{TEST_DOMAIN}.",
                "Type": "A",
                "AliasTarget": Match.object_like(
                    {
                        "HostedZoneId": Match.any_value(),
                        "DNSName": Match.any_value(),
                    }
                ),
            },
        )

    def test_alb_a_record(self):
        """A record for api subdomain pointing to ALB."""
        template = _get_template()
        template.has_resource_properties(
            "AWS::Route53::RecordSet",
            {
                "Name": f"api.{TEST_DOMAIN}.",
                "Type": "A",
                "AliasTarget": Match.object_like(
                    {
                        "HostedZoneId": Match.any_value(),
                        "DNSName": Match.any_value(),
                    }
                ),
            },
        )


# ── ACM Certificates ─────────────────────────────────────────────


class TestAcmCertificates:
    """Verify ACM certificates for CloudFront and ALB."""

    def test_acm_certificates_exist(self):
        """At least 1 ACM certificate in the stack (ALB cert; CF cert is cross-region custom resource)."""
        template = _get_template()
        resources = template.to_json()["Resources"]
        acm_certs = [
            r
            for r in resources.values()
            if r.get("Type") == "AWS::CertificateManager::Certificate"
        ]
        assert len(acm_certs) >= 1, f"Expected >=1 ACM certificate, got {len(acm_certs)}"

    def test_alb_certificate_domain(self):
        template = _get_template()
        template.has_resource_properties(
            "AWS::CertificateManager::Certificate",
            {
                "DomainName": f"api.{TEST_DOMAIN}",
                "ValidationMethod": "DNS",
            },
        )


# ── Outputs ───────────────────────────────────────────────────────


class TestOutputs:
    """Verify stack exports key resource identifiers."""

    def test_cloudfront_distribution_domain_output(self):
        template = _get_template()
        template.has_output("CloudFrontDistributionDomain", {})

    def test_hosted_zone_id_output(self):
        template = _get_template()
        template.has_output("HostedZoneId", {})

    def test_cloudfront_certificate_arn_output(self):
        template = _get_template()
        template.has_output("CloudFrontCertificateArn", {})

    def test_alb_certificate_arn_output(self):
        template = _get_template()
        template.has_output("AlbCertificateArn", {})

    def test_web_app_bucket_name_output(self):
        template = _get_template()
        template.has_output("WebAppBucketName", {})
