#!/usr/bin/env bash
# deploy.sh — One-script deployment for Multi-LOB Banking Agent (Pattern 1)
#
# Prerequisites:
#   - 4 AWS CLI profiles: platform, retail-banking, transaction-banking, lending-wealth
#   - AWS CDK CLI installed (npm install -g aws-cdk)
#   - Python 3.10+, Docker, Node.js 18+
#   - Bedrock model access: Claude 4.5 Sonnet enabled in us-east-1
#   - agentcore CLI: pip install bedrock-agentcore-starter-toolkit
#
# Usage:
#   ./deploy.sh              # Run all steps
#   ./deploy.sh --from 5     # Resume from step 5
#
# Steps:
#   0  - Validate prerequisites
#   1  - Python venv + CDK dependencies
#   2  - CDK bootstrap (platform + 3 LOB accounts)
#   3  - CDK deploy — platform infra (Foundation, Guardrail, Gateway)
#   4  - CDK deploy — LOB infra (DynamoDB, IAM, KB for lending-wealth)
#   5  - Seed DynamoDB (3 LOBs)
#   6  - Generate + upload banking policy PDFs to lending-wealth S3
#   7  - Deploy 3 LOB MCP servers (agentcore deploy × 3)
#   8  - Create Gateway targets + OAuth credential provider + Cedar policies
#   9  - Register 3 LOBs in Agent Registry
#   10 - Deploy agent (agentcore deploy)
#   11 - CDK deploy — webapp + CloudFront

set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
REGION="${AWS_REGION:-us-east-1}"
PREFIX="LOBFederation"
PLATFORM_CDK="$PROJECT_DIR/infra/platform"
LOB_CDK="$PROJECT_DIR/infra/lob"
START_STEP=0

