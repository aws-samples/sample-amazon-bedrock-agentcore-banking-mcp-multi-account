#!/usr/bin/env python3
import os
import json
import aws_cdk as cdk
from stacks.foundation_stack import FoundationStack
from stacks.guardrail_stack import GuardrailStack
from stacks.gateway_stack import GatewayStack
from stacks.webapp_stack import WebAppStack
from stacks.cloudfront_stack import CloudFrontStack

app = cdk.App()
prefix = app.node.try_get_context("project_prefix") or "LOBFederation"
env = cdk.Environment(
    account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
    region=os.environ.get("CDK_DEFAULT_REGION", "us-east-1"),
)

# Load Okta config
okta_config_path = os.path.join(os.path.dirname(__file__), "..", "..", "okta_config.json")
with open(okta_config_path) as f:
    okta_config = json.load(f)

foundation = FoundationStack(app, f"{prefix}-Foundation", env=env)

guardrail = GuardrailStack(app, f"{prefix}-Guardrail", env=env)

gateway = GatewayStack(
    app, f"{prefix}-Gateway",
    gateway_role=foundation.gateway_role,
    okta_discovery_url=okta_config["discovery_url"],
    okta_audience=okta_config["audience"],
    okta_m2m_client_id=okta_config["m2m_client_id"],
    env=env,
)
gateway.add_dependency(foundation)

webapp = WebAppStack(
    app, f"{prefix}-WebApp",
    ecs_exec_role_arn=foundation.ecs_exec_role.role_arn,
    ecs_task_role_arn=foundation.ecs_task_role.role_arn,
    okta_issuer=okta_config["issuer"],
    okta_spa_client_id=okta_config.get("spa_client_id", ""),
    okta_web_client_id=okta_config.get("web_client_id", ""),
    okta_web_client_secret=okta_config.get("web_client_secret", ""),
    env=env,
)
webapp.add_dependency(foundation)

cloudfront = CloudFrontStack(
    app, f"{prefix}-CloudFront",
    alb=webapp.alb,
    env=env,
)
cloudfront.add_dependency(webapp)

app.synth()
