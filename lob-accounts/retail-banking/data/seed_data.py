"""Seed DynamoDB tables for Accounts LOB."""
import boto3
import sys

REGION = "us-east-1"
PROFILE = "retail-banking"

session = boto3.Session(profile_name=PROFILE, region_name=REGION)
dynamodb = session.resource("dynamodb")


def create_tables():
    client = session.client("dynamodb")
    existing = client.list_tables()["TableNames"]

    tables = {
        "Customers": {"pk": "customer_id"},
        "Accounts": {"pk": "account_id"},
        "Balances": {"pk": "account_id"},
    }

    for name, keys in tables.items():
        if name in existing:
            print(f"  Table {name} already exists, skipping creation.")
            continue
        client.create_table(
            TableName=name,
            KeySchema=[{"AttributeName": keys["pk"], "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": keys["pk"], "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        print(f"  Created table {name}")
        client.get_waiter("table_exists").wait(TableName=name)


def seed_customers():
    table = dynamodb.Table("Customers")
    items = [
        {"customer_id": "C001", "name": "Priya Sharma", "email": "priya.sharma@example.com", "phone": "+1-555-0101", "segment": "Premium"},
        {"customer_id": "C002", "name": "James Wilson", "email": "james.wilson@example.com", "phone": "+1-555-0102", "segment": "Standard"},
        {"customer_id": "C003", "name": "Maria Garcia", "email": "maria.garcia@example.com", "phone": "+1-555-0103", "segment": "Premium"},
        {"customer_id": "C004", "name": "Robert Chen", "email": "robert.chen@example.com", "phone": "+1-555-0104", "segment": "Standard"},
        {"customer_id": "C005", "name": "Aisha Patel", "email": "aisha.patel@example.com", "phone": "+1-555-0105", "segment": "Gold"},
        {"customer_id": "C006", "name": "David Kim", "email": "david.kim@example.com", "phone": "+1-555-0106", "segment": "Standard"},
        {"customer_id": "C007", "name": "Sarah Johnson", "email": "sarah.johnson@example.com", "phone": "+1-555-0107", "segment": "New"},
        {"customer_id": "C008", "name": "Michael Brown", "email": "michael.brown@example.com", "phone": "+1-555-0108", "segment": "Premium"},
    ]
    with table.batch_writer() as batch:
        for item in items:
            batch.put_item(Item=item)
    print(f"  Seeded {len(items)} customers")


def seed_accounts():
    table = dynamodb.Table("Accounts")
    items = [
        # C001 - Priya Sharma
        {"account_id": "SA-1001", "customer_id": "C001", "type": "Savings", "status": "Active", "opened_date": "2020-03-15"},
        {"account_id": "CA-1001", "customer_id": "C001", "type": "Checking", "status": "Active", "opened_date": "2020-03-15"},
        # C002 - James Wilson
        {"account_id": "SA-2001", "customer_id": "C002", "type": "Savings", "status": "Active", "opened_date": "2021-07-22"},
        {"account_id": "CA-2001", "customer_id": "C002", "type": "Checking", "status": "Active", "opened_date": "2021-07-22"},
        # C003 - Maria Garcia
        {"account_id": "SA-3001", "customer_id": "C003", "type": "Savings", "status": "Active", "opened_date": "2019-11-01"},
        {"account_id": "CA-3001", "customer_id": "C003", "type": "Checking", "status": "Active", "opened_date": "2019-11-01"},
        # C004 - Robert Chen
        {"account_id": "SA-4001", "customer_id": "C004", "type": "Savings", "status": "Active", "opened_date": "2022-01-10"},
        # C005 - Aisha Patel
        {"account_id": "SA-5001", "customer_id": "C005", "type": "Savings", "status": "Active", "opened_date": "2018-05-20"},
        {"account_id": "CA-5001", "customer_id": "C005", "type": "Checking", "status": "Active", "opened_date": "2018-05-20"},
        {"account_id": "FD-5001", "customer_id": "C005", "type": "FixedDeposit", "status": "Active", "opened_date": "2019-01-15"},
        # C006 - David Kim
        {"account_id": "SA-6001", "customer_id": "C006", "type": "Savings", "status": "Active", "opened_date": "2023-03-05"},
        # C007 - Sarah Johnson
        {"account_id": "SA-7001", "customer_id": "C007", "type": "Savings", "status": "Active", "opened_date": "2025-12-01"},
        # C008 - Michael Brown
        {"account_id": "SA-8001", "customer_id": "C008", "type": "Savings", "status": "Active", "opened_date": "2017-09-10"},
        {"account_id": "CA-8001", "customer_id": "C008", "type": "Checking", "status": "Active", "opened_date": "2017-09-10"},
    ]
    with table.batch_writer() as batch:
        for item in items:
            batch.put_item(Item=item)
    print(f"  Seeded {len(items)} accounts")


def seed_balances():
    table = dynamodb.Table("Balances")
    items = [
        {"account_id": "SA-1001", "available": "25430.00", "current": "25430.00", "currency": "USD", "as_of": "2026-02-23"},
        {"account_id": "CA-1001", "available": "3200.50", "current": "3200.50", "currency": "USD", "as_of": "2026-02-23"},
        {"account_id": "SA-2001", "available": "8200.00", "current": "8200.00", "currency": "USD", "as_of": "2026-02-23"},
        {"account_id": "CA-2001", "available": "1500.75", "current": "1500.75", "currency": "USD", "as_of": "2026-02-23"},
        {"account_id": "SA-3001", "available": "45000.00", "current": "45000.00", "currency": "USD", "as_of": "2026-02-23"},
        {"account_id": "CA-3001", "available": "5200.00", "current": "5200.00", "currency": "USD", "as_of": "2026-02-23"},
        {"account_id": "SA-4001", "available": "1200.00", "current": "1200.00", "currency": "USD", "as_of": "2026-02-23"},
        {"account_id": "SA-5001", "available": "120000.00", "current": "120000.00", "currency": "USD", "as_of": "2026-02-23"},
        {"account_id": "CA-5001", "available": "15000.00", "current": "15000.00", "currency": "USD", "as_of": "2026-02-23"},
        {"account_id": "FD-5001", "available": "50000.00", "current": "50000.00", "currency": "USD", "as_of": "2026-02-23"},
        {"account_id": "SA-6001", "available": "3500.00", "current": "3500.00", "currency": "USD", "as_of": "2026-02-23"},
        {"account_id": "SA-7001", "available": "500.00", "current": "500.00", "currency": "USD", "as_of": "2026-02-23"},
        {"account_id": "SA-8001", "available": "67000.00", "current": "67000.00", "currency": "USD", "as_of": "2026-02-23"},
        {"account_id": "CA-8001", "available": "8500.00", "current": "8500.00", "currency": "USD", "as_of": "2026-02-23"},
    ]
    with table.batch_writer() as batch:
        for item in items:
            batch.put_item(Item=item)
    print(f"  Seeded {len(items)} balances")


if __name__ == "__main__":
    print("=== Accounts LOB: Creating tables ===")
    create_tables()
    print("=== Accounts LOB: Seeding data ===")
    seed_customers()
    seed_accounts()
    seed_balances()
    print("=== Accounts LOB: Done ===")
