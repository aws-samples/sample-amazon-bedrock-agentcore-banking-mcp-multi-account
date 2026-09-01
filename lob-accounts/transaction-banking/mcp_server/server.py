"""Payments LOB MCP Server — Payments & Transfers tools.

Deployed on AgentCore Runtime with MCP protocol.
Provides tools: get_payments, transfer_funds, get_beneficiaries, schedule_payment
"""
import os
import uuid
from datetime import datetime
import boto3
from mcp.server.fastmcp import FastMCP
from boto3.dynamodb.conditions import Attr

REGION = os.environ.get("AWS_REGION", "us-east-1")
dynamodb = boto3.resource("dynamodb", region_name=REGION)

mcp = FastMCP("transaction-banking", host="0.0.0.0", stateless_http=True)


@mcp.tool()
def get_payments(customer_id: str, days: int = 30) -> list:
    """Get payment history for a customer. Returns recent payments with amounts, dates, and status."""
    table = dynamodb.Table("Payments")
    resp = table.scan(FilterExpression=Attr("customer_id").eq(customer_id))
    items = resp.get("Items", [])
    if not items:
        return {"error": f"No payments found for customer {customer_id}"}
    return sorted(items, key=lambda x: x.get("date", ""), reverse=True)


@mcp.tool()
def transfer_funds(from_account: str, to_account: str, amount: float) -> dict:
    """Transfer funds between accounts. Creates a payment record and instructs the agent to update balances via the retail-banking update_balance tool."""
    table = dynamodb.Table("Payments")
    payment_id = f"P-{uuid.uuid4().hex[:6].upper()}"
    item = {
        "payment_id": payment_id,
        "customer_id": "SYSTEM",
        "from_account": from_account,
        "to_account": to_account,
        "amount": str(amount),
        "date": datetime.now().strftime("%Y-%m-%d"),
        "status": "Completed",
        "description": f"Fund transfer from {from_account} to {to_account}",
    }
    table.put_item(Item=item)
    return {"status": "success", "payment_id": payment_id, "amount": amount,
            "from": from_account, "to": to_account,
            "action_required": "Call update_balance to debit from_account and credit to_account"}


@mcp.tool()
def get_beneficiaries(customer_id: str) -> list:
    """List registered beneficiaries for a customer."""
    table = dynamodb.Table("Beneficiaries")
    resp = table.scan(FilterExpression=Attr("customer_id").eq(customer_id))
    items = resp.get("Items", [])
    if not items:
        return {"error": f"No beneficiaries found for customer {customer_id}"}
    return items


@mcp.tool()
def schedule_payment(customer_id: str, to_account: str, amount: float, date: str) -> dict:
    """Schedule a future payment for a customer."""
    table = dynamodb.Table("Payments")
    payment_id = f"P-{uuid.uuid4().hex[:6].upper()}"
    item = {
        "payment_id": payment_id,
        "customer_id": customer_id,
        "from_account": "DEFAULT",
        "to_account": to_account,
        "amount": str(amount),
        "date": date,
        "status": "Scheduled",
        "description": f"Scheduled payment to {to_account}",
    }
    table.put_item(Item=item)
    return {"status": "scheduled", "payment_id": payment_id, "amount": amount, "date": date}


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
