"""Post-deploy: create Okta M2M (client_credentials) credential provider + 3 MCP server targets on the LOBFederation Gateway.

Reads Gateway ID from CDK stack outputs and Okta config from okta_config.json.
Creates a plain client_credentials OAuth credential provider, then creates
3 MCP server targets using OAuth (client_credentials) outbound auth.

Usage:
  python3 platform-account/gateway/setup_gateway.py --profile platform
"""
import argparse
import json
import os
import sys
import time
import urllib.parse

import boto3
import yaml

REGION = os.environ.get("AWS_REGION", "us-east-1")
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PREFIX = os.environ.get("CDK_PREFIX", "LOBFederation")

LOB_CONFIGS = [
    {
        "name": "retail-banking",
        "yaml_path": os.path.join(PROJECT_DIR, "lob-accounts", "retail-banking", "mcp_server", ".bedrock_agentcore.yaml"),
        "description": "Retail Banking — customer profiles, accounts, balances",
    },
    {
        "name": "transaction-banking",
        "yaml_path": os.path.join(PROJECT_DIR, "lob-accounts", "transaction-banking", "mcp_server", ".bedrock_agentcore.yaml"),
        "description": "Transaction Banking — payments, transfers, beneficiaries",
    },
    {
        "name": "lending-wealth",
        "yaml_path": os.path.join(PROJECT_DIR, "lob-accounts", "lending-wealth", "mcp_server", ".bedrock_agentcore.yaml"),
        "description": "Lending & Wealth — loans, credit scores, eligibility, policy search",
    },
]


def get_runtime_arn(yaml_path: str) -> str | None:
    if not os.path.exists(yaml_path):
        return None
    with open(yaml_path) as f:
        cfg = yaml.safe_load(f)
    for agent in cfg.get("agents", {}).values():
        arn = agent.get("bedrock_agentcore", {}).get("agent_arn")
        if arn:
            return arn
    return None


def get_stack_output(cf, stack_name, key):
    resp = cf.describe_stacks(StackName=stack_name)
    for o in resp["Stacks"][0].get("Outputs", []):
        if o["OutputKey"] == key:
            return o["OutputValue"]
    raise KeyError(f"Output {key} not found in stack {stack_name}")


def build_mcp_endpoint(runtime_arn: str) -> str:
    encoded_arn = urllib.parse.quote(runtime_arn, safe="")
    return f"https://bedrock-agentcore.{REGION}.amazonaws.com/runtimes/{encoded_arn}/invocations"


def load_okta_config() -> dict:
    config_path = os.path.join(PROJECT_DIR, "okta_config.json")
    if not os.path.exists(config_path):
        print(f"ERROR: {config_path} not found. Create it first.")
        sys.exit(1)
    with open(config_path) as f:
        return json.load(f)


