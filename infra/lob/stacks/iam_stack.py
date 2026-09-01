from aws_cdk import (
    Stack, CfnOutput,
    aws_iam as iam,
)
from constructs import Construct


class LobIamStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs):
        super().__init__(scope, construct_id, **kwargs)

        platform_account_id = self.node.try_get_context("platform_account_id")
        if not platform_account_id:
            raise ValueError("Context 'platform_account_id' is required")

        # Role that the platform Gateway assumes to invoke this LOB's MCP server
        self.invoke_role = iam.Role(
            self, "LobRuntimeInvokeRole",
            role_name="LobRuntimeInvokeRole",
            assumed_by=iam.ArnPrincipal(
                f"arn:aws:iam::{platform_account_id}:role/LOBFederation-GatewayExecutionRole"
            ),
            inline_policies={
                "InvokeRuntime": iam.PolicyDocument(
                    statements=[
                        iam.PolicyStatement(
                            actions=["bedrock-agentcore:InvokeAgentRuntime"],
                            resources=[f"arn:aws:bedrock-agentcore:{self.region}:{self.account}:runtime/*"],
                        ),
                    ]
                )
            },
        )

        CfnOutput(self, "LobRuntimeInvokeRoleArn", value=self.invoke_role.role_arn)
