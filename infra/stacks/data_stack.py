"""Data layer infrastructure: RDS PostgreSQL, ElastiCache Redis, S3 buckets, Secrets Manager.

Requirements covered:
  23.1 — RDS PostgreSQL (db.t4g.medium) as primary operational database
  23.2 — RDS Multi-AZ deployment for high availability
  23.3 — Automated RDS backups with 7-day retention and point-in-time recovery
  23.4 — S3 for historical market data in Parquet format
  23.5 — S3 for KYC documents with SSE-S3 encryption
  23.6 — S3 lifecycle: transition >90 day data to Infrequent Access
  23.7 — AWS Secrets Manager for all sensitive credentials
"""

from aws_cdk import (
    Stack,
    Duration,
    RemovalPolicy,
    CfnOutput,
    aws_ec2 as ec2,
    aws_rds as rds,
    aws_elasticache as elasticache,
    aws_s3 as s3,
    aws_secretsmanager as secretsmanager,
    aws_iam as iam,
)
from constructs import Construct


class DataStack(Stack):
    """RDS PostgreSQL, ElastiCache Redis, S3 buckets, and Secrets Manager."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        vpc: ec2.IVpc,
        ecs_sg: ec2.ISecurityGroup,
        redis_sg: ec2.ISecurityGroup,
        rds_sg: ec2.ISecurityGroup,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        private_subnets = ec2.SubnetSelection(
            subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
        )

        # ── RDS PostgreSQL (Multi-AZ, 7-day backup, PITR) ────────
        self.db_instance = rds.DatabaseInstance(
            self,
            "LoHiTradeDb",
            engine=rds.DatabaseInstanceEngine.postgres(
                version=rds.PostgresEngineVersion.VER_16_4,
            ),
            instance_type=ec2.InstanceType.of(
                ec2.InstanceClass.T4G, ec2.InstanceSize.MEDIUM
            ),
            vpc=vpc,
            vpc_subnets=private_subnets,
            security_groups=[rds_sg],
            multi_az=True,
            allocated_storage=50,
            max_allocated_storage=200,
            database_name="lohitrade",
            backup_retention=Duration.days(7),
            deletion_protection=True,
            removal_policy=RemovalPolicy.RETAIN,
            storage_encrypted=True,
        )

        # ── ElastiCache Redis (replication group, 1 replica) ─────
        redis_subnet_group = elasticache.CfnSubnetGroup(
            self,
            "RedisSubnetGroup",
            description="Private subnets for ElastiCache Redis",
            subnet_ids=[
                subnet.subnet_id
                for subnet in vpc.select_subnets(
                    subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
                ).subnets
            ],
        )

        self.redis_replication_group = elasticache.CfnReplicationGroup(
            self,
            "LoHiTradeRedis",
            replication_group_description="LOHI-TRADE managed Redis cluster",
            engine="redis",
            cache_node_type="cache.t4g.micro",
            num_cache_clusters=2,  # 1 primary + 1 replica
            automatic_failover_enabled=True,
            cache_subnet_group_name=redis_subnet_group.ref,
            security_group_ids=[redis_sg.security_group_id],
            at_rest_encryption_enabled=True,
            transit_encryption_enabled=True,
        )


        # ── S3 Bucket: Historical Data (Parquet) ─────────────────
        self.historical_data_bucket = s3.Bucket(
            self,
            "HistoricalDataBucket",
            bucket_name=None,  # auto-generated unique name
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            removal_policy=RemovalPolicy.RETAIN,
            lifecycle_rules=[
                s3.LifecycleRule(
                    id="TransitionToIA",
                    transitions=[
                        s3.Transition(
                            storage_class=s3.StorageClass.INFREQUENT_ACCESS,
                            transition_after=Duration.days(90),
                        ),
                    ],
                ),
            ],
        )

        # ── S3 Bucket: KYC Documents (SSE-S3 encryption) ────────
        self.kyc_documents_bucket = s3.Bucket(
            self,
            "KycDocumentsBucket",
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            removal_policy=RemovalPolicy.RETAIN,
            enforce_ssl=True,
        )

        # ── S3 Bucket: Exports ───────────────────────────────────
        self.exports_bucket = s3.Bucket(
            self,
            "ExportsBucket",
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            removal_policy=RemovalPolicy.DESTROY,
        )

        # ── Secrets Manager ──────────────────────────────────────
        # Note: RDS DatabaseInstance auto-creates a secret for DB credentials.
        # We reference it via self.db_instance.secret.

        self.redis_auth_secret = secretsmanager.Secret(
            self,
            "RedisAuthToken",
            description="LOHI-TRADE ElastiCache Redis auth token",
            generate_secret_string=secretsmanager.SecretStringGenerator(
                exclude_punctuation=True,
                password_length=32,
            ),
        )

        self.api_keys_secret = secretsmanager.Secret(
            self,
            "ApiKeys",
            description="LOHI-TRADE external API keys (broker, LLM, payment)",
        )

        # ── Grant ECS task role read access to secrets ───────────
        # ECS task role is passed via ecs_sg context; grant via resource policy
        # The ECS task role will be granted read access by the ECS stack
        # Here we export ARNs so ECS stack can grant access
        self.secret_arns = [
            self.db_instance.secret.secret_arn,
            self.redis_auth_secret.secret_arn,
            self.api_keys_secret.secret_arn,
        ]

        # ── CfnOutputs ──────────────────────────────────────────
        CfnOutput(
            self,
            "RdsEndpoint",
            value=self.db_instance.db_instance_endpoint_address,
        )
        CfnOutput(
            self,
            "RedisEndpoint",
            value=self.redis_replication_group.attr_primary_end_point_address,
        )
        CfnOutput(
            self,
            "HistoricalDataBucketName",
            value=self.historical_data_bucket.bucket_name,
        )
        CfnOutput(
            self,
            "KycDocumentsBucketName",
            value=self.kyc_documents_bucket.bucket_name,
        )
        CfnOutput(
            self,
            "ExportsBucketName",
            value=self.exports_bucket.bucket_name,
        )
        CfnOutput(
            self,
            "DbCredentialsSecretArn",
            value=self.db_instance.secret.secret_arn,
        )
        CfnOutput(
            self,
            "RedisAuthSecretArn",
            value=self.redis_auth_secret.secret_arn,
        )
        CfnOutput(
            self,
            "ApiKeysSecretArn",
            value=self.api_keys_secret.secret_arn,
        )
