# tests/unit/test_aws_drupal_cdk_stack.py
import aws_cdk as cdk
import pytest
from aws_drupal_cdk.stacks.network_stack import NetworkStack

def test_vpc_creation():
    app = cdk.App()
    stack = NetworkStack(app, "TestStack")
    assert stack is not None