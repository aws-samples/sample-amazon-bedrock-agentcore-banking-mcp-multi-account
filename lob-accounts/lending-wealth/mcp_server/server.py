"""Lending & Wealth MCP Server — Loans, Credit, and Policy tools.

Deployed on AgentCore Runtime with MCP protocol.
Provides tools: get_loans, check_eligibility, get_credit_score, get_emi_details,
                calculate_emi, search_lending_policies
"""
import os
import json
import math
import boto3
from mcp.server.fastmcp import FastMCP
from boto3.dynamodb.conditions import Attr, Key

REGION = os.environ.get("AWS_REGION", "us-east-1")
dynamodb = boto3.resource("dynamodb", region_name=REGION)
bedrock_agent_runtime = boto3.client("bedrock-agent-runtime", region_name=REGION)
KNOWLEDGE_BASE_ID = os.environ.get("KNOWLEDGE_BASE_ID", "")

mcp = FastMCP("lending-wealth", host="0.0.0.0", stateless_http=True)


@mcp.tool()
def get_loans(customer_id: str) -> list:
    """Get all loans for a customer. Returns loan details including type, principal, rate, and status."""
    table = dynamodb.Table("Loans")
    resp = table.scan(FilterExpression=Attr("customer_id").eq(customer_id))
    items = resp.get("Items", [])
    if not items:
        return {"message": f"No active loans for customer {customer_id}"}
    return items


@mcp.tool()
def get_credit_score(customer_id: str) -> dict:
    """Get credit score and contributing factors for a customer."""
    table = dynamodb.Table("CreditScores")
    resp = table.get_item(Key={"customer_id": customer_id})
    item = resp.get("Item")
    if not item:
        return {"error": f"No credit score found for customer {customer_id}"}
    return item


@mcp.tool()
def check_eligibility(customer_id: str, amount: float, loan_type: str) -> dict:
    """Check loan eligibility for a customer based on credit score and requested amount."""
    score_data = get_credit_score(customer_id)
    if "error" in score_data:
        return {"eligible": False, "reason": "No credit history available"}

    score = int(score_data.get("score", 0))

    # Eligibility rules
    if score < 600:
        return {"eligible": False, "reason": f"Credit score {score} is below minimum threshold of 600", "credit_score": score}
    if score < 700 and amount > 25000:
        return {"eligible": False, "reason": f"Credit score {score} qualifies for max $25,000. Requested: ${amount:,.2f}", "credit_score": score}

    # Determine rate based on score
    if score >= 800:
        rate = 6.5
    elif score >= 750:
        rate = 8.5
    elif score >= 700:
        rate = 10.5
    else:
        rate = 12.5

    tenure = 36 if loan_type.lower() == "personal" else 60
    emi = calculate_emi(amount, rate, tenure)

    return {
        "eligible": True,
        "credit_score": score,
        "offered_rate": rate,
        "loan_type": loan_type,
        "amount": amount,
        "tenure_months": tenure,
        "estimated_emi": emi.get("emi"),
        "total_payment": emi.get("total_payment"),
    }


@mcp.tool()
def get_emi_details(loan_id: str) -> list:
    """Get EMI schedule for a specific loan."""
    table = dynamodb.Table("EMISchedule")
    resp = table.query(KeyConditionExpression=Key("loan_id").eq(loan_id))
    items = resp.get("Items", [])
    if not items:
        return {"error": f"No EMI schedule found for loan {loan_id}"}
    return items


@mcp.tool()
def calculate_emi(principal: float, rate: float, tenure: int) -> dict:
    """Calculate EMI for given loan parameters. Rate is annual %, tenure in months."""
    monthly_rate = rate / 12 / 100
    if monthly_rate == 0:
        emi = principal / tenure
    else:
        emi = principal * monthly_rate * math.pow(1 + monthly_rate, tenure) / (math.pow(1 + monthly_rate, tenure) - 1)
    total = emi * tenure
    return {"emi": round(emi, 2), "total_payment": round(total, 2), "total_interest": round(total - principal, 2)}


@mcp.tool()
def search_lending_policies(query: str) -> str:
    """Search the bank's lending policy documents for guidelines, eligibility criteria,
    regulatory requirements, and product terms. Use this when you need to check bank
    policies before making lending recommendations."""
    if not KNOWLEDGE_BASE_ID:
        return json.dumps({"error": "KNOWLEDGE_BASE_ID not configured"})
    resp = bedrock_agent_runtime.retrieve(
        knowledgeBaseId=KNOWLEDGE_BASE_ID,
        retrievalQuery={"text": query},
        retrievalConfiguration={"vectorSearchConfiguration": {"numberOfResults": 5}},
    )
    chunks = []
    for r in resp.get("retrievalResults", []):
        text = r.get("content", {}).get("text", "")
        source = r.get("location", {}).get("s3Location", {}).get("uri", "")
        score = r.get("score", 0)
        if text:
            chunks.append({"text": text, "source": os.path.basename(source), "score": round(score, 3)})
    return json.dumps({"results": chunks}, default=str)


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
