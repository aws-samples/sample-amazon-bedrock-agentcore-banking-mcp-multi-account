"""Seed DynamoDB tables for Lending LOB."""
import boto3

REGION = "us-east-1"
PROFILE = "lending-wealth"

session = boto3.Session(profile_name=PROFILE, region_name=REGION)
dynamodb = session.resource("dynamodb")


def create_tables():
    client = session.client("dynamodb")
    existing = client.list_tables()["TableNames"]

    tables = [
        {"name": "Loans", "pk": "loan_id"},
        {"name": "CreditScores", "pk": "customer_id"},
        {"name": "EMISchedule", "pk": "loan_id", "sk": "emi_number"},
    ]
    for t in tables:
        if t["name"] in existing:
            print(f"  Table {t['name']} already exists, skipping.")
            continue
        key_schema = [{"AttributeName": t["pk"], "KeyType": "HASH"}]
        attr_defs = [{"AttributeName": t["pk"], "AttributeType": "S"}]
        if "sk" in t:
            key_schema.append({"AttributeName": t["sk"], "KeyType": "RANGE"})
            attr_defs.append({"AttributeName": t["sk"], "AttributeType": "N"})
        client.create_table(
            TableName=t["name"],
            KeySchema=key_schema,
            AttributeDefinitions=attr_defs,
            BillingMode="PAY_PER_REQUEST",
        )
        print(f"  Created table {t['name']}")
        client.get_waiter("table_exists").wait(TableName=t["name"])


def seed_loans():
    table = dynamodb.Table("Loans")
    items = [
        {"loan_id": "L-2001", "customer_id": "C002", "type": "Auto", "principal": "25000.00", "rate": "6.5", "tenure": 60, "status": "Active", "monthly_emi": "489.15"},
        {"loan_id": "L-4001", "customer_id": "C004", "type": "Personal", "principal": "10000.00", "rate": "12.0", "tenure": 24, "status": "Delinquent", "monthly_emi": "470.73"},
        {"loan_id": "L-5001", "customer_id": "C005", "type": "Mortgage", "principal": "350000.00", "rate": "4.5", "tenure": 360, "status": "Active", "monthly_emi": "1773.40"},
        {"loan_id": "L-8001", "customer_id": "C008", "type": "HomeEquity", "principal": "75000.00", "rate": "5.5", "tenure": 120, "status": "Active", "monthly_emi": "814.45"},
    ]
    with table.batch_writer() as batch:
        for item in items:
            batch.put_item(Item=item)
    print(f"  Seeded {len(items)} loans")


def seed_credit_scores():
    table = dynamodb.Table("CreditScores")
    items = [
        {"customer_id": "C001", "score": 780, "last_updated": "2026-02-01", "factors": ["Long credit history", "Low utilization", "No missed payments"]},
        {"customer_id": "C002", "score": 710, "last_updated": "2026-02-01", "factors": ["Active auto loan", "Moderate utilization", "Good payment history"]},
        {"customer_id": "C003", "score": 750, "last_updated": "2026-02-01", "factors": ["No active loans", "Consistent payments", "High savings"]},
        {"customer_id": "C004", "score": 580, "last_updated": "2026-02-01", "factors": ["Missed payments", "Delinquent loan", "High utilization"]},
        {"customer_id": "C005", "score": 820, "last_updated": "2026-02-01", "factors": ["Excellent history", "Diverse credit mix", "Low utilization"]},
        {"customer_id": "C006", "score": 650, "last_updated": "2026-02-01", "factors": ["Short credit history", "Limited credit mix", "No missed payments"]},
        {"customer_id": "C008", "score": 790, "last_updated": "2026-02-01", "factors": ["Long history", "Active home equity", "Consistent payments"]},
    ]
    with table.batch_writer() as batch:
        for item in items:
            batch.put_item(Item=item)
    print(f"  Seeded {len(items)} credit scores")


def seed_emi_schedule():
    table = dynamodb.Table("EMISchedule")
    # Sample EMI schedule for C004's delinquent loan
    items = [
        {"loan_id": "L-4001", "emi_number": 1, "amount": "470.73", "due_date": "2025-11-15", "status": "Paid"},
        {"loan_id": "L-4001", "emi_number": 2, "amount": "470.73", "due_date": "2025-12-15", "status": "Missed"},
        {"loan_id": "L-4001", "emi_number": 3, "amount": "470.73", "due_date": "2026-01-15", "status": "Missed"},
        {"loan_id": "L-4001", "emi_number": 4, "amount": "470.73", "due_date": "2026-02-15", "status": "Overdue"},
        # C002 auto loan
        {"loan_id": "L-2001", "emi_number": 1, "amount": "489.15", "due_date": "2025-08-22", "status": "Paid"},
        {"loan_id": "L-2001", "emi_number": 2, "amount": "489.15", "due_date": "2025-09-22", "status": "Paid"},
        {"loan_id": "L-2001", "emi_number": 3, "amount": "489.15", "due_date": "2025-10-22", "status": "Paid"},
    ]
    with table.batch_writer() as batch:
        for item in items:
            batch.put_item(Item=item)
    print(f"  Seeded {len(items)} EMI records")


if __name__ == "__main__":
    print("=== Lending LOB: Creating tables ===")
    create_tables()
    print("=== Lending LOB: Seeding data ===")
    seed_loans()
    seed_credit_scores()
    seed_emi_schedule()
    print("=== Lending LOB: Done ===")
