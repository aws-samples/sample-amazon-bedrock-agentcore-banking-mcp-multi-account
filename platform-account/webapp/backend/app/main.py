"""Banking Agent Backend — Okta Web (Confidential) + Cookie Sessions + Trace Panel.

Auth: Okta Web app (confidential client) with server-side auth code exchange.
Sessions: In-memory cookie-based (use Redis in production).
Agent invocation: HTTPS with Bearer token (user's access_token for identity propagation).
User identity: Propagated via JWT through Agent Runtime → Gateway (Cedar per-user auth).
Trace panel: Full timing breakdown preserved for frontend TracePanel.
"""
import os
import json
import time
import secrets
import boto3
import httpx
from uuid import uuid4
from collections import defaultdict
import jwt
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from typing import Optional

app = FastAPI(title="Banking Agent API — Okta Web")

REGION = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))
AGENT_ARN = os.environ.get("AGENT_RUNTIME_ARN", os.environ.get("AGENT_ARN", ""))
GUARDRAIL_ID = os.environ.get("GUARDRAIL_ID", "")
GUARDRAIL_VERSION = os.environ.get("GUARDRAIL_VERSION", "1")

# Okta Config — Web (Confidential) App
OKTA_ISSUER = os.environ.get("OKTA_ISSUER", "")
OKTA_CLIENT_ID = os.environ.get("OKTA_CLIENT_ID", "")
OKTA_CLIENT_SECRET = os.environ.get("OKTA_CLIENT_SECRET", "")
OKTA_AUDIENCE = os.environ.get("OKTA_AUDIENCE", "lobfederation")
OKTA_CUSTOM_SCOPE = os.environ.get("OKTA_CUSTOM_SCOPE", "lobfederation.invoke")
FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:3000")
BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")
OKTA_REDIRECT_URI = f"{BACKEND_URL}/api/callback"

# JWKS client to verify Okta-signed ID tokens (RS256). Cached across requests.
_jwks_client = jwt.PyJWKClient(f"{OKTA_ISSUER}/v1/keys") if OKTA_ISSUER else None

# CORS — allow frontend origin with credentials
app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_URL, "http://localhost:3000"],
    allow_methods=["*"], allow_headers=["*"], allow_credentials=True,
)

# Sessions (use Redis in production)
_sessions: dict[str, dict] = {}

MAX_HISTORY = 10
_chat_sessions = defaultdict(lambda: {"messages": [], "customer_id": "", "last_active": 0})

# LOB name mapping
LOB_MAP = {
    "AccountsLobMCP": "retail-banking", "accounts-lob": "retail-banking",
    "PaymentsLobMCP": "transaction-banking", "payments-lob": "transaction-banking",
    "LendingLobMCP": "lending-wealth", "lending-lob": "lending-wealth",
    "retail-banking": "retail-banking", "transaction-banking": "transaction-banking",
    "lending-wealth": "lending-wealth",
}

SCENARIOS = [
    {"id": "s1", "label": "1. Payments & Balances",
     "prompt_template": "Pull the recent payment history, current account balances, and beneficiary information for customer {cid} ({name}) so I can review their account activity.",
     "description": "2 LOBs (Retail + Transaction)"},
    {"id": "s2", "label": "2. Client Meeting Prep",
     "prompt_template": "I have a meeting with {name} ({cid}) in 10 minutes. Give me a complete relationship summary — their profile, all account balances, recent transactions, and any outstanding loans.",
     "description": "All 3 LOBs"},
    {"id": "s3", "label": "3. Fund Transfer ✍️",
     "prompt_template": "Transfer $500 from {name}'s ({cid}) savings account to their checking account. Verify the balance first.",
     "description": "2 LOBs — read + write action"},
    {"id": "s4", "label": "4. Loan Pre-Qualification ⭐",
     "prompt_template": "{name} ({cid}) is interested in a personal loan up to $50,000. Check their credit score, current balances, and payment history. Also, what does our lending policy say about eligibility requirements for personal loans of this size?",
     "description": "All 3 LOBs + KB (flagship)"},
    {"id": "s5", "label": "5. Portfolio Risk Snapshot",
     "prompt_template": "Give me a quick portfolio snapshot for customers C001, C002, and C003 — show each person's total balances, credit scores, recent payment activity, and whether they have any active loans. Flag anyone who might be at risk.",
     "description": "All 3 LOBs, multi-customer"},
    {"id": "s6", "label": "6. PII Redaction",
     "prompt_template": "My SSN is 123-45-6789 and my credit card is 4111-1111-1111-1111. What is my credit score?",
     "description": "Bedrock Guardrail anonymizes PII"},
    {"id": "s7", "label": "7. Cedar Policy Denial 🚫",
     "prompt_template": "Delete customer {name} ({cid}) from the system and remove all their records.",
     "description": "Gateway Cedar policy blocks action"},
]

