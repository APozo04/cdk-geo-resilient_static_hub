import aws_cdk as cdk
from config import get_config
from stacks.certificate_stack import CertificateStack
from stacks.replica_stack import ReplicaStack
from stacks.frontend_stack import FrontendStack
from stacks.backend_stack import BackendStack

app = cdk.App()
config = get_config(app)

# =================================================================
# 1. REPLICA STACK (Disaster Recovery Region)
# =================================================================
# Created first to receive S3 Cross-Region Replication traffic.
replica_env = cdk.Environment(account=config.account, region=config.failover_region)
replica_stack = ReplicaStack(
    app, f"PortfolioReplica-{config.name}",
    config=config, 
    env=replica_env,
    cross_region_references=True
)

# =================================================================
# 2. CERTIFICATE STACK (Global - us-east-1)
# =================================================================
# ACM Certificates for CloudFront must be created in us-east-1.
cert_stack = None
if config.domain_name:
    cert_env = cdk.Environment(account=config.account, region="us-east-1")
    cert_stack = CertificateStack(
        app, f"PortfolioCert-{config.name}",
        config=config, 
        env=cert_env, 
        cross_region_references=True
    )

# =================================================================
# 3. BACKEND STACK (Primary Region)
# =================================================================
# Deploys the DynamoDB table and the Visitor Counter Lambda.
main_env = cdk.Environment(account=config.account, region=config.region)
backend_stack = BackendStack(
    app, f"PortfolioBackend-{config.name}",
    config=config, 
    env=main_env
)

# =================================================================
# 4. FRONTEND STACK (Primary Region)
# =================================================================
# Deploys S3 buckets and CloudFront. 
# It bridges the backend via Function URLs and the certificate via ACM.
frontend_stack = FrontendStack(
    app, f"PortfolioFrontend-{config.name}",
    config=config,
    certificate=cert_stack.certificate if cert_stack else None,
    backend_fn_url=backend_stack.fn_url,
    replica_bucket=replica_stack.replica_bucket,
    env=main_env,
    cross_region_references=True
)

if config.github_username and config.github_repository and config.github_connection_arn:
    from stacks.pipeline_stack import PipelineStack
    
    pipeline_stack = PipelineStack(
        app, f"PortfolioPipeline-{config.name}",
        config=config,
        source_bucket=frontend_stack.source_bucket,
        distribution=frontend_stack.distribution,
        env=main_env
    )
    pipeline_stack.add_dependency(frontend_stack)
else:
    print("⏭️ Skipping PipelineStack: GitHub configuration is incomplete in .env")

# =================================================================
# DEPLOYMENT DEPENDENCIES
# =================================================================

frontend_stack.add_dependency(cert_stack)
frontend_stack.add_dependency(backend_stack)
frontend_stack.add_dependency(replica_stack)

app.synth()