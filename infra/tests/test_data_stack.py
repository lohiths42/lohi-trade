"""Tests for Data layer stack — validates RDS, ElastiCache, S3, Secrets Manager.

Covers requirements:
  23.1 — RDS PostgreSQL (db.t4g.medium) as primary operational database
  23.2 — RDS Multi-AZ deployment for high availability
  23.3 — Automated RDS backups with 7-day retention and point-in-time recovery
  23.4 — S3 for historical market data in Parquet format
  23.5 — S3 for KYC documents with SSE-S3 encryption
  23.6 — S3 lifecycle: transition >90 day data to Infrequent Access
  23.7 — AWS Secrets Manager for all sensitive credentials
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import aws_cdk as cdk
from aws_cdk.assertions import Template, Match

from stacks.vpc_stack import VpcStack
from stacks.data_stack import DataStack


def _get_template() -> Template:
    app = cdk.App()
    vpc_stack = VpcStack(app, "TestVpc")
    data_stack = DataStack(
        app,
        "TestData",
        vpc=vpc_stack.vpc,
        ecs_sg=vpc_stack.ecs_sg,
        redis_sg=vpc_stack.redis_sg,
        rds_sg=vpc_stack.rds_sg,
    )
    return Template.from_stack(data_stack)


# ── RDS PostgreSQL ────────────────────────────────────────────────


class TestRdsPostgres:
    """Verify RDS PostgreSQL instance configuration."""

    def test_rds_instance_exists(self):
        template = _get_template()
        template.resource_count_is("AWS::RDS::DBInstance", 1)

    def test_rds_engine_postgres(self):
        template = _get_template()
        template.has_resource_properties(
            "AWS::RDS::DBInstance",
            {"Engine": "postgres"},
        )

    def test_rds_instance_class(self):
        template = _get_template()
        template.has_resource_properties(
            "AWS::RDS::DBInstance",
            {"DBInstanceClass": "db.t4g.medium"},
        )

    def test_rds_multi_az(self):
        template = _get_template()
        template.has_resource_properties(
            "AWS::RDS::DBInstance",
            {"MultiAZ": True},
        )

    def test_rds_backup_retention_7_days(self):
        template = _get_template()
        template.has_resource_properties(
            "AWS::RDS::DBInstance",
            {"BackupRetentionPeriod": 7},
        )

    def test_rds_storage_encrypted(self):
        template = _get_template()
        template.has_resource_properties(
            "AWS::RDS::DBInstance",
            {"StorageEncrypted": True},
        )

    def test_rds_deletion_protection(self):
        template = _get_template()
        template.has_resource_properties(
            "AWS::RDS::DBInstance",
            {"DeletionProtection": True},
        )

    def test_rds_database_name(self):
        template = _get_template()
        template.has_resource_properties(
            "AWS::RDS::DBInstance",
            {"DBName": "lohitrade"},
        )


# ── ElastiCache Redis ─────────────────────────────────────────────


class TestElastiCacheRedis:
    """Verify ElastiCache Redis replication group configuration."""

    def test_redis_replication_group_exists(self):
        template = _get_template()
        template.resource_count_is("AWS::ElastiCache::ReplicationGroup", 1)

    def test_redis_node_type(self):
        template = _get_template()
        template.has_resource_properties(
            "AWS::ElastiCache::ReplicationGroup",
            {"CacheNodeType": "cache.t4g.micro"},
        )

    def test_redis_two_cache_clusters(self):
        """1 primary + 1 replica = 2 cache clusters."""
        template = _get_template()
        template.has_resource_properties(
            "AWS::ElastiCache::ReplicationGroup",
            {"NumCacheClusters": 2},
        )

    def test_redis_automatic_failover(self):
        template = _get_template()
        template.has_resource_properties(
            "AWS::ElastiCache::ReplicationGroup",
            {"AutomaticFailoverEnabled": True},
        )

    def test_redis_encryption_at_rest(self):
        template = _get_template()
        template.has_resource_properties(
            "AWS::ElastiCache::ReplicationGroup",
            {"AtRestEncryptionEnabled": True},
        )

    def test_redis_encryption_in_transit(self):
        template = _get_template()
        template.has_resource_properties(
            "AWS::ElastiCache::ReplicationGroup",
            {"TransitEncryptionEnabled": True},
        )

    def test_redis_subnet_group_exists(self):
        template = _get_template()
        template.resource_count_is("AWS::ElastiCache::SubnetGroup", 1)


# ── S3 Buckets ────────────────────────────────────────────────────


class TestS3Buckets:
    """Verify S3 bucket configuration for historical data, KYC docs, exports."""

    def test_three_s3_buckets_created(self):
        template = _get_template()
        template.resource_count_is("AWS::S3::Bucket", 3)

    def test_all_buckets_block_public_access(self):
        template = _get_template()
        resources = template.to_json()["Resources"]
        buckets = [
            r for r in resources.values()
            if r.get("Type") == "AWS::S3::Bucket"
        ]
        for bucket in buckets:
            pba = bucket["Properties"].get("PublicAccessBlockConfiguration", {})
            assert pba.get("BlockPublicAcls") is True
            assert pba.get("BlockPublicPolicy") is True
            assert pba.get("IgnorePublicAcls") is True
            assert pba.get("RestrictPublicBuckets") is True

    def test_historical_data_bucket_lifecycle_rule(self):
        """Historical data transitions to IA after 90 days."""
        template = _get_template()
        resources = template.to_json()["Resources"]
        buckets_with_lifecycle = [
            r for r in resources.values()
            if r.get("Type") == "AWS::S3::Bucket"
            and r.get("Properties", {}).get("LifecycleConfiguration")
        ]
        assert len(buckets_with_lifecycle) >= 1, "Expected at least 1 bucket with lifecycle rules"
        lifecycle_config = buckets_with_lifecycle[0]["Properties"]["LifecycleConfiguration"]
        rules = lifecycle_config.get("Rules", [])
        ia_transitions = [
            t for rule in rules
            for t in rule.get("Transitions", [])
            if t.get("StorageClass") == "STANDARD_IA"
            and t.get("TransitionInDays") == 90
        ]
        assert len(ia_transitions) >= 1, "Expected transition to STANDARD_IA after 90 days"

    def test_all_buckets_encrypted(self):
        """All buckets use SSE-S3 encryption."""
        template = _get_template()
        resources = template.to_json()["Resources"]
        buckets = [
            r for r in resources.values()
            if r.get("Type") == "AWS::S3::Bucket"
        ]
        for bucket in buckets:
            enc = bucket["Properties"].get("BucketEncryption", {})
            rules = enc.get("ServerSideEncryptionConfiguration", [])
            assert len(rules) > 0, "Expected SSE configuration on all buckets"


# ── Secrets Manager ───────────────────────────────────────────────


class TestSecretsManager:
    """Verify Secrets Manager secrets for credentials."""

    def test_three_secrets_created(self):
        """1 auto-generated by RDS + 2 explicit = 3 total."""
        template = _get_template()
        template.resource_count_is("AWS::SecretsManager::Secret", 3)

    def test_db_credentials_secret(self):
        """RDS auto-generates a secret for master user credentials."""
        template = _get_template()
        resources = template.to_json()["Resources"]
        secrets_with_gen = [
            r for r in resources.values()
            if r.get("Type") == "AWS::SecretsManager::Secret"
            and "GenerateSecretString" in r.get("Properties", {})
        ]
        assert len(secrets_with_gen) >= 1, "Expected at least one auto-generated credentials secret"

    def test_redis_auth_secret(self):
        template = _get_template()
        template.has_resource_properties(
            "AWS::SecretsManager::Secret",
            {"Description": "LOHI-TRADE ElastiCache Redis auth token"},
        )

    def test_api_keys_secret(self):
        template = _get_template()
        template.has_resource_properties(
            "AWS::SecretsManager::Secret",
            {"Description": "LOHI-TRADE external API keys (broker, LLM, payment)"},
        )


# ── Outputs ───────────────────────────────────────────────────────


class TestOutputs:
    """Verify stack exports key resource identifiers."""

    def test_rds_endpoint_output(self):
        template = _get_template()
        template.has_output("RdsEndpoint", {})

    def test_redis_endpoint_output(self):
        template = _get_template()
        template.has_output("RedisEndpoint", {})

    def test_historical_data_bucket_output(self):
        template = _get_template()
        template.has_output("HistoricalDataBucketName", {})

    def test_kyc_documents_bucket_output(self):
        template = _get_template()
        template.has_output("KycDocumentsBucketName", {})

    def test_exports_bucket_output(self):
        template = _get_template()
        template.has_output("ExportsBucketName", {})

    def test_db_credentials_secret_arn_output(self):
        template = _get_template()
        template.has_output("DbCredentialsSecretArn", {})

    def test_redis_auth_secret_arn_output(self):
        template = _get_template()
        template.has_output("RedisAuthSecretArn", {})

    def test_api_keys_secret_arn_output(self):
        template = _get_template()
        template.has_output("ApiKeysSecretArn", {})