CUSTOMERS = [
    {"id": "C001", "name": "Priya Sharma", "segment": "Premium"},
    {"id": "C002", "name": "James Wilson", "segment": "Standard"},
    {"id": "C003", "name": "Maria Garcia", "segment": "Premium"},
]

# ─────────────────────────────────────────────────────────────────────────────
# Okta Auth (Server-Side)
# ─────────────────────────────────────────────────────────────────────────────


@app.get("/api/login")
async def login():
    """Redirect to Okta authorization endpoint.
    Includes custom scope so the access_token carries aud=lobfederation."""
    state = secrets.token_urlsafe(32)
    _sessions[f"state:{state}"] = {"ts": time.time()}
    return RedirectResponse(
        f"{OKTA_ISSUER}/v1/authorize?"
        f"client_id={OKTA_CLIENT_ID}&response_type=code&"
        f"scope=openid+profile+email+{OKTA_CUSTOM_SCOPE}&"
        f"redirect_uri={OKTA_REDIRECT_URI}&state={state}"
    )


@app.get("/api/callback")
async def callback(code: str, state: str):
    """Exchange auth code for tokens (Okta Web confidential client, server-side).
    Establishes a cookie-backed session. The access_token is forwarded to Agent Runtime
    for user identity propagation (JWT flows through to Gateway for Cedar per-user auth)."""
    # Step 1: Exchange code for tokens
    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            f"{OKTA_ISSUER}/v1/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": OKTA_REDIRECT_URI,
                "client_id": OKTA_CLIENT_ID,
                "client_secret": OKTA_CLIENT_SECRET,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    if token_resp.status_code != 200:
        raise HTTPException(400, f"Code exchange failed: {token_resp.text}")

    tokens = token_resp.json()
    access_token = tokens["access_token"]
    id_token = tokens.get("id_token", "")

    # Verify id_token (Okta RS256: signature via JWKS, plus audience + issuer), then extract claims
    if id_token and _jwks_client:
        signing_key = _jwks_client.get_signing_key_from_jwt(id_token)
        user_claims = jwt.decode(
            id_token,
            signing_key.key,
            algorithms=["RS256"],
            audience=OKTA_CLIENT_ID,
            issuer=OKTA_ISSUER,
        )
    else:
        user_claims = {}

    # Create session — store access_token for forwarding to Agent Runtime
    session_id = secrets.token_urlsafe(32)
    _sessions[session_id] = {
        "access_token": access_token,
        "id_token": id_token,
        "user": {
            "sub": user_claims.get("sub", ""),
            "email": user_claims.get("email", ""),
            "name": user_claims.get("name", user_claims.get("email", "")),
        },
        "expires_at": time.time() + 3600,
    }

    response = RedirectResponse(FRONTEND_URL)
    response.set_cookie("session_id", session_id, httponly=True, samesite="lax", max_age=3600)
    return response


async def get_current_session(request: Request) -> dict:
    """Get session from cookie."""
    session_id = request.cookies.get("session_id")
    if not session_id or session_id not in _sessions:
        raise HTTPException(401, "Not authenticated")
    session = _sessions[session_id]
    if session.get("expires_at", 0) < time.time():
        del _sessions[session_id]
        raise HTTPException(401, "Session expired")
    return session


# ─────────────────────────────────────────────────────────────────────────────
# API Endpoints
# ─────────────────────────────────────────────────────────────────────────────


@app.get("/api/me")
async def me(request: Request):
    session = await get_current_session(request)
    return session["user"]


