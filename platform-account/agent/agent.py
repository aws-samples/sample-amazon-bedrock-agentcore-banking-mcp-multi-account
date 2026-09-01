"""Multi-Account Banking Agent — Platform Account.

Strands Agent on AgentCore Runtime. Discovers LOB MCP servers dynamically
from Agent Registry at startup, then connects to AgentCore Gateway for
tool invocation across 3 LOB accounts.

Auth (User Identity Propagation): The user's JWT (obtained during Okta login)
is forwarded from the ECS backend → Agent Runtime → Gateway. The Runtime uses
customJWTAuthorizer to validate the token and makes it available via
context.request_headers["Authorization"]. The agent passes it directly to the
Gateway, where Cedar evaluates per-user policies. Gateway→LOB outbound auth
remains M2M (client_credentials via the credential provider) — unchanged.

Discovery: search_registry_records() → LOB names + metadata
Invocation: Gateway MCP (user JWT) → Cedar per-user auth → LOB MCP (M2M)
"""
import os
import json
import logging
import boto3
from botocore.config import Config
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from mcp.client.streamable_http import streamablehttp_client
from strands import Agent
from strands.tools.mcp import MCPClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = BedrockAgentCoreApp()

REGION = os.environ.get("AWS_REGION", "us-east-1")
MODEL_ID = os.environ.get("MODEL_ID", "us.anthropic.claude-sonnet-4-5-20250929-v1:0")

# Config from file or env
_config = {}
_config_path = os.path.join(os.path.dirname(__file__), "runtime_config.json")
if os.path.exists(_config_path):
    with open(_config_path) as f:
        _config = json.load(f)

GATEWAY_URL = os.environ.get("GATEWAY_URL", _config.get("GATEWAY_URL", ""))
REGISTRY_ARN = os.environ.get("REGISTRY_ARN", _config.get("REGISTRY_ARN", ""))

# ---------------------------------------------------------------------------
# Registry discovery — discover LOB MCP servers at startup
# ---------------------------------------------------------------------------

_discovered_lobs: dict[str, dict] = {}


def _discover_lobs_from_registry():
    """Search Agent Registry for LOB MCP servers and log what we found."""
    if not REGISTRY_ARN:
        logger.info("No REGISTRY_ARN set — skipping Registry discovery")
        return
    logger.info("Discovering LOBs from Agent Registry: %s", REGISTRY_ARN)
    try:
        client = boto3.client(
            "bedrock-agentcore", region_name=REGION,
            config=Config(read_timeout=120, retries={"max_attempts": 3, "mode": "adaptive"}),
        )
        results = client.search_registry_records(
            searchQuery="banking LOB MCP server",
            registryIds=[REGISTRY_ARN],
            maxResults=10,
        )
        for record in results.get("registryRecords", []):
            name = record["name"]
            desc = record.get("description", "")
            _discovered_lobs[name] = {"description": desc, "record_id": record.get("recordId", "")}
            logger.info("Registry → discovered LOB: %s — %s", name, desc)
        logger.info("Registry discovery complete: %d LOBs found", len(_discovered_lobs))
    except Exception:
        logger.exception("Registry discovery failed — agent will still work via Gateway")


# Run discovery at module load (agent startup)
_discover_lobs_from_registry()

# ---------------------------------------------------------------------------
# Build system prompt dynamically from discovered LOBs
# ---------------------------------------------------------------------------

_STATIC_LOB_INFO = {
    "retail-banking": "Customer profiles, bank accounts, balances",
    "transaction-banking": "Payment history, fund transfers, beneficiaries",
    "lending-wealth": "Loans, credit scores, eligibility checks, EMI calculations, lending policy search",
}


def _build_system_prompt() -> str:
    lob_lines = []
    if _discovered_lobs:
        for name, info in _discovered_lobs.items():
            lob_lines.append(f"- **{name}**: {info['description']}")
    else:
        for name, desc in _STATIC_LOB_INFO.items():
            lob_lines.append(f"- **{name}**: {desc}")

    lob_section = "\n".join(lob_lines)
    return f"""You are a Multi-Account Banking Assistant that helps relationship managers and analysts with banking queries across multiple lines of business.

You have access to tools from these banking LOBs (discovered dynamically):
{lob_section}

Guidelines:
1. Always identify the customer first using get_customer before accessing other data.
2. When asked about balances, use get_accounts to find account IDs, then get_balance for each.
3. For loan eligibility, gather credit score and payment history to provide a complete assessment.
4. For policy questions, use search_lending_policies to check bank guidelines before making recommendations.
5. For fund transfers, verify the source account has sufficient balance before proceeding. After a successful transfer_funds call, always call update_balance twice: once to debit the source account and once to credit the destination account.
6. Present financial data clearly with currency formatting.
7. Be concise but thorough in your responses.
8. If a tool returns an error, explain it clearly to the user.

Tool names use the format {{lob-name}}___{{tool_name}}. Always use the full prefixed name."""


