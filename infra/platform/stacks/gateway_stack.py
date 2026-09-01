from aws_cdk import (
    Stack, CfnOutput,
    aws_bedrockagentcore as ac,
)
from constructs import Construct


class GatewayStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, *, gateway_role,
                 okta_discovery_url: str, okta_audience: str, okta_m2m_client_id: str, **kwargs):
        super().__init__(scope, construct_id, **kwargs)

        prefix = self.node.try_get_context("project_prefix") or "LOBFederation"
        prefix_lower = prefix.lower().replace(" ", "-")

        # --- Gateway (Okta JWT inbound auth — pure M2M) ---
        # Validate the audience AND the calling client. Okta emits the client id in
        # the `cid` claim (not `client_id`), so allowed_clients won't match — we use
        # a custom claim to require cid == the M2M client id. setup_gateway.py applies
        # the same authorizer post-deploy (when attaching the Cedar policy engine).
        self.gateway = ac.CfnGateway(
            self, "Gateway",
            name=f"{prefix_lower}-gateway",
            protocol_type="MCP",
            protocol_configuration=ac.CfnGateway.GatewayProtocolConfigurationProperty(
                mcp=ac.CfnGateway.MCPGatewayConfigurationProperty(
                    search_type="SEMANTIC",
                    supported_versions=["2025-03-26"],
                ),
            ),
            authorizer_type="CUSTOM_JWT",
            role_arn=gateway_role.role_arn,
            authorizer_configuration=ac.CfnGateway.AuthorizerConfigurationProperty(
                custom_jwt_authorizer=ac.CfnGateway.CustomJWTAuthorizerConfigurationProperty(
                    discovery_url=okta_discovery_url,
                    allowed_audience=[okta_audience],
                    custom_claims=[
                        ac.CfnGateway.CustomClaimValidationTypeProperty(
                            inbound_token_claim_name="cid",
                            inbound_token_claim_value_type="STRING",
                            authorizing_claim_match_value=ac.CfnGateway.AuthorizingClaimMatchValueTypeProperty(
                                claim_match_operator="EQUALS",
                                claim_match_value=ac.CfnGateway.ClaimMatchValueTypeProperty(
                                    match_value_string=okta_m2m_client_id,
                                ),
                            ),
                        ),
                    ],
                ),
            ),
        )

        # NOTE: MCP server targets are created by setup_gateway.py after MCP servers
        # are deployed, because target creation requires runtime ARNs.

        # --- Outputs ---
        CfnOutput(self, "GatewayId", value=self.gateway.attr_gateway_identifier)
        CfnOutput(self, "GatewayUrl", value=self.gateway.attr_gateway_url)
        CfnOutput(self, "GatewayArn", value=self.gateway.attr_gateway_arn)
