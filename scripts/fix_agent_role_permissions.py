"""Fix permissions on auto-created AgentCore Runtime execution roles.

agentcore deploy auto-creates IAM roles with minimal permissions. This script
adds the extra permissions each runtime needs: DynamoDB + Bedrock KB for the LOB
MCP server roles, and Agent Registry search + AgentCore Identity Token Vault
access for the agent role.

Usage:
  python3 scripts/fix_agent_role_permissions.py --profile platform
"""
import argparse
import json
import os
import yaml
import boto3

REGION = os.environ.get("AWS_REGION", "us-east-1")
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PREFIX = os.environ.get("CDK_PREFIX", "LOBFederation")


def get_role_name(yaml_path):
    with open(yaml_path) as f:
        cfg = yaml.safe_load(f)
    for agent in cfg.get("agents", {}).values():
        role = agent.get("aws", {}).get("execution_role", "")
        return role.rsplit("/", 1)[-1] if "/" in role else role
    return None


def get_account(yaml_path):
    with open(yaml_path) as f:
        cfg = yaml.safe_load(f)
    for agent in cfg.get("agents", {}).values():
        return agent.get("aws", {}).get("account", "")
    return ""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", default="platform")
    args = parser.parse_args()

    print("=" * 60)
    print("Fix Agent Role Permissions")
    print("=" * 60)

    # --- MCP server roles: DynamoDB + KB ---
    lobs = [
        ("retail-banking", "lob-accounts/retail-banking/mcp_server/.bedrock_agentcore.yaml", False),
        ("transaction-banking", "lob-accounts/transaction-banking/mcp_server/.bedrock_agentcore.yaml", False),
        ("lending-wealth", "lob-accounts/lending-wealth/mcp_server/.bedrock_agentcore.yaml", True),
    ]

    for profile, yaml_rel, has_kb in lobs:
        yaml_path = os.path.join(PROJECT_DIR, yaml_rel)
        if not os.path.exists(yaml_path):
            print(f"  ⚠️ {profile}: {yaml_rel} not found — skipping")
            continue

        role_name = get_role_name(yaml_path)
        acct = get_account(yaml_path)
        session = boto3.Session(profile_name=profile, region_name=REGION)
        iam = session.client("iam")

        # DynamoDB read
        iam.put_role_policy(
            RoleName=role_name,
            PolicyName="DynamoDBReadAccess",
            PolicyDocument=json.dumps({
                "Version": "2012-10-17",
                "Statement": [{
                    "Effect": "Allow",
                    "Action": ["dynamodb:GetItem", "dynamodb:Query", "dynamodb:Scan", "dynamodb:BatchGetItem", "dynamodb:PutItem", "dynamodb:UpdateItem"],
                    "Resource": f"arn:aws:dynamodb:{REGION}:{acct}:table/*",
                }],
            }),
        )
        print(f"  ✅ {profile}: DynamoDB permissions added to {role_name}")

        # KB permissions for lending-wealth
        if has_kb:
            try:
                cf = session.client("cloudformation")
                kb_id = cf.describe_stacks(StackName="LobInfra-lending-wealth-KnowledgeBase")["Stacks"][0]
                kb_id = [o["OutputValue"] for o in kb_id.get("Outputs", []) if o["OutputKey"] == "KnowledgeBaseId"][0]
                iam.put_role_policy(
                    RoleName=role_name,
                    PolicyName="BedrockKBAccess",
                    PolicyDocument=json.dumps({
                        "Version": "2012-10-17",
                        "Statement": [{
                            "Effect": "Allow",
                            "Action": ["bedrock:Retrieve", "bedrock:RetrieveAndGenerate"],
                            "Resource": f"arn:aws:bedrock:{REGION}:{acct}:knowledge-base/{kb_id}",
                        }],
                    }),
                )
                print(f"  ✅ {profile}: KB permissions added (KB: {kb_id})")
            except Exception as e:
                print(f"  ⚠️ {profile}: KB permissions failed — {e}")

    # --- Agent role: AgentCore Identity + Registry ---
    agent_yaml = os.path.join(PROJECT_DIR, "platform-account", "agent", ".bedrock_agentcore.yaml")
    if os.path.exists(agent_yaml):
        role_name = get_role_name(agent_yaml)
        acct = get_account(agent_yaml)
        session = boto3.Session(profile_name=args.profile, region_name=REGION)
        iam = session.client("iam")

        iam.put_role_policy(
            RoleName=role_name,
            PolicyName="AgentExtraPermissions",
            PolicyDocument=json.dumps({
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": ["bedrock-agentcore:SearchRegistryRecords"],
                        "Resource": f"arn:aws:bedrock-agentcore:{REGION}:{acct}:registry/*",
                    },
                    {
                        "Effect": "Allow",
                        "Action": ["bedrock-agentcore:GetWorkloadAccessToken", "bedrock-agentcore:GetResourceOauth2Token"],
                        "Resource": "*",
                    },
                ],
            }),
        )
        print(f"  ✅ agent: Registry + Token Vault permissions added to {role_name}")
    else:
        print(f"  ⚠️ agent: {agent_yaml} not found — skipping")

    print(f"\n{'=' * 60}")
    print("✅ All role permissions fixed")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
