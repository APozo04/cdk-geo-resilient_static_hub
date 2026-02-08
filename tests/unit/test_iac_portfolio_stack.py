import aws_cdk as core
import aws_cdk.assertions as assertions

from stacks.frontend_stack import IacPortfolioStack

# example tests. To run these tests, uncomment this file along with the example
# resource in iac_portfolio/iac_portfolio_stack.py
def test_sqs_queue_created():
    app = core.App()
    stack = IacPortfolioStack(app, "iac-portfolio")
    template = assertions.Template.from_stack(stack)

#     template.has_resource_properties("AWS::SQS::Queue", {
#         "VisibilityTimeout": 300
#     })
