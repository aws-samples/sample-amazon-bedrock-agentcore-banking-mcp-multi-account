#!/usr/bin/env bash
# cleanup.sh — Destroy all LOB Federation (Pattern 1) resources
#
# Destroy order (reverse of deploy):
#   1. Agent runtime (platform)
#   2. MCP server runtimes (3 LOBs)
#   3. Gateway targets
#   4. Agent Registry + records
#   5. CDK stacks — platform (reverse dependency order)
#   6. CDK stacks — LOB (3 accounts)
#   7. Local config files
#
# Usage:
#   ./cleanup.sh
#
# Prompts once for confirmation, then proceeds without further prompts.

set +e  # Continue on errors (resources may already be deleted)

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
REGION="${AWS_REGION:-us-east-1}"
PREFIX="LOBFederation"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
log()  { echo -e "${GREEN}[✓]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
fail() { echo -e "${RED}[✗]${NC} $1"; }

echo -e "${RED}════════════════════════════════════════════════════════════${NC}"
echo -e "${RED}  TEARDOWN — Destroy ALL LOB Federation resources${NC}"
echo -e "${RED}════════════════════════════════════════════════════════════${NC}"
echo ""

echo -e "  This will destroy ALL resources across 4 AWS accounts:"
echo -e "    • Agent runtime (platform)"
echo -e "    • 3 MCP server runtimes (LOB accounts)"
echo -e "    • Gateway targets + Cedar policies"
echo -e "    • Agent Registry + records"
echo -e "    • CDK stacks (platform + 3 LOBs)"
echo -e "    • Local config files"
echo ""
echo -ne "${YELLOW}  Are you sure you want to proceed? [y/N]: ${NC}"
read -r ans
[[ "$ans" =~ ^[Yy] ]] || exit 0

# ═══════════════════════════════════════════════════════════
# Step 1: Destroy Agent Runtime (platform)
# ═══════════════════════════════════════════════════════════
echo -e "\n${YELLOW}Step 1: Destroy Agent Runtime${NC}"
cd "$PROJECT_DIR/platform-account/agent"
if [ -f .bedrock_agentcore.yaml ]; then
    AWS_PROFILE=platform agentcore destroy --force 2>&1 | tail -3 || true
    rm -f .bedrock_agentcore.yaml
    rm -rf .bedrock_agentcore/
    log "Agent runtime destroyed"
else
    warn "No agent config found — skipping"
fi

# ═══════════════════════════════════════════════════════════
# Step 2: Destroy LOB MCP Servers (3 runtimes)
# ═══════════════════════════════════════════════════════════
echo -e "\n${YELLOW}Step 2: Destroy LOB MCP Servers${NC}"
for lob in retail-banking transaction-banking lending-wealth; do
    cd "$PROJECT_DIR/lob-accounts/$lob/mcp_server"
    if [ -f .bedrock_agentcore.yaml ]; then
        AWS_PROFILE="$lob" agentcore destroy --force 2>&1 | tail -3 || true
        rm -f .bedrock_agentcore.yaml
        rm -rf .bedrock_agentcore/
        log "$lob MCP server destroyed"
    else
        warn "$lob: no config found — skipping"
    fi
done

# ═══════════════════════════════════════════════════════════
# Step 3: Delete Gateway Targets
# ═══════════════════════════════════════════════════════════
echo -e "\n${YELLOW}Step 3: Delete Gateway Targets${NC}"
# Resolve gateway ID (API needs full ID, not just the name)
GATEWAY_ID=$(AWS_PROFILE=platform aws bedrock-agentcore-control list-gateways --region "$REGION" \
    --query "items[?name=='lobfederation-gateway'].gatewayId" --output text 2>/dev/null) || true
if [ -n "$GATEWAY_ID" ]; then
    TARGETS=$(AWS_PROFILE=platform aws bedrock-agentcore-control list-gateway-targets \
        --gateway-identifier "$GATEWAY_ID" --region "$REGION" \
        --query 'items[].targetId' --output text 2>/dev/null) || true
    if [ -n "$TARGETS" ]; then
        for target_id in $TARGETS; do
            AWS_PROFILE=platform aws bedrock-agentcore-control delete-gateway-target \
                --gateway-identifier "$GATEWAY_ID" --target-id "$target_id" \
                --region "$REGION" 2>&1 || true
            log "Target deleted: $target_id"
        done
        # Wait for all targets to finish deleting
        sleep 15
    else
        warn "No gateway targets found — skipping"
    fi
else
    warn "No lobfederation-gateway found — skipping"
fi

# ═══════════════════════════════════════════════════════════
# Step 4: Delete Agent Registry
# ═══════════════════════════════════════════════════════════
echo -e "\n${YELLOW}Step 4: Delete Agent Registry${NC}"
REGISTRY_ID=""
if [ -f "$PROJECT_DIR/registry_config.json" ]; then
    REGISTRY_ID=$(python3 -c "import json; print(json.load(open('$PROJECT_DIR/registry_config.json')).get('registry_id',''))" 2>/dev/null) || true
fi
if [ -z "$REGISTRY_ID" ]; then
    # Try to find by name
    REGISTRY_ID=$(AWS_PROFILE=platform aws bedrock-agentcore-control list-registries \
        --region "$REGION" --query "registries[?name=='bankingdemo-agent-registry'].registryId" \
        --output text 2>/dev/null) || true
fi
if [ -n "$REGISTRY_ID" ]; then
    # Delete all records first
    RECORDS=$(AWS_PROFILE=platform aws bedrock-agentcore-control list-registry-records \
        --registry-id "$REGISTRY_ID" --region "$REGION" \
        --query 'registryRecords[].recordId' --output text 2>/dev/null) || true
    for record_id in $RECORDS; do
        AWS_PROFILE=platform aws bedrock-agentcore-control delete-registry-record \
            --registry-id "$REGISTRY_ID" --record-id "$record_id" \
            --region "$REGION" 2>&1 || true
    done
    sleep 3
    AWS_PROFILE=platform aws bedrock-agentcore-control delete-registry \
        --registry-id "$REGISTRY_ID" --region "$REGION" 2>&1 || true
    log "Registry deleted: $REGISTRY_ID"
else
    warn "No registry found — skipping"
fi

# ═══════════════════════════════════════════════════════════
# Step 5: CDK Destroy — Platform Stacks (sequential, respects export dependencies)
# ═══════════════════════════════════════════════════════════
echo -e "\n${YELLOW}Step 5: Destroy Platform CDK Stacks${NC}"
# Must delete in reverse dependency order: CloudFront → WebApp → Gateway → Guardrail → Foundation
for stack in ${PREFIX}-CloudFront ${PREFIX}-WebApp ${PREFIX}-Gateway ${PREFIX}-Guardrail ${PREFIX}-Foundation; do
    # Check if stack exists
    STATUS=$(AWS_PROFILE=platform aws cloudformation describe-stacks --stack-name "$stack" --region "$REGION" \
        --query 'Stacks[0].StackStatus' --output text 2>/dev/null) || true
    if [ -z "$STATUS" ] || [ "$STATUS" = "None" ]; then
        warn "$stack: not found — skipping"
        continue
    fi
    AWS_PROFILE=platform aws cloudformation delete-stack --stack-name "$stack" --region "$REGION" 2>&1 || true
    AWS_PROFILE=platform aws cloudformation wait stack-delete-complete --stack-name "$stack" --region "$REGION" 2>&1 || true
    log "$stack destroyed"
done

# ═══════════════════════════════════════════════════════════
# Step 6: CDK Destroy — LOB Stacks (3 accounts)
# ═══════════════════════════════════════════════════════════
echo -e "\n${YELLOW}Step 6: Destroy LOB CDK Stacks${NC}"
for lob in lending-wealth transaction-banking retail-banking; do
    # Find all LobInfra stacks for this LOB
    STACKS=$(AWS_PROFILE="$lob" aws cloudformation list-stacks --region "$REGION" \
        --query "StackSummaries[?contains(StackName,'LobInfra-${lob}') && StackStatus!='DELETE_COMPLETE'].StackName" \
        --output text 2>/dev/null) || true
    if [ -z "$STACKS" ]; then
        warn "$lob: no stacks found — skipping"
        continue
    fi
    for stack in $STACKS; do
        AWS_PROFILE="$lob" aws cloudformation delete-stack --stack-name "$stack" --region "$REGION" 2>&1 || true
        AWS_PROFILE="$lob" aws cloudformation wait stack-delete-complete --stack-name "$stack" --region "$REGION" 2>&1 || true
        log "$lob: $stack destroyed"
    done
done

# ═══════════════════════════════════════════════════════════
# Step 7: Clean Up Local Config Files
# ═══════════════════════════════════════════════════════════
echo -e "\n${YELLOW}Step 7: Clean Up Local Config Files${NC}"
for f in \
    "$PROJECT_DIR/gateway_config.json" \
    "$PROJECT_DIR/registry_config.json" \
    "$PROJECT_DIR/platform-account/agent/runtime_config.json" \
    "$PROJECT_DIR/platform-account/gateway/gateway_config.json" \
    "$PROJECT_DIR/platform-account/gateway/runtime_arns.json"; do
    if [ -f "$f" ]; then
        rm -f "$f"
        log "Removed: $(realpath --relative-to="$PROJECT_DIR" "$f")"
    fi
done

echo -e "\n${GREEN}════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  Teardown complete!${NC}"
echo -e "${GREEN}════════════════════════════════════════════════════════════${NC}"
