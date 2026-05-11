"""CDN, DNS, and TLS infrastructure: S3 static hosting, CloudFront, Route 53, ACM.

Requirements covered:
  24.7 — React web app as static site on S3 with CloudFront CDN distribution
  24.8 — Route 53 for DNS management with platform domain
  24.9 — ACM certificates for TLS on ALB and CloudFront
"""

from aws_cdk import (
    Stack,
    Duration,
    RemovalPolicy,
    CfnOutput,
    aws_s3 as s3,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
    aws_route53 as route53,
    aws_route53_targets as targets,
    aws_certificatemanager as acm,
    aws_elasticloadbalancingv2 as elbv2,
)
from constructs import Construct


class CdnStack(Stack):
    """S3 static hosting, CloudFront CDN, Route 53 DNS, and ACM TLS certificates."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        alb: elbv2.IApplicationLoadBalancer,
        domain_name: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ── S3 Bucket for React web app static hosting ────────────
        self.web_bucket = s3.Bucket(
            self,
            "WebAppBucket",
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        # ── CloudFront Origin Access Identity ─────────────────────
        oai = cloudfront.OriginAccessIdentity(
            self,
            "WebAppOAI",
            comment="OAI for LOHI-TRADE web app S3 bucket",
        )
        self.web_bucket.grant_read(oai)

        # ── Route 53 Hosted Zone ─────────────────────────────────
        self.hosted_zone = route53.HostedZone(
            self,
            "PlatformHostedZone",
            zone_name=domain_name,
        )

        # ── ACM Certificate (us-east-1) for CloudFront ───────────
        self.cloudfront_certificate = acm.Certificate(
            self,
            "CloudFrontCert",
            domain_name=domain_name,
            subject_alternative_names=[f"*.{domain_name}"],
            validation=acm.CertificateValidation.from_dns(self.hosted_zone),
            certificate_name="LoHiTrade-CloudFront-Cert",
        )

        # ── ACM Certificate (stack region) for ALB ────────────────
        self.alb_certificate = acm.Certificate(
            self,
            "AlbCert",
            domain_name=f"api.{domain_name}",
            validation=acm.CertificateValidation.from_dns(self.hosted_zone),
        )

        # ── CloudFront Distribution ───────────────────────────────
        self.distribution = cloudfront.Distribution(
            self,
            "WebAppDistribution",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_identity(
                    self.web_bucket,
                    origin_access_identity=oai,
                ),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
            ),
            domain_names=[domain_name, f"www.{domain_name}"],
            certificate=self.cloudfront_certificate,
            default_root_object="index.html",
            error_responses=[
                cloudfront.ErrorResponse(
                    http_status=403,
                    response_http_status=200,
                    response_page_path="/index.html",
                    ttl=Duration.seconds(0),
                ),
                cloudfront.ErrorResponse(
                    http_status=404,
                    response_http_status=200,
                    response_page_path="/index.html",
                    ttl=Duration.seconds(0),
                ),
            ],
        )

        # ── Route 53 A Record: CloudFront ─────────────────────────
        route53.ARecord(
            self,
            "CloudFrontARecord",
            zone=self.hosted_zone,
            target=route53.RecordTarget.from_alias(
                targets.CloudFrontTarget(self.distribution),
            ),
            record_name=domain_name,
        )

        # ── Route 53 A Record: ALB (api subdomain) ───────────────
        route53.ARecord(
            self,
            "AlbARecord",
            zone=self.hosted_zone,
            target=route53.RecordTarget.from_alias(
                targets.LoadBalancerTarget(alb),
            ),
            record_name=f"api.{domain_name}",
        )

        # ── CfnOutputs ───────────────────────────────────────────
        CfnOutput(
            self,
            "CloudFrontDistributionDomain",
            value=self.distribution.distribution_domain_name,
        )
        CfnOutput(
            self,
            "HostedZoneId",
            value=self.hosted_zone.hosted_zone_id,
        )
        CfnOutput(
            self,
            "CloudFrontCertificateArn",
            value=self.cloudfront_certificate.certificate_arn,
        )
        CfnOutput(
            self,
            "AlbCertificateArn",
            value=self.alb_certificate.certificate_arn,
        )
        CfnOutput(
            self,
            "WebAppBucketName",
            value=self.web_bucket.bucket_name,
        )
