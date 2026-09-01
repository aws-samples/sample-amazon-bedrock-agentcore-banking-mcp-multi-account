"""Generate banking policy PDF documents for Bedrock Knowledge Base.

Creates 3 PDFs in lob-accounts/lending-wealth/documents/:
  1. lending_policy_manual.pdf — eligibility criteria, credit score thresholds, DTI limits
  2. product_terms_sheets.pdf — product terms for savings, FDs, personal loans, credit cards
  3. regulatory_guidelines.pdf — KYC, AML thresholds, suspicious activity indicators

Numbers align with the 5 demo customers (C001-C005) so scenarios produce meaningful results.

Usage:
  pip install fpdf2
  python scripts/generate_documents.py
"""
import os
from fpdf import FPDF

DOCS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "lob-accounts", "lending-wealth", "documents")


def make_pdf(filename, title, sections):
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 12, title, new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.ln(4)
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(0, 5, "CONFIDENTIAL - Internal Use Only", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.cell(0, 5, "Effective Date: January 1, 2026", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.ln(8)
    for heading, body in sections:
        pdf.set_font("Helvetica", "B", 13)
        pdf.cell(0, 8, heading, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)
        pdf.set_font("Helvetica", "", 10)
        for line in body.strip().split("\n"):
            line = line.strip().replace("\u2014", "--").replace("\u2013", "-").replace("\u2019", "'")
            if line:
                pdf.multi_cell(0, 5, line, new_x="LMARGIN", new_y="NEXT")
            else:
                pdf.ln(3)
        pdf.ln(4)
    os.makedirs(DOCS_DIR, exist_ok=True)
    path = os.path.join(DOCS_DIR, filename)
    pdf.output(path)
    print(f"  Generated: {path}")


def generate_lending_policy_manual():
    sections = [
        ("1. Purpose and Scope", """
This Lending Policy Manual establishes the credit standards, approval criteria, and risk
framework for all consumer lending products. All relationship managers and credit analysts
must adhere to these policies when evaluating loan applications.
        """),
        ("2. Credit Score Requirements", """
Minimum credit score requirements by product and amount:

Personal Loans up to $25,000: Minimum credit score of 650. Applicants with scores 650-699
require additional income documentation for the past 24 months.

Personal Loans $25,001 to $50,000: Minimum credit score of 700. Scores 700-749 require
senior credit officer approval. Scores 750 and above qualify for streamlined approval.

Personal Loans above $50,000: Minimum credit score of 750. Credit committee approval required
for amounts exceeding $75,000.

Home Equity Lines: Minimum credit score of 700. Combined loan-to-value must not exceed 80%.

Auto Loans: Minimum credit score of 620. Scores 620-659 limited to $25,000 maximum and
48-month terms. Scores 660+ qualify for standard terms up to 72 months.
        """),
        ("3. Debt-to-Income (DTI) Ratio Limits", """
Maximum DTI ratios by product:

Personal Loans: Maximum DTI of 40%. For applicants with credit scores above 750, DTI up to
45% may be approved with senior credit officer sign-off.

Home Equity: Maximum DTI of 43% including the new credit line at full utilization.

Auto Loans: Maximum DTI of 45%. Monthly auto payment should not exceed 15% of gross monthly
income.

For all products: Applicants with DTI above the standard maximum but below the exception
threshold must demonstrate compensating factors such as significant liquid reserves (6+ months
of expenses), stable employment history (5+ years), or substantial collateral.
        """),
        ("4. Customer Segment Policies", """
Lending limits and privileges by customer segment:

Standard Segment: Maximum unsecured personal loan of $25,000. Standard interest rates apply.
Minimum 12 months of account relationship required.

Premium Segment: Maximum unsecured personal loan of $75,000. Rate discount of 0.5% on all
products. Expedited processing (48-hour decision). Dedicated relationship manager.

Gold Segment: Maximum unsecured personal loan of $150,000. Rate discount of 1.0% on all
products. Same-day preliminary decision. Priority credit committee review. Access to
exclusive investment-linked lending products.
        """),
        ("5. Collateral Requirements", """
Secured lending standards:

Personal Loans above $50,000: May require collateral equal to 50% of loan value. Acceptable
collateral includes fixed deposits, investment portfolios, or real property.

Home Equity: Property appraisal required within 90 days of application. Maximum LTV of 80%
for scores 700-739, or 85% for scores 740+.

Auto Loans: Vehicle must be no more than 7 years old at loan maturity. Maximum LTV of 100%
for new vehicles, 90% for used vehicles.
        """),
        ("6. Approval Authority", """
Lending authority levels:

Relationship Manager: May recommend personal loans up to $25,000 for applicants meeting all
standard criteria.

Senior Credit Officer: May approve personal loans up to $50,000, auto loans up to $75,000.
May grant DTI exceptions up to 5 percentage points above standard limits.

Credit Committee: Required for all loans above $50,000, any DTI exception above 5 points,
and any loan to a borrower with prior delinquency history.
        """),
    ]
    make_pdf("lending_policy_manual.pdf", "Lending Policy Manual", sections)


def generate_product_terms():
    sections = [
        ("1. Savings Accounts", """
Standard Savings Account:
- Minimum balance: $500
- Interest rate: 2.5% APY
- Monthly maintenance fee: $5 (waived if balance above $1,000)
- Unlimited withdrawals

Premium Savings Account:
- Minimum balance: $10,000
- Interest rate: 3.5% APY
- No monthly maintenance fee
- Complimentary financial planning consultation annually
        """),
        ("2. Fixed Deposits", """
Standard Fixed Deposit:
- Minimum deposit: $1,000
- 6-month term: 4.0% APY
- 12-month term: 4.5% APY
- 24-month term: 5.0% APY
- Early withdrawal penalty: 3 months of interest

Premium Fixed Deposit (Gold/Premium customers):
- Minimum deposit: $25,000
- Additional 0.25% APY on all terms
- Partial withdrawal allowed (up to 25% without penalty)
        """),
        ("3. Personal Loans", """
Standard Personal Loan:
- Amount range: $5,000 to $25,000
- Interest rate: 10.5% to 12.5% APR (based on credit score)
- Terms: 12 to 36 months
- Origination fee: 1.5% of loan amount
- No prepayment penalty after 6 months

Premium Personal Loan:
- Amount range: $5,000 to $75,000
- Interest rate: 8.5% to 10.5% APR (0.5% discount for Premium segment)
- Terms: 12 to 60 months
- Origination fee: 1.0% of loan amount
- No prepayment penalty

Gold Personal Loan:
- Amount range: $5,000 to $150,000
- Interest rate: 6.5% to 9.5% APR (1.0% discount for Gold segment)
- Terms: 12 to 84 months
- No origination fee
- No prepayment penalty
        """),
        ("4. Credit Cards", """
Standard Credit Card:
- Credit limit: $2,000 to $10,000
- APR: 18.99%
- Annual fee: $50
- Rewards: 1% cashback on all purchases

Premium Credit Card:
- Credit limit: $10,000 to $25,000
- APR: 15.99%
- Annual fee: $95
- Rewards: 2% cashback on dining and travel, 1% on all other purchases
- Complimentary airport lounge access (2 visits/year)

Gold Credit Card:
- Credit limit: $25,000 to $100,000
- APR: 12.99%
- Annual fee: $250
- Rewards: 3% cashback on all purchases
- Unlimited airport lounge access
- Complimentary travel insurance
        """),
    ]
    make_pdf("product_terms_sheets.pdf", "Product Terms and Conditions", sections)


def generate_regulatory_guidelines():
    sections = [
        ("1. Know Your Customer (KYC) Requirements", """
All new account openings and loan applications require KYC verification:

Standard KYC (accounts under $50,000):
- Government-issued photo ID (passport, driver's license)
- Proof of address (utility bill, bank statement within 90 days)
- Social Security Number verification

Enhanced KYC (accounts $50,000 and above, or high-risk indicators):
- All Standard KYC documents
- Source of funds documentation
- Employment verification letter
- Tax returns for the past 2 years
- Additional reference checks for non-resident applicants
        """),
        ("2. Anti-Money Laundering (AML) Thresholds", """
Transaction monitoring and reporting requirements:

Currency Transaction Reports (CTR): Required for all cash transactions exceeding $10,000
in a single business day, whether single or aggregated transactions.

Suspicious Activity Reports (SAR): Must be filed within 30 days of detection for:
- Transactions that appear to have no business or lawful purpose
- Transactions inconsistent with the customer's known profile
- Structuring: multiple transactions just below $10,000 threshold
- Rapid movement of funds through accounts with no apparent business reason
- Wire transfers to/from high-risk jurisdictions

Enhanced monitoring triggers:
- Single transaction exceeding $50,000
- Cumulative monthly transactions exceeding $100,000
- International wire transfers exceeding $25,000
- Account activity inconsistent with stated occupation/income
        """),
        ("3. Suspicious Activity Indicators", """
Red flags requiring investigation:

Transaction Patterns:
- Multiple deposits just below $10,000 (structuring)
- Frequent large cash deposits followed by immediate wire transfers
- Account used primarily for pass-through transactions
- Sudden increase in transaction volume without business justification

Customer Behavior:
- Reluctance to provide identification or documentation
- Use of multiple accounts to aggregate funds
- Frequent changes to account ownership or signatories
- Transactions inconsistent with customer's stated business

Geographic Risk:
- Transactions involving OFAC-sanctioned countries
- Wire transfers to/from jurisdictions with weak AML controls
- Use of correspondent banking relationships in high-risk regions
        """),
        ("4. Customer Due Diligence Levels", """
Risk-based due diligence tiers:

Low Risk: Standard retail customers with domestic accounts, regular employment income,
and transaction patterns consistent with profile. Review cycle: every 36 months.

Medium Risk: Customers with international transactions, self-employment income, or
accounts exceeding $250,000. Review cycle: every 12 months.

High Risk: Politically exposed persons (PEPs), customers in high-risk industries
(cash-intensive businesses, money services), or customers with prior SAR filings.
Review cycle: every 6 months. Senior compliance officer approval required for
account opening and significant transactions.
        """),
    ]
    make_pdf("regulatory_guidelines.pdf", "Regulatory Compliance Guidelines", sections)


if __name__ == "__main__":
    print("Generating banking policy documents...")
    generate_lending_policy_manual()
    generate_product_terms()
    generate_regulatory_guidelines()
    print("Done. PDFs are in lob-accounts/lending-wealth/documents/")
