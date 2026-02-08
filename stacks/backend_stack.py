from aws_cdk import (
    Stack,
    Duration,
    aws_dynamodb as dynamodb,
    aws_lambda as lambda_,
    aws_iam as iam,
)
from constructs import Construct

class BackendStack(Stack):
    """
    Deploys the serverless backend infrastructure:
    1. DynamoDB Table for visitor tracking and metrics.
    2. Lambda Function with a public Function URL secured by a shared secret.
    """
    def __init__(self, scope: Construct, construct_id: str, config, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # =================================================================
        # 1. DYNAMODB STORAGE
        # =================================================================
        # Optimized for high-concurrency atomic updates
        self.table = dynamodb.Table(self, "VisitsTable",
            partition_key=dynamodb.Attribute(name="PK", type=dynamodb.AttributeType.STRING),
            time_to_live_attribute="ExpiresAt",
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=config.removal_policy
        )

        self.table.add_global_secondary_index(
            index_name="MetricsIndex",
            partition_key=dynamodb.Attribute(name="Type", type=dynamodb.AttributeType.STRING),
            projection_type=dynamodb.ProjectionType.ALL 
        )

        # =================================================================
        # 2. VISITOR COUNTER FUNCTION
        # =================================================================
        self.visitor_counter_fn = lambda_.Function(self, "VisitorCounterFn",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="main.lambda_handler",
            code=lambda_.Code.from_asset("lambda/visitor_counter"),
            # reserved_concurrent_executions=10, # Throttle to prevent abuse
            environment={
                "TABLE_NAME": self.table.table_name,
                "AUTH_TOKEN": config.shared_secret # Security token for header verification
            }
        )
        
        # =================================================================
        # 3. LAMBDA FUNCTION URL (CORS & AUTH)
        # =================================================================
        # Logic to prevent Circular Dependency:
        # We allow the custom domain or '*'. 
        # Security is maintained via the 'X-Origin-Verify' header check in code.
        allowed_origins = ["*"]
        if config.domain_name:
            allowed_origins = [f"https://{config.domain_name}"]

        self.fn_url = self.visitor_counter_fn.add_function_url(
            auth_type=lambda_.FunctionUrlAuthType.NONE, # Secured via Logic Layer (Secret Header)
            cors=lambda_.FunctionUrlCorsOptions(
                allowed_origins=allowed_origins,
                allowed_methods=[lambda_.HttpMethod.GET],
                allowed_headers=["*"],
                max_age=Duration.days(1)
            )
        )

        # =================================================================
        # 4. PERMISSIONS & LEAST PRIVILEGE
        # =================================================================
        # Grant standard Read/Write access
        self.table.grant_read_write_data(self.visitor_counter_fn)