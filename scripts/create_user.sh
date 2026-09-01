#!/bin/bash
# Create a demo user in the Okta organization for the Banking Agent app.
# Usage: ./create_user.sh <email> <password>
#
# Requires: OKTA_ORG_URL and OKTA_API_TOKEN env vars (or okta_config.json in project root)
# Users are created with admin-managed passwords (no email verification in demo).

set -e

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
OKTA_ORG="${OKTA_ORG_URL:-$(python3 -c "import json; print(json.load(open('$PROJECT_DIR/okta_config.json'))['okta_org'])")}"
OKTA_TOKEN="${OKTA_API_TOKEN:?Set OKTA_API_TOKEN env var (Okta admin API token)}"

EMAIL="${1:?Usage: $0 <email> <password>}"
PASSWORD="${2:?Usage: $0 <email> <password>}"
FIRST_NAME="${3:-Demo}"
LAST_NAME="${4:-User}"

echo "Creating Okta user: $EMAIL"
curl -s -X POST "${OKTA_ORG}/api/v1/users?activate=true" \
  -H "Authorization: SSWS $OKTA_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{
    \"profile\": {
      \"firstName\": \"$FIRST_NAME\",
      \"lastName\": \"$LAST_NAME\",
      \"email\": \"$EMAIL\",
      \"login\": \"$EMAIL\"
    },
    \"credentials\": {
      \"password\": {\"value\": \"$PASSWORD\"}
    }
  }" | python3 -c "
import json,sys
r = json.load(sys.stdin)
if 'id' in r:
    print(f'✅ User created: {r[\"profile\"][\"login\"]} (ID: {r[\"id\"]})')
else:
    print(f'❌ Error: {r.get(\"errorSummary\", r)}')
"

echo ""
echo "Login credentials:"
echo "   Email: $EMAIL"
echo "   Password: $PASSWORD"
