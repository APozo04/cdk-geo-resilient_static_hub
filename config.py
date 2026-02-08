import os
from typing import Optional
from dotenv import load_dotenv
from aws_cdk import RemovalPolicy

# Load environment variables from a .env file
load_dotenv()

class EnvConfig:
    """
    Stores environment-specific configuration for the CDK stacks.
    """
    def __init__(
        self, 
        env_name: str, 
        account: str, 
        region: str, 
        failover_region: str, 
        domain: Optional[str], 
        ssm_prefix: str, 
        shared_secret: str,
        github_username: Optional[str] = None,
        github_repository: Optional[str] = None,
        github_connection_arn: Optional[str] = None
    ):
        self.name = env_name
        self.account = account
        self.region = region
        self.failover_region = failover_region
        self.domain_name = domain 
        self.ssm_prefix = ssm_prefix
        self.shared_secret = shared_secret

        # GitHub Configuration
        self.github_username = github_username
        self.github_repository = github_repository
        self.github_connection_arn = github_connection_arn

        # Data Lifecycle Policy:
        # In 'prod', we retain resources and disable auto-delete to prevent data loss.
        # In other environments, we clean up to save costs.
        if env_name == 'prod':
            self.removal_policy = RemovalPolicy.RETAIN
            self.auto_delete_objects = False
        else:
            self.removal_policy = RemovalPolicy.DESTROY
            self.auto_delete_objects = True

def get_required_env(key: str) -> str:
    """
    Retrieves a required environment variable or raises a RuntimeError if missing.
    """
    value = os.getenv(key)
    if not value:
        raise RuntimeError(f"❌ MISSING CONFIG: Required environment variable '{key}' not found in .env")
    return value

def get_config(scope) -> EnvConfig:
    """
    Factory function to generate the EnvConfig object based on CDK context.
    Usage: cdk deploy -c env=prod
    """
    # Default to 'dev' environment if no context is provided
    env_name = scope.node.try_get_context("env") or "dev"
    prefix = env_name.upper()

    print(f"🔍 Initializing CDK Infrastructure for environment: {prefix}")

    # Load Mandatory Variables
    account = get_required_env(f"{prefix}_ACCOUNT")
    region = get_required_env(f"{prefix}_REGION")
    failover_region = get_required_env(f"{prefix}_FAILOVER_REGION")
    ssm_prefix = get_required_env(f"{prefix}_SSM_PREFIX")
    
    # Global Secret for CloudFront-to-Lambda authentication
    shared_secret = get_required_env("SHARED_SECRET")

    # Load Optional Variables
    domain = os.getenv(f"{prefix}_DOMAIN_NAME")

    github_user = os.getenv("GITHUB_USERNAME")
    github_repo = os.getenv("GITHUB_REPOSITORY")
    github_conn = os.getenv("GITHUB_CONNECTION_ARN")

    return EnvConfig(
        env_name=env_name,
        account=account,
        region=region,
        failover_region=failover_region,
        domain=domain,
        ssm_prefix=ssm_prefix,
        shared_secret=shared_secret,
        github_username=github_user,
        github_repository=github_repo,
        github_connection_arn=github_conn
    )