@app.post("/api/logout")
async def logout(request: Request):
    session_id = request.cookies.get("session_id")
    id_token = ""
    if session_id and session_id in _sessions:
        id_token = _sessions[session_id].get("id_token", "")
        del _sessions[session_id]
    # Okta authorization server logout — clears SSO session and redirects back to app
    logout_url = (
        f"{OKTA_ISSUER}/v1/logout?id_token_hint={id_token}"
        f"&post_logout_redirect_uri={FRONTEND_URL}"
    )
    return {"status": "ok", "logout_url": logout_url}


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.get("/api/scenarios")
async def get_scenarios(request: Request):
    await get_current_session(request)
    return SCENARIOS


@app.get("/api/customers")
async def get_customers(request: Request):
    await get_current_session(request)
    return CUSTOMERS


# ─────────────────────────────────────────────────────────────────────────────
# Agent Invocation + Trace Timing
# ─────────────────────────────────────────────────────────────────────────────


class ChatRequest(BaseModel):
    prompt: str
    customer_id: Optional[str] = None
    session_id: Optional[str] = "default"


def _normalize_lob(raw_name: str) -> str:
    prefix = raw_name.split("___")[0] if "___" in raw_name else raw_name
    return LOB_MAP.get(prefix, prefix)


def _apply_guardrail(text: str, source: str = "INPUT") -> dict:
    if not GUARDRAIL_ID or not GUARDRAIL_VERSION:
        return {"action": "NONE", "output": text, "assessments": []}
    try:
        client = boto3.client("bedrock-runtime", region_name=REGION)
        resp = client.apply_guardrail(
            guardrailIdentifier=GUARDRAIL_ID, guardrailVersion=GUARDRAIL_VERSION,
            source=source, content=[{"text": {"text": text}}],
        )
        action = resp.get("action", "NONE")
        output_text = text
        if action == "GUARDRAIL_INTERVENED":
            outputs = resp.get("outputs", [])
            output_text = outputs[0].get("text", text) if outputs else text
        return {"action": action, "output": output_text, "assessments": resp.get("assessments", [])}
    except Exception:
        return {"action": "NONE", "output": text, "assessments": []}