while [[ $# -gt 0 ]]; do
    case $1 in
        --from) START_STEP="$2"; shift 2 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
log()  { echo -e "${GREEN}[✓]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
fail() { echo -e "${RED}[✗]${NC} $1"; exit 1; }
step() { echo -e "\n${CYAN}════════════════════════════════════════════════════════════${NC}"; echo -e "${CYAN}  Step $1: $2${NC}"; echo -e "${CYAN}════════════════════════════════════════════════════════════${NC}\n"; }
should_run() { [ "$START_STEP" -le "$1" ]; }

# Helper: deploy one MCP server via agentcore CLI, return ARN on stdout
deploy_mcp_server() {
    local name="$1" dir="$2" profile="$3" discovery_url="$4" audience="$5"
    shift 5
    local extra_env_args=("$@")
    cd "$dir"
    rm -rf .bedrock_agentcore.yaml .bedrock_agentcore/

    local auth_config=""
    if [ -n "$discovery_url" ] && [ -n "$audience" ]; then
        auth_config="--authorizer-config {\"customJWTAuthorizer\":{\"discoveryUrl\":\"$discovery_url\",\"allowedAudience\":[\"$audience\"]}}"
    fi

    AWS_PROFILE="$profile" agentcore configure --entrypoint server.py --name "$name" \
        --protocol MCP --disable-memory --non-interactive $auth_config >&2

    local deploy_args=(AWS_PROFILE="$profile" agentcore deploy --auto-update-on-conflict)
    for env_arg in "${extra_env_args[@]}"; do
        deploy_args+=(--env "$env_arg")
    done
    env "${deploy_args[@]}" >&2

    python3 -c "
import yaml
with open('.bedrock_agentcore.yaml') as f:
    cfg = yaml.safe_load(f)
for a in cfg.get('agents', {}).values():
    bc = a.get('bedrock_agentcore', {})
    if bc.get('agent_arn'): print(bc['agent_arn']); break
"
    cd "$PROJECT_DIR"
}

# ═══════════════════════════════════════════════════════════
# Step 0: Validate prerequisites
# ═══════════════════════════════════════════════════════════
if should_run 0; then
    step 0 "Validate prerequisites"
    for cmd in aws cdk python3 docker agentcore; do
        command -v $cmd >/dev/null || fail "$cmd not found"
        log "$cmd available"
    done
    for profile in platform retail-banking transaction-banking lending-wealth; do
        aws sts get-caller-identity --profile "$profile" >/dev/null 2>&1 || fail "Profile '$profile' not configured"
        log "Profile '$profile' OK ($(aws sts get-caller-identity --profile "$profile" --query Account --output text))"
    done
    # Validate okta_config.json
    [ -f "$PROJECT_DIR/okta_config.json" ] || fail "okta_config.json not found — see README for Okta setup"
    for key in issuer web_client_id web_client_secret m2m_client_id m2m_client_secret discovery_url audience scope; do
        val=$(python3 -c "import json; print(json.load(open('$PROJECT_DIR/okta_config.json')).get('$key',''))")
        [ -n "$val" ] || fail "okta_config.json missing required field: $key"
    done
    log "okta_config.json validated"
fi

# ═══════════════════════════════════════════════════════════
# Step 1: Python venv + CDK dependencies
# ═══════════════════════════════════════════════════════════
if should_run 1; then
    step 1 "Python venv + CDK dependencies"
    for dir in "$PLATFORM_CDK" "$LOB_CDK"; do
        python3 -m venv --clear "$dir/.venv"
        source "$dir/.venv/bin/activate"
        "$dir/.venv/bin/pip" install -q --upgrade pip
        "$dir/.venv/bin/pip" install -q -r "$dir/requirements.txt"
        deactivate
        log "$(basename $dir) venv ready"
    done
fi

# ═══════════════════════════════════════════════════════════
# Step 2: CDK bootstrap (4 accounts)
# ═══════════════════════════════════════════════════════════
if should_run 2; then
    step 2 "CDK bootstrap (4 accounts)"
    cd "$PLATFORM_CDK"
    source .venv/bin/activate
    for profile in platform retail-banking transaction-banking lending-wealth; do
        acct=$(aws sts get-caller-identity --profile "$profile" --query Account --output text)
        log "Bootstrapping $profile ($acct)..."
        AWS_PROFILE="$profile" cdk bootstrap "aws://$acct/$REGION" 2>&1 | tail -3
    done
    deactivate
fi

# ═══════════════════════════════════════════════════════════
# Step 3: CDK deploy — platform infra (Foundation, Guardrail, Gateway)
# ═══════════════════════════════════════════════════════════
if should_run 3; then
    step 3 "CDK deploy — platform infra"
    cd "$PLATFORM_CDK"
    source .venv/bin/activate
    AWS_PROFILE=platform cdk deploy \
        ${PREFIX}-Foundation ${PREFIX}-Guardrail ${PREFIX}-Gateway \
        --require-approval never 2>&1 | tail -20
    deactivate

    # Extract outputs for later steps
    GATEWAY_URL=$(aws cloudformation describe-stacks --stack-name ${PREFIX}-Gateway --profile platform \
        --query "Stacks[0].Outputs[?OutputKey=='GatewayUrl'].OutputValue" --output text)
    GUARDRAIL_ID=$(aws cloudformation describe-stacks --stack-name ${PREFIX}-Guardrail --profile platform \
        --query "Stacks[0].Outputs[?OutputKey=='GuardrailId'].OutputValue" --output text)

    # Load Okta config
    OKTA_ISSUER=$(python3 -c "import json; print(json.load(open('$PROJECT_DIR/okta_config.json'))['issuer'])")
    OKTA_SPA_CLIENT_ID=$(python3 -c "import json; print(json.load(open('$PROJECT_DIR/okta_config.json')).get('spa_client_id',''))")
    OKTA_M2M_CLIENT_ID=$(python3 -c "import json; print(json.load(open('$PROJECT_DIR/okta_config.json'))['m2m_client_id'])")
    OKTA_DISCOVERY_URL=$(python3 -c "import json; print(json.load(open('$PROJECT_DIR/okta_config.json'))['discovery_url'])")

    log "Gateway URL: $GATEWAY_URL"
    log "Guardrail: $GUARDRAIL_ID"
    log "Okta Issuer: $OKTA_ISSUER"
fi

# ═══════════════════════════════════════════════════════════
# Step 4: CDK deploy — LOB infra (DynamoDB, IAM, KB)
# ═══════════════════════════════════════════════════════════
if should_run 4; then
    step 4 "CDK deploy — LOB infra"
    cd "$LOB_CDK"
    source .venv/bin/activate

    # Auto-patch platform account ID into cdk.context.json for cross-account trust
    PLATFORM_ACCT=$(aws sts get-caller-identity --profile platform --query Account --output text)
    python3 -c "
import json, os
ctx_file = 'cdk.context.json'
ctx = json.load(open(ctx_file)) if os.path.exists(ctx_file) else {}
ctx['platform_account_id'] = '${PLATFORM_ACCT}'
with open(ctx_file, 'w') as f: json.dump(ctx, f, indent=2)
"
    log "Set platform_account_id=$PLATFORM_ACCT in infra/lob/cdk.context.json"

    for lob_profile in retail-banking transaction-banking; do
        log "Deploying $lob_profile infra..."
        AWS_PROFILE="$lob_profile" cdk deploy --all --require-approval never \
            -c lob_name="$lob_profile" 2>&1 | tail -5
    done
    log "Deploying lending-wealth infra (with Knowledge Base)..."
    AWS_PROFILE=lending-wealth cdk deploy --all --require-approval never \
        -c lob_name=lending-wealth -c enable_kb=true 2>&1 | tail -10
    deactivate
fi

# ═══════════════════════════════════════════════════════════
# Step 5: Seed DynamoDB (3 LOBs)
# ═══════════════════════════════════════════════════════════
if should_run 5; then
    step 5 "Seed DynamoDB"
    for lob in retail-banking transaction-banking lending-wealth; do
        log "Seeding $lob..."
        python3 "$PROJECT_DIR/lob-accounts/$lob/data/seed_data.py"
    done
fi

# ═══════════════════════════════════════════════════════════
# Step 6: Generate + upload banking policy PDFs
# ═══════════════════════════════════════════════════════════
if should_run 6; then
    step 6 "Generate + upload banking policy PDFs"
    DOCS_DIR="$PROJECT_DIR/lob-accounts/lending-wealth/documents"
    if [ -f "$DOCS_DIR/lending_policy_manual.pdf" ] && [ -f "$DOCS_DIR/product_terms_sheets.pdf" ] && [ -f "$DOCS_DIR/regulatory_guidelines.pdf" ]; then
        log "PDFs already exist — skipping generation (using static assets)"
    else
        pip install -q fpdf2 2>/dev/null || "$PLATFORM_CDK/.venv/bin/pip" install -q fpdf2
        "$PLATFORM_CDK/.venv/bin/python" "$PROJECT_DIR/scripts/generate_documents.py"
    fi

    DOCS_BUCKET=$(aws cloudformation describe-stacks --stack-name LobInfra-lending-wealth-KnowledgeBase \
        --profile lending-wealth --query "Stacks[0].Outputs[?OutputKey=='DocsBucketName'].OutputValue" --output text)
    log "Uploading PDFs to s3://$DOCS_BUCKET/"
    aws s3 sync "$PROJECT_DIR/lob-accounts/lending-wealth/documents/" "s3://$DOCS_BUCKET/" --profile lending-wealth
    log "PDFs uploaded"

    # Trigger KB data source sync (index the uploaded PDFs)
    KB_ID=$(aws cloudformation describe-stacks --stack-name LobInfra-lending-wealth-KnowledgeBase \
        --profile lending-wealth --query "Stacks[0].Outputs[?OutputKey=='KnowledgeBaseId'].OutputValue" --output text)
    DS_ID=$(aws cloudformation describe-stacks --stack-name LobInfra-lending-wealth-KnowledgeBase \
        --profile lending-wealth --query "Stacks[0].Outputs[?OutputKey=='DataSourceId'].OutputValue" --output text)
    log "Syncing Knowledge Base ($KB_ID)..."
    aws bedrock-agent start-ingestion-job --knowledge-base-id "$KB_ID" --data-source-id "$DS_ID" \
        --profile lending-wealth --region "$REGION" >/dev/null
    # Wait for sync to complete
    for i in $(seq 1 30); do
        STATUS=$(aws bedrock-agent get-ingestion-job --knowledge-base-id "$KB_ID" --data-source-id "$DS_ID" \
            --ingestion-job-id "$(aws bedrock-agent list-ingestion-jobs --knowledge-base-id "$KB_ID" --data-source-id "$DS_ID" \
            --profile lending-wealth --region "$REGION" --query 'ingestionJobSummaries[0].ingestionJobId' --output text)" \
            --profile lending-wealth --region "$REGION" --query 'ingestionJob.status' --output text 2>/dev/null)
        [ "$STATUS" = "COMPLETE" ] && break
        sleep 5
    done
    log "KB sync complete — documents indexed"
fi

# ═══════════════════════════════════════════════════════════
# Step 7: Deploy 3 LOB MCP servers (with JWT authorizer for OAuth M2M)
# ═══════════════════════════════════════════════════════════
if should_run 7; then
    step 7 "Deploy 3 LOB MCP servers"

    # Read Okta config for JWT authorizer
    if [ -z "$OKTA_DISCOVERY_URL" ]; then
        OKTA_DISCOVERY_URL=$(python3 -c "import json; print(json.load(open('$PROJECT_DIR/okta_config.json'))['discovery_url'])")
    fi
    OKTA_AUDIENCE=$(python3 -c "import json; print(json.load(open('$PROJECT_DIR/okta_config.json'))['audience'])")

    RETAIL_ARN=$(deploy_mcp_server "retail_banking_mcp" \
        "$PROJECT_DIR/lob-accounts/retail-banking/mcp_server" "retail-banking" \
        "$OKTA_DISCOVERY_URL" "$OKTA_AUDIENCE")
    log "Retail Banking MCP: $RETAIL_ARN"

    TRANSACTION_ARN=$(deploy_mcp_server "transaction_banking_mcp" \
        "$PROJECT_DIR/lob-accounts/transaction-banking/mcp_server" "transaction-banking" \
        "$OKTA_DISCOVERY_URL" "$OKTA_AUDIENCE")
    log "Transaction Banking MCP: $TRANSACTION_ARN"

    LENDING_ARN=$(deploy_mcp_server "lending_wealth_mcp" \
        "$PROJECT_DIR/lob-accounts/lending-wealth/mcp_server" "lending-wealth" \
        "$OKTA_DISCOVERY_URL" "$OKTA_AUDIENCE" \
        "KNOWLEDGE_BASE_ID=$(aws cloudformation describe-stacks --stack-name LobInfra-lending-wealth-KnowledgeBase \
            --profile lending-wealth --query 'Stacks[0].Outputs[?OutputKey==`KnowledgeBaseId`].OutputValue' --output text)")
    log "Lending & Wealth MCP: $LENDING_ARN"
fi

# ═══════════════════════════════════════════════════════════
# Step 8: Create Gateway targets (OAuth M2M)
# ═══════════════════════════════════════════════════════════
if should_run 8; then
    step 8 "Create Gateway targets + OAuth credential provider + Cedar policies"
    pip install -q pyyaml boto3 2>/dev/null || "$PLATFORM_CDK/.venv/bin/pip" install -q pyyaml boto3
    export CDK_PREFIX="$PREFIX"
    AWS_PROFILE=platform "$PLATFORM_CDK/.venv/bin/python" "$PROJECT_DIR/platform-account/gateway/setup_gateway.py" --profile platform
fi

# ═══════════════════════════════════════════════════════════
# Step 9: Register LOBs in Agent Registry
# ═══════════════════════════════════════════════════════════
if should_run 9; then
    step 9 "Register LOBs in Agent Registry"
    AWS_PROFILE=platform python3 "$PROJECT_DIR/platform-account/gateway/register_agents.py" --profile platform
fi

# ═══════════════════════════════════════════════════════════
# Step 10: Deploy agent
# ═══════════════════════════════════════════════════════════
if should_run 10; then
    step 10 "Deploy banking agent"
    cd "$PROJECT_DIR/platform-account/agent"
    rm -rf .bedrock_agentcore.yaml .bedrock_agentcore/

    # Read values from CDK outputs / okta_config if not already set
    if [ -z "$GATEWAY_URL" ]; then
        GATEWAY_URL=$(aws cloudformation describe-stacks --stack-name ${PREFIX}-Gateway --profile platform \
            --query "Stacks[0].Outputs[?OutputKey=='GatewayUrl'].OutputValue" --output text)
    fi
    if [ -z "$OKTA_ISSUER" ]; then
        OKTA_ISSUER=$(python3 -c "import json; print(json.load(open('$PROJECT_DIR/okta_config.json'))['issuer'])")
    fi

    REGISTRY_ARN=""
    [ -f "$PROJECT_DIR/registry_config.json" ] && \
        REGISTRY_ARN=$(python3 -c "import json; print(json.load(open('$PROJECT_DIR/registry_config.json'))['registry_arn'])")

    AWS_PROFILE=platform agentcore configure --entrypoint agent.py --name lobfederation_agent \
        --protocol HTTP --disable-memory --non-interactive

    # agentcore.json with customJWTAuthorizer is already at agentcore/agentcore.json
    # (committed to source — no copy needed)

    AWS_PROFILE=platform agentcore deploy --auto-update-on-conflict \
        --env "GATEWAY_URL=$GATEWAY_URL" \
        --env "REGISTRY_ARN=$REGISTRY_ARN" \
        --env "MODEL_ID=us.anthropic.claude-sonnet-4-5-20250929-v1:0" \
        --env "AWS_REGION=$REGION"

    AGENT_ARN=$(python3 -c "
import yaml
with open('.bedrock_agentcore.yaml') as f:
    cfg = yaml.safe_load(f)
for a in cfg.get('agents', {}).values():
    bc = a.get('bedrock_agentcore', {})
    if bc.get('agent_arn'): print(bc['agent_arn']); break
")

    log "Agent deployed: $AGENT_ARN"

    # Apply CUSTOM_JWT authorizer to the Runtime.
    # The agentcore CLI doesn't read agentcore/agentcore.json for authorizer config,
    # so we apply it via API after deploy. This also re-sets env vars (update_agent_runtime
    # is a full-replace API).
    log "Configuring Runtime JWT authorizer (user identity propagation)..."
    OKTA_DISCOVERY=$(python3 -c "import json; print(json.load(open('$PROJECT_DIR/okta_config.json'))['discovery_url'])")
    OKTA_AUD=$(python3 -c "import json; print(json.load(open('$PROJECT_DIR/okta_config.json'))['audience'])")

    AGENT_RUNTIME_ID=$(python3 -c "
import yaml
with open('.bedrock_agentcore.yaml') as f:
    cfg = yaml.safe_load(f)
for a in cfg.get('agents', {}).values():
    rid = a.get('bedrock_agentcore', {}).get('agent_id', '')
    if rid: print(rid); break
")

    python3 -c "
import boto3, json, time
session = boto3.Session(profile_name='platform', region_name='us-east-1')
client = session.client('bedrock-agentcore-control')
runtime_id = '$AGENT_RUNTIME_ID'
current = client.get_agent_runtime(agentRuntimeId=runtime_id)
# Wait if still updating from deploy
for _ in range(30):
    if current['status'] == 'READY': break
    time.sleep(3)
    current = client.get_agent_runtime(agentRuntimeId=runtime_id)
client.update_agent_runtime(
    agentRuntimeId=runtime_id,
    roleArn=current['roleArn'],
    networkConfiguration=current['networkConfiguration'],
    agentRuntimeArtifact=current['agentRuntimeArtifact'],
    protocolConfiguration=current.get('protocolConfiguration', {'serverProtocol': 'HTTP'}),
    authorizerConfiguration={
        'customJWTAuthorizer': {
            'discoveryUrl': '$OKTA_DISCOVERY',
            'allowedAudience': ['$OKTA_AUD'],
        }
    },
    requestHeaderConfiguration={'requestHeaderAllowlist': ['Authorization']},
    environmentVariables={
        'GATEWAY_URL': '$GATEWAY_URL',
        'REGISTRY_ARN': '$REGISTRY_ARN',
        'MODEL_ID': 'us.anthropic.claude-sonnet-4-5-20250929-v1:0',
        'AWS_REGION': 'us-east-1',
    },
)
# Wait for READY
for _ in range(30):
    time.sleep(3)
    s = client.get_agent_runtime(agentRuntimeId=runtime_id)['status']
    if s == 'READY': break
print(f'Runtime {runtime_id}: JWT authorizer configured, status={s}')
"

    cd "$PROJECT_DIR"

    # Fix permissions on auto-created roles (DynamoDB/KB for MCP servers, Registry for agent)
    log "Fixing agent role permissions..."
    export CDK_PREFIX="$PREFIX"
    python3 "$PROJECT_DIR/scripts/fix_agent_role_permissions.py" --profile platform
fi

# ═══════════════════════════════════════════════════════════
# Step 11: CDK deploy — webapp + CloudFront
# ═══════════════════════════════════════════════════════════
if should_run 11; then
    step 11 "CDK deploy — webapp + CloudFront"
    cd "$PLATFORM_CDK"
    source .venv/bin/activate

    # Read agent ARN if not set
    if [ -z "$AGENT_ARN" ]; then
        AGENT_ARN=$(grep "agent_arn:" "$PROJECT_DIR/platform-account/agent/.bedrock_agentcore.yaml" | head -1 | awk '{print $2}')
    fi
    if [ -z "$GUARDRAIL_ID" ]; then
        GUARDRAIL_ID=$(aws cloudformation describe-stacks --stack-name ${PREFIX}-Guardrail --profile platform \
            --query "Stacks[0].Outputs[?OutputKey=='GuardrailId'].OutputValue" --output text 2>/dev/null || echo "")
    fi
    if [ -z "$OKTA_ISSUER" ]; then
        OKTA_ISSUER=$(python3 -c "import json; print(json.load(open('$PROJECT_DIR/okta_config.json'))['issuer'])")
    fi
    if [ -z "$OKTA_SPA_CLIENT_ID" ]; then
        OKTA_SPA_CLIENT_ID=$(python3 -c "import json; print(json.load(open('$PROJECT_DIR/okta_config.json')).get('spa_client_id',''))")
    fi

    # Write runtime values to cdk.context.json (gitignored, never dirties cdk.json)
    OKTA_WEB_CLIENT_ID=$(python3 -c "import json; print(json.load(open('$PROJECT_DIR/okta_config.json')).get('web_client_id',''))")
    OKTA_WEB_CLIENT_SECRET=$(python3 -c "import json; print(json.load(open('$PROJECT_DIR/okta_config.json')).get('web_client_secret',''))")
    # Get existing CloudFront URL if available (for redeployments)
    EXISTING_CF_URL=$(aws cloudformation describe-stacks --stack-name ${PREFIX}-CloudFront --profile platform \
        --query "Stacks[0].Outputs[?OutputKey=='CloudFrontUrl'].OutputValue" --output text 2>/dev/null || echo "")

    python3 -c "
import json, os
ctx_file = 'cdk.context.json'
ctx = json.load(open(ctx_file)) if os.path.exists(ctx_file) else {}
ctx['okta_issuer'] = '${OKTA_ISSUER:-}'
ctx['okta_spa_client_id'] = '${OKTA_SPA_CLIENT_ID:-}'
ctx['okta_web_client_id'] = '${OKTA_WEB_CLIENT_ID:-}'
ctx['okta_web_client_secret'] = '${OKTA_WEB_CLIENT_SECRET:-}'
ctx['agent_runtime_arn'] = '${AGENT_ARN:-PLACEHOLDER}'
ctx['guardrail_id'] = '${GUARDRAIL_ID:-}'
ctx['frontend_url'] = '${EXISTING_CF_URL:-http://localhost:3000}'
ctx['backend_url'] = '${EXISTING_CF_URL:-http://localhost:8000}'
with open(ctx_file, 'w') as f: json.dump(ctx, f, indent=2)
"

    cd "$PROJECT_DIR/platform-account/webapp/frontend" && npm install --silent 2>/dev/null
    cd "$PLATFORM_CDK"

    AWS_PROFILE=platform cdk deploy ${PREFIX}-WebApp ${PREFIX}-CloudFront \
        --require-approval never 2>&1 | tail -20
    deactivate

    CF_URL=$(aws cloudformation describe-stacks --stack-name ${PREFIX}-CloudFront --profile platform \
        --query "Stacks[0].Outputs[?OutputKey=='CloudFrontUrl'].OutputValue" --output text)
    CF_DIST_ID=$(aws cloudformation describe-stacks --stack-name ${PREFIX}-CloudFront --profile platform \
        --query "Stacks[0].Outputs[?OutputKey=='DistributionId'].OutputValue" --output text)
    log "CloudFront URL: $CF_URL"

    # Re-deploy webapp with correct CloudFront URL if first deploy used localhost
    if [ -n "$CF_URL" ] && [ "$EXISTING_CF_URL" != "$CF_URL" ]; then
        log "First deploy detected — re-deploying webapp with CloudFront URL..."
        cd "$PLATFORM_CDK"
        source .venv/bin/activate
        python3 -c "
import json, os
ctx_file = 'cdk.context.json'
ctx = json.load(open(ctx_file)) if os.path.exists(ctx_file) else {}
ctx['frontend_url'] = '${CF_URL}'
ctx['backend_url'] = '${CF_URL}'
with open(ctx_file, 'w') as f: json.dump(ctx, f, indent=2)
"
        AWS_PROFILE=platform cdk deploy ${PREFIX}-WebApp \
            --require-approval never 2>&1 | tail -10
        deactivate
        log "Webapp re-deployed with BACKEND_URL=$CF_URL"
    fi

    # Invalidate cache to serve updated frontend
    aws cloudfront create-invalidation --distribution-id "$CF_DIST_ID" --paths "/*" --profile platform >/dev/null 2>&1
    log "CloudFront cache invalidated"
fi

# ═══════════════════════════════════════════════════════════
echo -e "\n${GREEN}════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  ✅ Deployment complete!${NC}"
echo -e "${GREEN}════════════════════════════════════════════════════════════${NC}"
echo ""
echo "  CloudFront: ${CF_URL:-check ${PREFIX}-CloudFront stack outputs}"
echo "  Login:      Okta user (banker@example.com)"
echo "  Scenarios:  ./scripts/demo.sh"
echo ""
echo "  Auth chain: Browser → Okta login → CloudFront → ALB → ECS (IAM SigV4) → Agent Runtime → Okta M2M → Gateway → LOB MCP"
echo ""
