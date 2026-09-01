"""Register 3 LOB MCP servers in Agent Registry for dynamic discovery.

Creates a registry (if not exists), registers each LOB as an MCP record,
and submits for approval (auto-approved). The agent discovers these at
startup via search_registry_records().

Usage:
  python3 platform-account/gateway/register_agents.py --profile platform
"""
import argparse
import json
import os
import time

import boto3
import yaml

REGION = os.environ.get("AWS_REGION", "us-east-1")
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REGISTRY_NAME = "bankingdemo-agent-registry"

LOB_CONFIGS = [
    {
        "name": "retail-banking",
        "description": "Retail Banking MCP server — customer profiles, bank accounts, balances (4 tools: get_customer, get_accounts, get_balance, get_profile)",
        "yaml_path": os.path.join(PROJECT_DIR, "lob-accounts", "retail-banking", "mcp_server", ".bedrock_agentcore.yaml"),
        "tools": ["get_customer", "get_accounts", "get_balance", "get_profile"],
    },
    {
        "name": "transaction-banking",
        "description": "Transaction Banking MCP server — payment history, fund transfers, beneficiaries (4 tools: get_payments, transfer_funds, get_beneficiaries, schedule_payment)",
        "yaml_path": os.path.join(PROJECT_DIR, "lob-accounts", "transaction-banking", "mcp_server", ".bedrock_agentcore.yaml"),
        "tools": ["get_payments", "transfer_funds", "get_beneficiaries", "schedule_payment"],
    },
    {
        "name": "lending-wealth",
        "description": "Lending & Wealth MCP server — loans, credit scores, eligibility, EMI calculations, lending policy search via Bedrock KB (6 tools: get_loans, check_eligibility, get_credit_score, get_emi_details, calculate_emi, search_lending_policies)",
        "yaml_path": os.path.join(PROJECT_DIR, "lob-accounts", "lending-wealth", "mcp_server", ".bedrock_agentcore.yaml"),
        "tools": ["get_loans", "check_eligibility", "get_credit_score", "get_emi_details", "calculate_emi", "search_lending_policies"],
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


def get_or_create_registry(ctrl) -> tuple[str, str]:
    """Get existing registry or create new one with auto-approval."""
    try:
        for r in ctrl.list_registries().get("registries", []):
            if r["name"] == REGISTRY_NAME:
                registry_id = r["registryId"]
                print(f"  Registry exists: {registry_id}")
                for _ in range(30):
                    info = ctrl.get_registry(registryId=registry_id)
                    if info["status"] == "READY":
                        return registry_id, info["registryArn"]
                    time.sleep(2)  # nosemgrep: arbitrary-sleep — poll for registry readiness
                return registry_id, info["registryArn"]
    except Exception:
        pass

    resp = ctrl.create_registry(
        name=REGISTRY_NAME,
        description="Banking Demo — LOB MCP server registry for dynamic discovery",
        approvalConfiguration={"autoApproval": True},
    )
    registry_arn = resp["registryArn"]
    registry_id = registry_arn.rsplit("/", 1)[-1]
    print(f"  Created registry: {registry_id} (waiting for READY...)")
    for _ in range(60):
        time.sleep(2)  # nosemgrep: arbitrary-sleep — poll for registry READY state
        info = ctrl.get_registry(registryId=registry_id)
        if info["status"] == "READY":
            print(f"  ✅ Registry READY")
            return registry_id, registry_arn
    print(f"  ⚠️ Registry status: {info['status']}")
    return registry_id, registry_arn


def register_lob(ctrl, registry_id, lob_config):
    """Register a LOB MCP server in the registry."""
    name = lob_config["name"]
    runtime_arn = get_runtime_arn(lob_config["yaml_path"])
    if not runtime_arn:
        print(f"  {name}: ⚠️ no runtime ARN — skipping")
        return None

    # Delete existing record with same name
    try:
        existing = ctrl.list_registry_records(registryId=registry_id)
        for r in existing.get("registryRecords", []):
            if r["name"] == name:
                print(f"  {name}: deleting existing record ({r['recordId']})")
                ctrl.delete_registry_record(registryId=registry_id, recordId=r["recordId"])
                time.sleep(2)  # nosemgrep: arbitrary-sleep — wait for record deletion
                break
    except Exception:
        pass

    # Create registry record — use CUSTOM descriptor (simpler, no MCP schema validation)
    # The agent discovers LOBs via search_registry_records by name/description
    descriptor_content = json.dumps({
        "name": name,
        "type": "mcp-server",
        "description": lob_config["description"],
        "runtime_arn": runtime_arn,
        "tools": lob_config.get("tools", []),
    })

    resp = ctrl.create_registry_record(
        registryId=registry_id,
        name=name,
        description=lob_config["description"],
        descriptorType="CUSTOM",
        descriptors={"custom": {"inlineContent": descriptor_content}},
        recordVersion="1.0",
    )
    record_id = resp["recordArn"].rsplit("/", 1)[-1]
    print(f"  {name}: created (recordId={record_id})")

    # Wait for DRAFT then submit for approval
    for _ in range(15):
        time.sleep(2)  # nosemgrep: arbitrary-sleep — poll for record DRAFT state
        info = ctrl.get_registry_record(registryId=registry_id, recordId=record_id)
        if info["status"] == "DRAFT":
            break

    ctrl.submit_registry_record_for_approval(registryId=registry_id, recordId=record_id)
    print(f"  {name}: ✅ submitted for approval (auto-approved)")
    return record_id


def main():
    parser = argparse.ArgumentParser(description="Register LOBs in Agent Registry")
    parser.add_argument("--profile", default=os.environ.get("AWS_PROFILE", "platform"))
    args = parser.parse_args()

    session = boto3.Session(profile_name=args.profile, region_name=REGION)
    ctrl = session.client("bedrock-agentcore-control")

    print("=" * 60)
    print("Agent Registry — Register LOB MCP Servers")
    print("=" * 60)

    # Step 1: Create/get registry
    print("\n=== Step 1: Create/Get Registry ===")
    registry_id, registry_arn = get_or_create_registry(ctrl)

    # Step 2: Register LOBs
    print("\n=== Step 2: Register LOB MCP Servers ===")
    records = {}
    for lob in LOB_CONFIGS:
        record_id = register_lob(ctrl, registry_id, lob)
        if record_id:
            records[lob["name"]] = record_id

    # Step 3: Save config
    print("\n=== Step 3: Save Registry Config ===")
    config = {
        "registry_name": REGISTRY_NAME,
        "registry_id": registry_id,
        "registry_arn": registry_arn,
        "region": REGION,
        "records": records,
    }
    config_path = os.path.join(PROJECT_DIR, "registry_config.json")
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)
    print(f"  ✅ Saved: {config_path}")

    print(f"\n{'=' * 60}")
    print(f"✅ Registry setup complete!")
    print(f"  Registry: {REGISTRY_NAME} ({registry_id})")
    print(f"  ARN: {registry_arn}")
    print(f"  Records: {len(records)} LOBs registered")
    print(f"\n  Set this in agent env: REGISTRY_ARN={registry_arn}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