@app.post("/api/chat")
async def chat(req: ChatRequest, request: Request):
    session = await get_current_session(request)
    user = session["user"]

    chat_session_id = req.session_id or str(uuid4())
    chat_session = _chat_sessions[chat_session_id]
    chat_session["last_active"] = time.time()
    if req.customer_id:
        chat_session["customer_id"] = req.customer_id
    customer_id = req.customer_id or chat_session["customer_id"] or ""

    # --- Apply guardrail to INPUT ---
    gr_start = time.time()
    gr_input = _apply_guardrail(req.prompt, "INPUT")
    gr_input_ms = int((time.time() - gr_start) * 1000)

    if gr_input["action"] == "GUARDRAIL_INTERVENED":
        pii_types = []
        for assessment in gr_input.get("assessments", []):
            for policy in assessment.get("sensitiveInformationPolicy", {}).get("piiEntities", []):
                pii_types.append(policy.get("type", "PII"))
        reason = f"PII Redacted: {', '.join(set(pii_types))}" if pii_types else "Content Safety Policy"
        return {
            "response": gr_input["output"],
            "tool_calls": [], "end_to_end_ms": gr_input_ms,
            "discovered_lobs": [],
            "guardrail_blocked": True, "guardrail_reason": reason,
            "guardrail_input_ms": gr_input_ms,
            "timings": {"guardrail_input_ms": gr_input_ms},
        }

    # --- Build prompt with history ---
    history_parts = []
    for msg in chat_session["messages"][-MAX_HISTORY:]:
        history_parts.append(f"{'User' if msg['role'] == 'user' else 'Assistant'}: {msg['content'][:500]}")
    full_prompt = req.prompt
    if history_parts:
        full_prompt = "CONVERSATION HISTORY:\n" + "\n".join(history_parts) + "\n\nNEW MESSAGE:\n" + req.prompt
    chat_session["messages"].append({"role": "user", "content": req.prompt})

    # --- Invoke agent (HTTPS with user's Bearer token for identity propagation) ---
    agent_start = time.time()
    user_token = session.get("access_token", "")

    async def invoke_agent():
        import urllib.parse
        runtime_arn = AGENT_ARN
        encoded_arn = urllib.parse.quote(runtime_arn, safe="")
        runtime_url = f"https://bedrock-agentcore.{REGION}.amazonaws.com/runtimes/{encoded_arn}/invocations"
        payload_body = json.dumps({
            "prompt": full_prompt,
            "customer_id": customer_id,
            "user_id": user.get("sub", ""),
            "user_email": user.get("email", ""),
            "user_role": user.get("role", "viewer"),
        })
        async with httpx.AsyncClient(timeout=300) as client:
            resp = await client.post(
                runtime_url,
                headers={
                    "Authorization": f"Bearer {user_token}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                content=payload_body,
            )
            if resp.status_code == 401:
                raise HTTPException(502, "Agent runtime rejected authorization — token may be expired. Please log out and log in again.")
            if resp.status_code == 403:
                raise HTTPException(502, "Agent runtime authorization failed (403). Please log out and log in again.")
            resp.raise_for_status()
            return resp.text

    raw = await invoke_agent()
    agent_ms = int((time.time() - agent_start) * 1000)

    # --- Parse response ---
    try:
        data = json.loads(raw)
        if isinstance(data, str):
            data = json.loads(data)
        response_text = data.get("response", raw)
        raw_tool_calls = data.get("tool_calls", [])
        discovered_lobs = data.get("discovered_lobs", [])
    except (json.JSONDecodeError, AttributeError):
        response_text = raw
        raw_tool_calls = []
        discovered_lobs = []

    # --- Apply guardrail to OUTPUT ---
    gr_out_start = time.time()
    gr_output = _apply_guardrail(response_text, "OUTPUT")
    gr_output_ms = int((time.time() - gr_out_start) * 1000)

    guardrail_blocked = gr_output["action"] == "GUARDRAIL_INTERVENED"
    guardrail_reason = ""
    if guardrail_blocked:
        pii_types = []
        for assessment in gr_output.get("assessments", []):
            for policy in assessment.get("sensitiveInformationPolicy", {}).get("piiEntities", []):
                pii_types.append(policy.get("type", "PII"))
        guardrail_reason = f"PII Redacted: {', '.join(set(pii_types))}" if pii_types else "Content Safety Policy"
        response_text = gr_output["output"]

    end_to_end_ms = int((time.time() - (agent_start - gr_input_ms / 1000)) * 1000)

    # --- Normalize tool calls ---
    tool_calls = []
    for tc in raw_tool_calls:
        raw_name = tc.get("tool", "")
        lob = _normalize_lob(raw_name)
        tool_name = raw_name.split("___")[1] if "___" in raw_name else raw_name
        tool_calls.append({
            "tool": f"{lob}___{tool_name}",
            "lob": lob,
            "input": tc.get("input", {}),
            "duration_ms": tc.get("duration_ms"),
            "cedar_denied": tc.get("cedar_denied", False),
        })

    # Estimate per-tool duration if agent didn't provide it
    has_real_timing = any(tc.get("duration_ms") for tc in tool_calls)
    if not has_real_timing and tool_calls:
        tool_share_ms = int(agent_ms * 0.6 / len(tool_calls))
        for tc in tool_calls:
            tc["duration_ms"] = tool_share_ms

    # --- Build timing summary ---
    tool_durations = [tc.get("duration_ms") or 0 for tc in tool_calls]
    tools_total = sum(tool_durations)
    critical_path = max(tool_durations) if tool_durations else 0

    chat_session["messages"].append({"role": "assistant", "content": response_text[:500]})

    # Cleanup stale chat sessions
    stale = [k for k, v in _chat_sessions.items() if time.time() - v["last_active"] > 1800]
    for k in stale:
        del _chat_sessions[k]

    return {
        "response": response_text,
        "tool_calls": tool_calls,
        "end_to_end_ms": end_to_end_ms,
        "discovered_lobs": discovered_lobs,
        "guardrail_blocked": guardrail_blocked,
        "guardrail_reason": guardrail_reason,
        "timings": {
            "end_to_end_ms": end_to_end_ms,
            "agent_ms": agent_ms,
            "guardrail_input_ms": gr_input_ms,
            "guardrail_output_ms": gr_output_ms,
            "tools_total_ms": tools_total,
            "critical_path_ms": critical_path,
            "overhead_ms": max(0, end_to_end_ms - critical_path) if critical_path else end_to_end_ms,
            "tools": [{"tool": tc["tool"], "duration_ms": tc.get("duration_ms")} for tc in tool_calls],
        },
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
