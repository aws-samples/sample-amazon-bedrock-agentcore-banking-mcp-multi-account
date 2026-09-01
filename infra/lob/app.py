#!/usr/bin/env python3
"""LOB CDK App — deployed once per LOB account with context parameters.

Usage:
  cdk deploy --all --profile retail-banking -c lob_name=retail-banking
  cdk deploy --all --profile transaction-banking -c lob_name=transaction-banking
  cdk deploy --all --profile lending-wealth -c lob_name=lending-wealth -c enable_kb=true
"""
import os
import aws_cdk as cdk
from stacks.data_stack import LobDataStack
from stacks.iam_stack import LobIamStack
from stacks.knowledge_base_stack import KnowledgeBaseStack

app = cdk.App()
lob_name = app.node.try_get_context("lob_name")
if not lob_name:
    raise ValueError("Context 'lob_name' is required: -c lob_name=retail-banking")

enable_kb = str(app.node.try_get_context("enable_kb") or "false").lower() == "true"
stack_prefix = f"LobInfra-{lob_name}"

env = cdk.Environment(
    account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
    region=os.environ.get("CDK_DEFAULT_REGION", "us-east-1"),
)

data = LobDataStack(app, f"{stack_prefix}-Data", env=env)
iam_stack = LobIamStack(app, f"{stack_prefix}-IAM", env=env)

if enable_kb:
    kb = KnowledgeBaseStack(app, f"{stack_prefix}-KnowledgeBase", env=env)

app.synth()
