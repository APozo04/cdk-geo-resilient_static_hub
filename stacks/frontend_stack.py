import tldextract
from typing import Any, Optional
from aws_cdk import (
    Stack,
    CfnOutput,
    aws_s3 as s3,
    aws_iam as iam,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
    aws_route53 as route53,
    aws_route53_targets as targets,
    Fn
)
from constructs import Construct

class FrontendStack(Stack):
    """
    Deploys the frontend infrastructure:
    1. Primary S3 bucket with Cross-Region Replication (CRR) configured.
    2. CloudFront Distribution with Origin Failover (S3) and an API behavior (Lambda).
    3. Route53 DNS records for custom domain mapping.
    """
    def __init__(
        self, 
        scope: Construct, 
        construct_id: str, 
        config: Any, 
        certificate: Any, 
        backend_fn_url: Any, 
        replica_bucket: Any,
        **kwargs
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)


        # =================================================================
        # 2. SOURCE S3 BUCKET (Primary Storage)
        # =================================================================
        source_bucket_name = f"portfolio-source-{config.name}-{self.account}"
        manual_source_arn = f"arn:aws:s3:::{source_bucket_name}"

        self.source_bucket = s3.Bucket(self, "SourceBucket",
            bucket_name=source_bucket_name,
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            versioned=True,  # Mandatory for Replication
            removal_policy=config.removal_policy,
            auto_delete_objects=config.auto_delete_objects
        )

        # =================================================================
        # 3. S3 CROSS-REGION REPLICATION (IAM & Config)
        # =================================================================
        # Define the IAM Role for S3 to assume during replication
        replication_role = iam.Role(self, "S3ReplicationRole",
            assumed_by=iam.ServicePrincipal("s3.amazonaws.com").with_conditions({
                "StringEquals": {
                    "aws:SourceAccount": self.account,
                    "aws:SourceArn": manual_source_arn
                }
            })
        )

        replication_role.add_to_policy(iam.PolicyStatement(
            actions=["s3:GetReplicationConfiguration", "s3:ListBucket"],
            resources=[self.source_bucket.bucket_arn]
        ))
        replication_role.add_to_policy(iam.PolicyStatement(
            actions=["s3:GetObjectVersionForReplication", "s3:GetObjectVersionAcl", "s3:GetObjectVersionTagging"],
            resources=[self.source_bucket.arn_for_objects("*")]
        ))
        replication_role.add_to_policy(iam.PolicyStatement(
            actions=["s3:ReplicateObject", "s3:ReplicateDelete", "s3:ReplicateTags"],
            resources=[f"arn:aws:s3:::{replica_bucket.bucket_name}/*"]
        ))

        # Apply the L1 replication configuration to the source bucket
        cfn_source_bucket = self.source_bucket.node.default_child
        cfn_source_bucket.replication_configuration = s3.CfnBucket.ReplicationConfigurationProperty(
            role=replication_role.role_arn,
            rules=[
                s3.CfnBucket.ReplicationRuleProperty(
                    destination=s3.CfnBucket.ReplicationDestinationProperty(
                        bucket=f"arn:aws:s3:::{replica_bucket.bucket_name}"
                    ),
                    status="Enabled",
                    priority=1,
                    delete_marker_replication=s3.CfnBucket.DeleteMarkerReplicationProperty(status="Disabled"),
                    filter=s3.CfnBucket.ReplicationRuleFilterProperty(prefix="")
                )
            ]
        )

        # =================================================================
        # 4. CLOUDFRONT DISTRIBUTION
        # =================================================================

        # A. Origin Request Policy: Ensures Lambda receives vital viewer metadata
        api_policy = cloudfront.OriginRequestPolicy(self, "ApiHeadersPolicy",
            header_behavior=cloudfront.OriginRequestHeaderBehavior.allow_list(
                "CloudFront-Viewer-Address",
                "CloudFront-Viewer-Country",
                "CloudFront-Is-Mobile-Viewer",
                "CloudFront-Is-Tablet-Viewer",
                "User-Agent"
            ),
            cookie_behavior=cloudfront.OriginRequestCookieBehavior.none(),
            query_string_behavior=cloudfront.OriginRequestQueryStringBehavior.none()
        )

       # B. Backend Origin: Extract the domain from the Function URL Token safely
        # Logic: Split by "://" and take the second part (index 1), then split by "/" and take the first part (index 0)
        origin_domain = Fn.select(1, Fn.split("://", backend_fn_url.url))
        origin_domain = Fn.select(0, Fn.split("/", origin_domain))

        lambda_origin = origins.HttpOrigin(
            domain_name=origin_domain, 
            origin_id="VisitorCounterAPI",
            custom_headers={
                "X-Origin-Verify": config.shared_secret
            }
        )

        # C. S3 Origin Group: Implements automated failover for static assets
        imported_replica_bucket = s3.Bucket.from_bucket_name(
            self, 
            "ImportedReplicaBucket", 
            replica_bucket.bucket_name
        )

        s3_origin_group = origins.OriginGroup(
            primary_origin=origins.S3BucketOrigin.with_origin_access_control(self.source_bucket),
            fallback_origin=origins.S3BucketOrigin.with_origin_access_control(imported_replica_bucket),
            fallback_status_codes=[500, 502, 503, 504]
        )

        # D. The Global Distribution
        self.distribution = cloudfront.Distribution(self, "PortfolioDist",
            default_root_object="index.html",
            price_class=cloudfront.PriceClass.PRICE_CLASS_100,
            certificate=certificate,
            domain_names=[config.domain_name] if config.domain_name else None,
            
            # Static Content Behavior (Cached)
            default_behavior=cloudfront.BehaviorOptions(
                origin=s3_origin_group,
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                cache_policy=cloudfront.CachePolicy.CACHING_OPTIMIZED,
                compress=True
            ),
            
            # API Behavior (Dynamic - No Cache)
            additional_behaviors={
                "api/visitors": cloudfront.BehaviorOptions(
                    origin=lambda_origin,
                    viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                    cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
                    origin_request_policy=api_policy,
                    allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
                    compress=True
                )
            },
            
            error_responses=[
                cloudfront.ErrorResponse(http_status=404, response_http_status=404, response_page_path="/404.html")
            ]
        )

        # =================================================================
        # 5. DNS MANAGEMENT (Route53)
        # =================================================================
        if config.domain_name:
            extracted = tldextract.extract(config.domain_name)
            zone_name = f"{extracted.domain}.{extracted.suffix}"
            hosted_zone = route53.HostedZone.from_lookup(self, "MyZone", domain_name=zone_name)
            subdomain = extracted.subdomain if extracted.subdomain else None

            # Alias records pointing to the CloudFront Distribution
            route53.ARecord(self, "AliasRecord",
                zone=hosted_zone,
                record_name=subdomain,  # Use the subdomain if it exists, otherwise root
                target=route53.RecordTarget.from_alias(targets.CloudFrontTarget(self.distribution))
            )
            route53.AaaaRecord(self, "AliasRecordIPv6",
                zone=hosted_zone,
                record_name=subdomain,
                target=route53.RecordTarget.from_alias(targets.CloudFrontTarget(self.distribution))
            )

        # =================================================================
        # 6. OUTPUTS
        # =================================================================
        CfnOutput(self, "CloudFrontDomain", value=self.distribution.distribution_domain_name)
        CfnOutput(self, "VisitorApiEndpoint", value=f"https://{self.distribution.distribution_domain_name}/api/visitors")
        CfnOutput(self, "SourceBucketName", value=self.source_bucket.bucket_name)