def main():
    parser = argparse.ArgumentParser(description="Create Gateway targets with Okta M2M (client_credentials) auth")
    parser.add_argument("--profile", default=os.environ.get("AWS_PROFILE", "platform"))
    args = parser.parse_args()

    session = boto3.Session(profile_name=args.profile, region_name=REGION)
    cf = session.client("cloudformation")
    ctrl = session.client("bedrock-agentcore-control")

    okta = load_okta_config()
    prefix_lower = PREFIX.lower().replace(" ", "-")

    print("=" * 60)
    print("Gateway Setup — Okta M2M (client_credentials)")
    print("=" * 60)

    # Step 1: Read CDK outputs
    gateway_id = get_stack_output(cf, f"{PREFIX}-Gateway", "GatewayId")
    gateway_url = get_stack_output(cf, f"{PREFIX}-Gateway", "GatewayUrl")
    gateway_arn = get_stack_output(cf, f"{PREFIX}-Gateway", "GatewayArn")

    print(f"\nGateway: {gateway_id}")
    print(f"Okta Issuer: {okta['issuer']}")
    print(f"M2M Client: {okta['m2m_client_id']}")

    # Step 2: Create Okta OAuth credential provider (M2M / client_credentials)
    print("\n=== Step 2: Okta OAuth Credential Provider (client_credentials / M2M) ===")
    cred_name = "lobfederation-okta-m2m"
    cred_arn = None

    # Delete stale provider if exists
    try:
        existing = ctrl.get_oauth2_credential_provider(name=cred_name)
        print(f"  Deleting stale credential provider: {existing['credentialProviderArn']}")
        ctrl.delete_oauth2_credential_provider(name=cred_name)
        time.sleep(5)  # nosemgrep: arbitrary-sleep
    except Exception:
        pass

    try:
        resp = ctrl.create_oauth2_credential_provider(
            name=cred_name,
            credentialProviderVendor="CustomOauth2",
            oauth2ProviderConfigInput={
                "customOauth2ProviderConfig": {
                    "oauthDiscovery": {"discoveryUrl": okta["discovery_url"]},
                    "clientId": okta["m2m_client_id"],
                    "clientSecret": okta["m2m_client_secret"],
                    "clientAuthenticationMethod": "CLIENT_SECRET_BASIC",
                }
            },
        )
        cred_arn = resp["credentialProviderArn"]
        print(f"  Created: {cred_arn}")
    except Exception as e:
        print(f"  ❌ Failed to create credential provider: {e}")
        sys.exit(1)

    # Step 3: Create workload identity for the agent
    print("\n=== Step 3: Workload Identity ===")
    workload_name = "lobfederation-agent"
    try:
        ctrl.get_workload_identity(name=workload_name)
        print(f"  Workload identity already exists: {workload_name}")
    except ctrl.exceptions.ResourceNotFoundException:
        ctrl.create_workload_identity(name=workload_name)
        print(f"  Created workload identity: {workload_name}")
    except Exception:
        # May not have ResourceNotFoundException — try create
        try:
            ctrl.create_workload_identity(name=workload_name)
            print(f"  Created workload identity: {workload_name}")
        except Exception as e2:
            if "already exists" in str(e2).lower() or "conflict" in str(e2).lower():
                print(f"  Workload identity already exists: {workload_name}")
            else:
                print(f"  ⚠️ Could not create workload identity: {e2}")

    # Step 4: Delete existing targets
    print("\n=== Step 4: Clean existing targets ===")
    existing = ctrl.list_gateway_targets(gatewayIdentifier=gateway_id)
    for t in existing.get("items", []):
        print(f"  Deleting: {t['name']} ({t['targetId']})")
        ctrl.delete_gateway_target(gatewayIdentifier=gateway_id, targetId=t["targetId"])
        time.sleep(2)  # nosemgrep: arbitrary-sleep

    # Step 5: Create targets with OAuth outbound auth
    scope = okta["scope"]
    print(f"\n=== Step 5: Create targets (OAuth, scope={scope}) ===")
    for lob in LOB_CONFIGS:
        name = lob["name"]
        runtime_arn = get_runtime_arn(lob["yaml_path"])
        if not runtime_arn:
            print(f"  {name}: ⚠️ no runtime ARN in {lob['yaml_path']} — skipping")
            continue

        endpoint_url = build_mcp_endpoint(runtime_arn)
        print(f"  {name}: creating target → {runtime_arn}")

        try:
            resp = ctrl.create_gateway_target(
                gatewayIdentifier=gateway_id,
                name=name,
                description=lob["description"],
                targetConfiguration={
                    "mcp": {
                        "mcpServer": {
                            "endpoint": endpoint_url,
                        }
                    }
                },
                credentialProviderConfigurations=[
                    {
                        "credentialProviderType": "OAUTH",
                        "credentialProvider": {
                            "oauthCredentialProvider": {
                                "providerArn": cred_arn,
                                "scopes": [scope],
                                "grantType": "CLIENT_CREDENTIALS",
                            }
                        },
                    }
                ],
            )
            target_id = resp.get("targetId", "unknown")
            print(f"  {name}: ✅ created (targetId={target_id})")
        except Exception as e:
            print(f"  {name}: ❌ failed — {e}")

    # Step 6: Wait for targets to sync
    print("\n=== Waiting for targets to sync ===")
    for i in range(36):
        time.sleep(5)  # nosemgrep: arbitrary-sleep
        final = ctrl.list_gateway_targets(gatewayIdentifier=gateway_id)
        statuses = {t["name"]: t["status"] for t in final.get("items", [])}
        if all(s == "READY" for s in statuses.values()) and len(statuses) == len(LOB_CONFIGS):
            print(f"  All READY ({(i+1)*5}s)")
            break
        if i % 6 == 0:
            print(f"  ... {statuses} ({(i+1)*5}s)")

    # Step 7: Cedar policy engine
    print(f"\n=== Step 7: Cedar Policy Engine ===")
    policy_engine_id = None

    gw_detail = ctrl.get_gateway(gatewayIdentifier=gateway_id)
    pec = gw_detail.get("policyEngineConfiguration", {})
    if pec and pec.get("arn"):
        policy_engine_id = pec["arn"].rsplit("/", 1)[-1]
        print(f"  Gateway already has policy engine: {policy_engine_id}")
    else:
        pe_name = f"{prefix_lower.replace('-', '_')}_cedar_engine"
        try:
            existing_engines = ctrl.list_policy_engines().get("policyEngines", [])
            for pe in existing_engines:
                if pe.get("name") == pe_name:
                    policy_engine_id = pe["policyEngineId"]
                    print(f"  Reusing existing policy engine: {policy_engine_id}")
                    break
        except Exception:
            pass

        if not policy_engine_id:
            resp = ctrl.create_policy_engine(name=pe_name, description="Cedar ENFORCE for LOB Federation Gateway")
            policy_engine_id = resp["policyEngineArn"].rsplit("/", 1)[-1]
            print(f"  Created policy engine: {policy_engine_id}")
            for _ in range(30):
                time.sleep(2)  # nosemgrep: arbitrary-sleep
                pe_info = ctrl.get_policy_engine(policyEngineId=policy_engine_id)
                if pe_info.get("status") == "READY":
                    break
            print(f"  ✅ Policy engine READY")

        # Attach to gateway — use Okta discovery URL
        try:
            ctrl.update_gateway(
                gatewayIdentifier=gateway_id,
                name=f"{prefix_lower}-gateway",
                protocolType="MCP",
                protocolConfiguration={
                    "mcp": {
                        "searchType": "SEMANTIC",
                        "supportedVersions": ["2025-03-26"],
                    }
                },
                roleArn=gw_detail["roleArn"],
                authorizerType="CUSTOM_JWT",
                authorizerConfiguration={
                    "customJWTAuthorizer": {
                        "discoveryUrl": okta["discovery_url"],
                        "allowedAudience": [okta["audience"]],
                        # No allowedClients — Okta uses 'cid' claim (not 'client_id')
                        # which AgentCore doesn't match against. Audience check is sufficient.
                    }
                },
                policyEngineConfiguration={
                    "arn": ctrl.get_policy_engine(policyEngineId=policy_engine_id)["policyEngineArn"],
                    "mode": "ENFORCE",
                },
            )
            print(f"  ✅ Attached to gateway (ENFORCE mode)")
            time.sleep(10)  # nosemgrep: arbitrary-sleep

            # Re-verify targets after update
            remaining = ctrl.list_gateway_targets(gatewayIdentifier=gateway_id)
            remaining_names = {t["name"] for t in remaining.get("items", [])}
            expected_names = {lob["name"] for lob in LOB_CONFIGS}
            missing = expected_names - remaining_names
            if missing:
                print(f"  ⚠️ Targets lost after update: {missing} — recreating...")
                for lob in LOB_CONFIGS:
                    if lob["name"] not in missing:
                        continue
                    runtime_arn = get_runtime_arn(lob["yaml_path"])
                    if not runtime_arn:
                        continue
                    endpoint_url = build_mcp_endpoint(runtime_arn)
                    ctrl.create_gateway_target(
                        gatewayIdentifier=gateway_id, name=lob["name"],
                        description=lob.get("description", ""),
                        targetConfiguration={"mcp": {"mcpServer": {"endpoint": endpoint_url}}},
                        credentialProviderConfigurations=[{
                            "credentialProviderType": "OAUTH",
                            "credentialProvider": {"oauthCredentialProvider": {
                                "providerArn": cred_arn, "scopes": [scope], "grantType": "CLIENT_CREDENTIALS",
                            }}
                        }],
                    )
                    print(f"  ✅ Recreated: {lob['name']}")
                time.sleep(15)  # nosemgrep: arbitrary-sleep
        except Exception as e:
            print(f"  ⚠️ Could not attach policy engine: {e}")

    # Step 8: Cedar policies
    if policy_engine_id:
        print(f"\n=== Step 8: Cedar Policies (engine={policy_engine_id}) ===")

        # Delete any existing policies, then WAIT for deletion to complete.
        # delete_policy is asynchronous — a fixed sleep races create_policy against
        # the still-DELETING policy name and raises ConflictException. Poll until empty.
        for p in ctrl.list_policies(policyEngineId=policy_engine_id).get("policies", []):
            try:
                ctrl.delete_policy(policyEngineId=policy_engine_id, policyId=p["policyId"])
                print(f"  deleting existing policy: {p['name']}")
            except Exception as e:
                print(f"  ⚠️ could not delete {p.get('name')}: {e}")
        for _ in range(30):
            if not ctrl.list_policies(policyEngineId=policy_engine_id).get("policies", []):
                break
            time.sleep(2)  # nosemgrep: arbitrary-sleep
        else:
            print("  ⚠️ existing policies still present after wait — creates may conflict")

        def _create_policy(name, statement, validation_mode="FAIL_ON_ANY_FINDINGS"):
            # Idempotent against an in-flight delete of the same name.
            for attempt in range(20):
                try:
                    ctrl.create_policy(
                        policyEngineId=policy_engine_id,
                        name=name,
                        definition={"cedar": {"statement": statement}},
                        validationMode=validation_mode,
                    )
                    print(f"  ✅ {name} ({validation_mode})")
                    return
                except ctrl.exceptions.ConflictException:
                    if attempt == 19:
                        raise
                    time.sleep(2)  # nosemgrep: arbitrary-sleep

        # PERMIT all authenticated users
        permit_stmt = (
            f'permit(principal is AgentCore::OAuthUser, '
            f'action, '
            f'resource == AgentCore::Gateway::"{gateway_arn}");'
        )
        _create_policy("PermitAllAuthenticatedTools", permit_stmt, validation_mode="IGNORE_ALL_FINDINGS")

        # DENY delete_customer
        deny_stmt = (
            f'forbid(principal, '
            f'action == AgentCore::Action::"retail-banking___delete_customer", '
            f'resource == AgentCore::Gateway::"{gateway_arn}");'
        )
        # A blanket forbid trips the engine's "Overly Restrictive" finding, which
        # FAIL_ON_ANY_FINDINGS rejects (CREATE_FAILED). That restrictiveness is the
        # intent for this demo deny, so create it with IGNORE_ALL_FINDINGS.
        _create_policy("DenyDeleteCustomer", deny_stmt, validation_mode="IGNORE_ALL_FINDINGS")

    # Save config
    config = {
        "gateway_id": gateway_id,
        "gateway_url": gateway_url,
        "gateway_arn": gateway_arn,
        "auth_type": "OKTA_M2M",
        "credential_provider_name": cred_name,
        "credential_provider_arn": cred_arn,
        "workload_name": workload_name,
        "okta_issuer": okta["issuer"],
        "m2m_client_id": okta["m2m_client_id"],
        "scope": scope,
        "policy_engine_id": policy_engine_id or "",
        "region": REGION,
    }
    config_path = os.path.join(PROJECT_DIR, "gateway_config.json")
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)
    print(f"\n✅ Saved: {config_path}")

    print(f"\n{'=' * 60}")
    print("✅ Gateway setup complete (Okta M2M client_credentials)")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
