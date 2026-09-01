"""Accounts LOB MCP Server — Core Banking tools.

Deployed on AgentCore Runtime with MCP protocol.
Provides tools: get_customer, get_accounts, get_balance, get_profile
"""
import os
import boto3
from mcp.server.fastmcp import FastMCP
from boto3.dynamodb.conditions import Key, Attr

REGION = os.environ.get("AWS_REGION", "us-east-1")
dynamodb = boto3.resource("dynamodb", region_name=REGION)

mcp = FastMCP("retail-banking", host="0.0.0.0", stateless_http=True)


@mcp.tool()
def get_customer(customer_id: str) -> dict:
    """Get customer profile by ID. Returns name, email, phone, and segment."""
    table = dynamodb.Table("Customers")
    resp = table.get_item(Key={"customer_id": customer_id})
    item = resp.get("Item")
    if not item:
        return {"error": f"Customer {customer_id} not found"}
    return item


@mcp.tool()
def get_accounts(customer_id: str) -> list:
    """List all bank accounts for a customer. Returns account IDs, types, and status."""
    table = dynamodb.Table("Accounts")
    resp = table.scan(FilterExpression=Attr("customer_id").eq(customer_id))
    items = resp.get("Items", [])
    if not items:
        return {"error": f"No accounts found for customer {customer_id}"}
    return items


@mcp.tool()
def get_balance(account_id: str) -> dict:
    """Get current balance for a specific bank account."""
    table = dynamodb.Table("Balances")
    resp = table.get_item(Key={"account_id": account_id})
    item = resp.get("Item")
    if not item:
        return {"error": f"Balance not found for account {account_id}"}
    return item


@mcp.tool()
def get_profile(customer_id: str) -> dict:
    """Get full customer profile including all accounts and their balances."""
    customer = get_customer(customer_id)
    if "error" in customer:
        return customer

    accounts = get_accounts(customer_id)
    if isinstance(accounts, dict) and "error" in accounts:
        accounts = []

    enriched = []
    for acct in accounts:
        balance = get_balance(acct["account_id"])
        enriched.append({**acct, "balance": balance if "error" not in balance else None})

    return {"customer": customer, "accounts": enriched}


@mcp.tool()
def update_balance(account_id: str, amount: float, operation: str = "debit") -> dict:
    """Update account balance after a transfer. Operation is 'debit' (subtract) or 'credit' (add)."""
    from decimal import Decimal
    from datetime import datetime
    table = dynamodb.Table("Balances")
    resp = table.get_item(Key={"account_id": account_id})
    item = resp.get("Item")
    if not item:
        return {"error": f"Account {account_id} not found"}
    current_bal = Decimal(item.get("available", "0"))
    change = Decimal(str(amount))
    if operation == "debit":
        if current_bal < change:
            return {"error": f"Insufficient funds. Available: {current_bal}, requested: {change}"}
        new_balance = current_bal - change
    else:
        new_balance = current_bal + change
    table.update_item(
        Key={"account_id": account_id},
        UpdateExpression="SET available = :a, #cur = :a, as_of = :d",
        ExpressionAttributeNames={"#cur": "current"},
        ExpressionAttributeValues={":a": str(new_balance), ":d": datetime.now().strftime("%Y-%m-%d")},
    )
    return {"account_id": account_id, "operation": operation, "amount": str(amount), "new_balance": str(new_balance)}


@mcp.tool()
def delete_customer(customer_id: str) -> dict:
    """Delete a customer and all their records from the system. This is a destructive operation."""
    # This tool exists but is blocked by Cedar policy on the Gateway.
    # If Cedar is bypassed, this would return an error anyway (demo safety).
    return {"error": "Operation blocked — delete_customer requires elevated privileges."}


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
