"""Seed DynamoDB tables for Payments LOB."""
import boto3

REGION = "us-east-1"
PROFILE = "transaction-banking"

session = boto3.Session(profile_name=PROFILE, region_name=REGION)
dynamodb = session.resource("dynamodb")


def create_tables():
    client = session.client("dynamodb")
    existing = client.list_tables()["TableNames"]

    tables = {
        "Payments": {"pk": "payment_id"},
        "Beneficiaries": {"pk": "beneficiary_id"},
    }
    for name, keys in tables.items():
        if name in existing:
            print(f"  Table {name} already exists, skipping.")
            continue
        client.create_table(
            TableName=name,
            KeySchema=[{"AttributeName": keys["pk"], "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": keys["pk"], "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        print(f"  Created table {name}")
        client.get_waiter("table_exists").wait(TableName=name)


def seed_payments():
    table = dynamodb.Table("Payments")
    items = [
        # C001 payments
        {"payment_id": "P-1001", "customer_id": "C001", "from_account": "CA-1001", "to_account": "EXT-9001", "amount": "150.00", "date": "2026-02-20", "status": "Completed", "description": "Electric bill"},
        {"payment_id": "P-1002", "customer_id": "C001", "from_account": "CA-1001", "to_account": "EXT-9002", "amount": "85.00", "date": "2026-02-18", "status": "Completed", "description": "Internet bill"},
        # C002 payments
        {"payment_id": "P-2001", "customer_id": "C002", "from_account": "CA-2001", "to_account": "EXT-9003", "amount": "450.00", "date": "2026-02-21", "status": "Completed", "description": "Auto loan EMI"},
        {"payment_id": "P-2002", "customer_id": "C002", "from_account": "CA-2001", "to_account": "EXT-9004", "amount": "120.00", "date": "2026-02-19", "status": "Completed", "description": "Insurance premium"},
        {"payment_id": "P-2003", "customer_id": "C002", "from_account": "SA-2001", "to_account": "CA-2001", "amount": "1000.00", "date": "2026-02-15", "status": "Completed", "description": "Internal transfer"},
        # C003 payments — consistent history for loan eligibility
        {"payment_id": "P-3001", "customer_id": "C003", "from_account": "CA-3001", "to_account": "EXT-9005", "amount": "200.00", "date": "2026-02-22", "status": "Completed", "description": "Utility bill"},
        {"payment_id": "P-3002", "customer_id": "C003", "from_account": "CA-3001", "to_account": "EXT-9006", "amount": "1500.00", "date": "2026-02-10", "status": "Completed", "description": "Rent payment"},
        {"payment_id": "P-3003", "customer_id": "C003", "from_account": "CA-3001", "to_account": "EXT-9006", "amount": "1500.00", "date": "2026-01-10", "status": "Completed", "description": "Rent payment"},
        # C004 — delinquent payment history
        {"payment_id": "P-4001", "customer_id": "C004", "from_account": "SA-4001", "to_account": "EXT-9007", "amount": "350.00", "date": "2026-01-15", "status": "Failed", "description": "Loan EMI - insufficient funds"},
        {"payment_id": "P-4002", "customer_id": "C004", "from_account": "SA-4001", "to_account": "EXT-9007", "amount": "350.00", "date": "2025-12-15", "status": "Failed", "description": "Loan EMI - insufficient funds"},
        # C005 — high net worth
        {"payment_id": "P-5001", "customer_id": "C005", "from_account": "CA-5001", "to_account": "EXT-9008", "amount": "3500.00", "date": "2026-02-20", "status": "Completed", "description": "Mortgage payment"},
    ]
    with table.batch_writer() as batch:
        for item in items:
            batch.put_item(Item=item)
    print(f"  Seeded {len(items)} payments")


def seed_beneficiaries():
    table = dynamodb.Table("Beneficiaries")
    items = [
        {"beneficiary_id": "B-1001", "customer_id": "C001", "name": "City Power Co", "account_number": "EXT-9001", "bank": "Utility Bank"},
        {"beneficiary_id": "B-1002", "customer_id": "C001", "name": "NetConnect ISP", "account_number": "EXT-9002", "bank": "Tech Bank"},
        {"beneficiary_id": "B-2001", "customer_id": "C002", "name": "Auto Finance Corp", "account_number": "EXT-9003", "bank": "Finance Bank"},
        {"beneficiary_id": "B-2002", "customer_id": "C002", "name": "SafeGuard Insurance", "account_number": "EXT-9004", "bank": "Insurance Bank"},
        {"beneficiary_id": "B-3001", "customer_id": "C003", "name": "Metro Utilities", "account_number": "EXT-9005", "bank": "Utility Bank"},
        {"beneficiary_id": "B-3002", "customer_id": "C003", "name": "Sunrise Apartments", "account_number": "EXT-9006", "bank": "Property Bank"},
    ]
    with table.batch_writer() as batch:
        for item in items:
            batch.put_item(Item=item)
    print(f"  Seeded {len(items)} beneficiaries")


if __name__ == "__main__":
    print("=== Payments LOB: Creating tables ===")
    create_tables()
    print("=== Payments LOB: Seeding data ===")
    seed_payments()
    seed_beneficiaries()
    print("=== Payments LOB: Done ===")
