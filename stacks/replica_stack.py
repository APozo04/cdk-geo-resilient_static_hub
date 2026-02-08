from aws_cdk import (
    Stack,
    aws_s3 as s3,
    aws_iam as iam
)
from constructs import Construct

class ReplicaStack(Stack):
    """
    Provisioning of the failover infrastructure in the secondary region.
    This bucket serves as the destination for S3 Cross-Region Replication (CRR).
    """
    def __init__(self, scope: Construct, construct_id: str, config, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Deterministic naming for Cross-Stack referencing
        replica_bucket_name = f"portfolio-replica-{config.name}-{self.account}"

        self.replica_bucket = s3.Bucket(self, "ReplicaBucket",
            bucket_name=replica_bucket_name,
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            versioned=True, # Required for S3 Replication logic
            removal_policy=config.removal_policy,
            auto_delete_objects=config.auto_delete_objects
        )

        self.replica_bucket.add_to_resource_policy(iam.PolicyStatement(
            sid="AllowCloudFrontServicePrincipalReadOnly",
            effect=iam.Effect.ALLOW,
            principals=[iam.ServicePrincipal("cloudfront.amazonaws.com")],
            actions=["s3:GetObject"],
            resources=[self.replica_bucket.arn_for_objects("*")],
            conditions={
                "StringEquals": {
                    "AWS:SourceAccount": self.account
                },
                "ArnLike": {
                    "AWS:SourceArn": f"arn:aws:cloudfront::{self.account}:distribution/*"
                }
            }
        ))