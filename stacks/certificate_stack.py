import tldextract
from aws_cdk import (
    Stack,
    aws_certificatemanager as acm,
    aws_route53 as route53
)
from constructs import Construct

class CertificateStack(Stack):
    """
    Handles SSL/TLS certificate creation and DNS validation.
    Note: This stack MUST be deployed in us-east-1 for CloudFront compatibility.
    """
    def __init__(self, scope: Construct, construct_id: str, config, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # 1. Extract the Root Zone (e.g., 'example.com' from 'sub.example.com')
        extracted = tldextract.extract(config.domain_name)
        zone_name = f"{extracted.domain}.{extracted.suffix}"
        
        # 2. Look up the existing Hosted Zone in Route53
        hosted_zone = route53.HostedZone.from_lookup(self, "HostedZone",
            domain_name=zone_name
        )

        # 3. Request Public Certificate with DNS Validation
        self.certificate = acm.Certificate(self, "PortfolioCert",
            domain_name=config.domain_name,
            validation=acm.CertificateValidation.from_dns(hosted_zone)
            )