SYSTEM_PROMPT = _build_system_prompt()

# ---------------------------------------------------------------------------
# Agent entrypoint
# ---------------------------------------------------------------------------


@app.entrypoint
def invoke(payload, context=None):
    if isinstance(payload, str):
        payload = json.loads(payload)

    prompt = payload.get("prompt", "Hello")
    customer_id = payload.get("customer_id", "")
    user_role = payload.get("user_role", "viewer")
    user_email = payload.get("user_email", "")

    if customer_id:
        prompt = f"[Customer ID: {customer_id}] {prompt}"

    # User Identity Propagation: read the user's JWT from request headers.
    # The Runtime's customJWTAuthorizer already validated it. We forward it
    # directly to the Gateway so Cedar can authorize per-user.
    request_headers = {}
    if context and hasattr(context, "request_headers"):
        request_headers = context.request_headers or {}

    user_jwt = request_headers.get("Authorization", "")
    if not user_jwt:
        # Fallback: check lowercase (HTTP/2 normalizes to lowercase)
        user_jwt = request_headers.get("authorization", "")

    if not user_jwt:
        logger.error("No Authorization header in request — user JWT required")
        return json.dumps({"error": "User authorization required. Please log in again."})

    logger.info("Forwarding user JWT to Gateway (len=%d)", len(user_jwt))

    mcp_client = MCPClient(
        lambda: streamablehttp_client(
            url=GATEWAY_URL,
            headers={"Authorization": user_jwt},
            timeout=120,
            terminate_on_close=False,
        )
    )

    try:
        with mcp_client:
            tools = mcp_client.list_tools_sync()
            logger.info("Loaded %d MCP tools from Gateway", len(tools))
            agent = Agent(model=MODEL_ID, system_prompt=SYSTEM_PROMPT, tools=tools)
            result = agent(prompt)
    except Exception as e:
        logger.exception("Agent invocation failed")
        return json.dumps({"error": f"Agent invocation failed: {e}"})

    # Extract tool trace — pair toolUse with toolResult, detect Cedar denials
    tool_calls = []
    tool_use_map = {}

    def _is_cedar_denied(tool_result):
        if tool_result.get("status") == "error":
            for cb in tool_result.get("content", []):
                text = cb.get("text", "") if isinstance(cb, dict) else str(cb)
                if any(kw in text.lower() for kw in ["forbidden", "not authorized to perform", "cedar", "policy denied"]):
                    return True
        return False

    for msg in agent.messages:
        if msg.get("role") == "assistant":
            for block in msg.get("content", []):
                if isinstance(block, dict) and block.get("toolUse"):
                    tu = block["toolUse"]
                    tool_use_map[tu["toolUseId"]] = {
                        "name": tu["name"],
                        "lob": tu["name"].split("___")[0] if "___" in tu["name"] else "unknown",
                        "input": tu.get("input", {}),
                    }
        elif msg.get("role") == "user":
            for block in msg.get("content", []):
                if isinstance(block, dict) and block.get("toolResult"):
                    tr = block["toolResult"]
                    tu_id = tr.get("toolUseId", "")
                    if tu_id in tool_use_map:
                        info = tool_use_map.pop(tu_id)
                        tool_calls.append({
                            "tool": info["name"], "lob": info["lob"],
                            "input": info["input"],
                            "cedar_denied": _is_cedar_denied(tr),
                        })

    if not tool_calls:
        for msg in agent.messages:
            if msg.get("role") == "assistant":
                for block in msg.get("content", []):
                    if isinstance(block, dict) and block.get("toolUse"):
                        tu = block["toolUse"]
                        lob = tu["name"].split("___")[0] if "___" in tu["name"] else "unknown"
                        tool_calls.append({"tool": tu["name"], "lob": lob, "input": tu.get("input", {}), "cedar_denied": False})

    response_text = result.message["content"][0]["text"] if result.message.get("content") else str(result)

    return json.dumps({
        "response": response_text,
        "tool_calls": tool_calls,
        "user_role": user_role,
        "user_email": user_email,
        "discovered_lobs": list(_discovered_lobs.keys()),
    })


if __name__ == "__main__":
    app.run()
