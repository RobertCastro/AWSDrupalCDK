import aws_cdk as core
import aws_cdk.assertions as assertions

from aws_drupal_cdk.aws_drupal_cdk_stack import AwsDrupalCdkStack

# example tests. To run these tests, uncomment this file along with the example
# resource in aws_drupal_cdk/aws_drupal_cdk_stack.py
def test_sqs_queue_created():
    app = core.App()
    stack = AwsDrupalCdkStack(app, "aws-drupal-cdk")
    template = assertions.Template.from_stack(stack)

#     template.has_resource_properties("AWS::SQS::Queue", {
#         "VisibilityTimeout": 300
#     })
