from aws_cdk import (
    Stack, RemovalPolicy, CfnOutput,
    aws_dynamodb as dynamodb,
)
from constructs import Construct

# Table definitions per LOB
LOB_TABLES = {
    "retail-banking": [
        {"name": "Customers", "pk": "customer_id"},
        {"name": "Accounts", "pk": "account_id"},
        {"name": "Balances", "pk": "account_id"},
    ],
    "transaction-banking": [
        {"name": "Payments", "pk": "payment_id"},
        {"name": "Beneficiaries", "pk": "beneficiary_id"},
    ],
    "lending-wealth": [
        {"name": "Loans", "pk": "loan_id"},
        {"name": "CreditScores", "pk": "customer_id"},
        {"name": "EMISchedule", "pk": "loan_id", "sk": "emi_number", "sk_type": dynamodb.AttributeType.NUMBER},
    ],
}


class LobDataStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs):
        super().__init__(scope, construct_id, **kwargs)

        lob_name = self.node.try_get_context("lob_name")
        if not lob_name or lob_name not in LOB_TABLES:
            raise ValueError(f"Context 'lob_name' must be one of {list(LOB_TABLES.keys())}, got: {lob_name}")

        self.tables = {}
        for table_def in LOB_TABLES[lob_name]:
            sk_kwargs = {}
            if "sk" in table_def:
                sk_kwargs["sort_key"] = dynamodb.Attribute(
                    name=table_def["sk"],
                    type=table_def.get("sk_type", dynamodb.AttributeType.STRING),
                )

            table = dynamodb.Table(
                self, table_def["name"],
                table_name=table_def["name"],
                partition_key=dynamodb.Attribute(
                    name=table_def["pk"],
                    type=dynamodb.AttributeType.STRING,
                ),
                billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
                removal_policy=RemovalPolicy.DESTROY,
                **sk_kwargs,
            )
            self.tables[table_def["name"]] = table
            CfnOutput(self, f"{table_def['name']}TableArn", value=table.table_arn)
