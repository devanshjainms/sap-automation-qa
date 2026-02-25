#!/usr/bin/env bash
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
#
# deploy-persistent.sh — Deploy E2E persistent infrastructure,
# poll for completion, lock down Key Vault, and verify.
#
# Usage:
#   ./deploy-persistent.sh
#
# Environment variables (all optional — sensible defaults provided):
#   AZURE_SUBSCRIPTION_ID  — Target subscription (REQUIRED)
#   AZURE_LOCATION         — Azure region (default: swedencentral)
#   E2E_RESOURCE_GROUP     — Resource group name
#   E2E_BASE_NAME          — Base name for resource naming
#   POLL_INTERVAL          — Seconds between polls (default: 15)
#   MAX_POLL_MINUTES       — Maximum polling duration (default: 20)
#   GITHUB_REPO_URL        — Repository URL (default: https://github.com/Azure/sap-automation-qa)
#   RUNNER_LABELS          — Comma-separated labels (default: e2e-runner)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ===================================================================
# Configuration
# ===================================================================
SUB_ID="${AZURE_SUBSCRIPTION_ID:?'Set AZURE_SUBSCRIPTION_ID env var'}"
LOCATION="${AZURE_LOCATION:-swedencentral}"
RG_NAME="${E2E_RESOURCE_GROUP:-e2e-sap-automation-qa-1}"
BASE_NAME="${E2E_BASE_NAME:-e2eqa}"
POLL_INTERVAL="${POLL_INTERVAL:-15}"
MAX_POLL_MINUTES="${MAX_POLL_MINUTES:-20}"
MAX_POLL_ATTEMPTS=$(( MAX_POLL_MINUTES * 60 / POLL_INTERVAL ))
GITHUB_REPO_URL="${GITHUB_REPO_URL:-https://github.com/devanshjainms/sap-automation-qa}"
GITHUB_REPO_SLUG="${GITHUB_REPO_SLUG:-devanshjainms/sap-automation-qa}"
GITHUB_ENVIRONMENT="${GITHUB_ENVIRONMENT:-e2e}"
RUNNER_LABELS="${RUNNER_LABELS:-e2e-runner}"

# ===================================================================
# Helpers
# ===================================================================
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; }
header() { echo -e "\n${BOLD}${CYAN}$*${NC}"; }
fatal() { error "$@"; exit 1; }

# ===================================================================
# Pre-flight checks
# ===================================================================
header "============================================================"
header "  E2E Persistent Infrastructure Deployment"
header "============================================================"

echo ""
info "Location:      ${LOCATION}"
info "Resource Group: ${RG_NAME}"
info "Base Name:     ${BASE_NAME}"
echo ""

# Verify required tools
command -v az >/dev/null 2>&1 \
    || fatal "'az' is required but not found. Install it first."
command -v gh >/dev/null 2>&1 \
    || fatal "'gh' (GitHub CLI) is required but not found. Install it first: https://cli.github.com"

# Ensure gh is authenticated
if ! gh auth status >/dev/null 2>&1; then
    error "GitHub CLI is not authenticated."
    error "Run 'gh auth login' first, then re-run this script."
    exit 1
fi
info "GitHub CLI authenticated"

# Ensure logged in and set subscription
az account set --subscription "${SUB_ID}" 2>/dev/null \
    || fatal "Failed to set subscription. Run 'az login' first."

# Get deployer principal OID
DEPLOYER_OID=$(az ad signed-in-user show --query id -o tsv 2>/dev/null) \
    || fatal "Cannot determine signed-in user OID. Run 'az login'."
info "Deployer principal resolved"

# Generate random 4-char hex suffix for Key Vault name (avoids soft-delete collisions)
KV_SUFFIX=$(head -c 4 /dev/urandom | xxd -p | cut -c1-4)
info "Key Vault suffix: ${KV_SUFFIX}"

# ===================================================================
# Phase 1: Deploy persistent infrastructure
# ===================================================================
DEPLOY_NAME="deploy-$(date +%Y%m%d-%H%M%S)"

header "============================================================"
header "  Phase 1: Deploy persistent infrastructure"
header "============================================================"
echo ""
info "Deployment: ${DEPLOY_NAME}"

info "Submitting subscription-scope Bicep deployment..."
az deployment sub create \
    --name "${DEPLOY_NAME}" \
    --location "${LOCATION}" \
    --template-file "${SCRIPT_DIR}/deploy.bicep" \
    --parameters deployerPrincipalObjectId="${DEPLOYER_OID}" kvSuffix="${KV_SUFFIX}" \
                 githubRepoSlug="${GITHUB_REPO_SLUG}" githubEnvironment="${GITHUB_ENVIRONMENT}" \
    --no-wait \
    || fatal "Failed to submit deployment"
info "Deployment submitted"

# Poll deployment
info "Polling every ${POLL_INTERVAL}s (max ${MAX_POLL_MINUTES} min)..."
ELAPSED=0
STATE="Running"
for _attempt in $(seq 1 "${MAX_POLL_ATTEMPTS}"); do
    sleep "${POLL_INTERVAL}"
    ELAPSED=$(( ELAPSED + POLL_INTERVAL ))

    STATE=$(az deployment sub show \
        --name "${DEPLOY_NAME}" \
        --query "properties.provisioningState" -o tsv 2>/dev/null) \
        || STATE="Unknown"

    printf "  [%4ds] %s\n" "${ELAPSED}" "${STATE}"

    case "${STATE}" in
        Succeeded)
            info "Deployment succeeded after ${ELAPSED}s"
            break
            ;;
        Failed|Canceled)
            error "Deployment ${STATE} after ${ELAPSED}s"
            echo ""
            echo "--- Deployment errors ---"
            az deployment sub show \
                --name "${DEPLOY_NAME}" \
                --query "properties.error" -o json 2>/dev/null || true
            echo ""
            echo "--- Inner deployment failures ---"
            az deployment group list \
                --resource-group "${RG_NAME}" \
                --query "[?properties.provisioningState=='Failed'].{name:name, error:properties.error}" \
                -o json 2>/dev/null || true
            exit 1
            ;;
    esac
done

if [[ "${STATE}" != "Succeeded" ]]; then
    fatal "Deployment did not complete within ${MAX_POLL_MINUTES} minutes"
fi

# Extract outputs
echo ""
info "Extracting deployment outputs..."
KV_NAME=$(az deployment sub show --name "${DEPLOY_NAME}" \
    --query "properties.outputs.keyVaultName.value" -o tsv 2>/dev/null) || true
SA_NAME=$(az deployment sub show --name "${DEPLOY_NAME}" \
    --query "properties.outputs.storageAccountName.value" -o tsv 2>/dev/null) || true
ADMIN_USER=$(az deployment sub show --name "${DEPLOY_NAME}" \
    --query "properties.outputs.vmAdminUsername.value" -o tsv 2>/dev/null) || true
SUBNET_ID=$(az deployment sub show --name "${DEPLOY_NAME}" \
    --query "properties.outputs.subnetId.value" -o tsv 2>/dev/null) || true
MSI_ID=$(az deployment sub show --name "${DEPLOY_NAME}" \
    --query "properties.outputs.userAssignedIdentityId.value" -o tsv 2>/dev/null) || true
MSI_CLIENT_ID=$(az deployment sub show --name "${DEPLOY_NAME}" \
    --query "properties.outputs.userAssignedIdentityClientId.value" -o tsv 2>/dev/null) || true

echo ""
echo "  Resource Group:  ${RG_NAME}"
echo "  Key Vault:       ${KV_NAME}"
echo "  Storage Account: ${SA_NAME}"

[[ -z "${KV_NAME}" ]] && fatal "Key Vault name not found in outputs"

# ===================================================================
# Phase 2: Lock down Key Vault
# ===================================================================
header "============================================================"
header "  Phase 2: Lock down Key Vault"
header "============================================================"
echo ""

info "Disabling public network access on '${KV_NAME}'..."
az keyvault update \
    --name "${KV_NAME}" \
    --resource-group "${RG_NAME}" \
    --public-network-access Disabled \
    --default-action Deny \
    --bypass AzureServices \
    -o none 2>/dev/null \
    || fatal "Failed to lock down Key Vault"

info "Lock down command sent. Verifying..."

MAX_KV_POLL=20
PUB="unknown"
ACL="unknown"
for i in $(seq 1 "${MAX_KV_POLL}"); do
    sleep 5
    PUB=$(az keyvault show --name "${KV_NAME}" --resource-group "${RG_NAME}" \
        --query "properties.publicNetworkAccess" -o tsv 2>/dev/null) || continue
    ACL=$(az keyvault show --name "${KV_NAME}" --resource-group "${RG_NAME}" \
        --query "properties.networkAcls.defaultAction" -o tsv 2>/dev/null) || continue

    printf "  [%2d/%d] publicNetworkAccess=%-10s  defaultAction=%s\n" \
        "${i}" "${MAX_KV_POLL}" "${PUB}" "${ACL}"

    if [[ "${PUB}" == "Disabled" && "${ACL}" == "Deny" ]]; then
        info "Key Vault locked down successfully"
        break
    fi
done

if [[ "${PUB}" != "Disabled" || "${ACL}" != "Deny" ]]; then
    fatal "Key Vault lockdown verification failed after ${MAX_KV_POLL} attempts"
fi

# ===================================================================
# Phase 3: Verify all resources
# ===================================================================
header "============================================================"
header "  Phase 3: Verification"
header "============================================================"
echo ""

# List all resources
info "Resources in '${RG_NAME}':"
RES_COUNT=$(az resource list --resource-group "${RG_NAME}" \
    --query "length([])" -o tsv 2>/dev/null) || RES_COUNT="?"
echo "  Total resources: ${RES_COUNT}"
az resource list --resource-group "${RG_NAME}" \
    --query "sort_by([], &type)[].{type:type, name:name}" \
    -o table 2>/dev/null || warn "Failed to list resources"

# Verify KV access policies
echo ""
info "Key Vault access policies:"
POLICY_COUNT=$(az keyvault show --name "${KV_NAME}" --resource-group "${RG_NAME}" \
    --query "properties.accessPolicies | length([])" -o tsv 2>/dev/null) || POLICY_COUNT="?"
echo "  Access policies: ${POLICY_COUNT}"

# Verify secrets (management plane)
echo ""
info "Key Vault secrets (management plane):"
SECRET_COUNT=$(az keyvault secret list --vault-name "${KV_NAME}" \
    --query "length([])" -o tsv 2>/dev/null) || SECRET_COUNT="?"
echo "  Secrets: ${SECRET_COUNT}"
az keyvault secret list --vault-name "${KV_NAME}" \
    --query "[].name" -o tsv 2>/dev/null | sort | sed 's/^/    /' || true

# Verify runner VM
echo ""
info "Runner VM status:"
RUNNER_VM_NAME=$(az vm list --resource-group "${RG_NAME}" \
    --query "[?tags.role=='github-runner'].name | [0]" -o tsv 2>/dev/null) || true

if [[ -n "${RUNNER_VM_NAME}" ]]; then
    PROV=$(az vm show --resource-group "${RG_NAME}" --name "${RUNNER_VM_NAME}" \
        --query "provisioningState" -o tsv 2>/dev/null) || PROV="?"
    POWER=$(az vm get-instance-view --resource-group "${RG_NAME}" --name "${RUNNER_VM_NAME}" \
        --query "instanceView.statuses[?starts_with(code,'PowerState')].displayStatus | [0]" \
        -o tsv 2>/dev/null) || POWER="?"
    echo "  VM:            ${RUNNER_VM_NAME}"
    echo "  Provisioning:  ${PROV}"
    echo "  Power state:   ${POWER}"
else
    warn "No runner VM found with tag role=github-runner"
fi

# ===================================================================
# Phase 4: Register GitHub Actions runner (optional)
# ===================================================================
if [[ -n "${RUNNER_VM_NAME}" ]]; then
    header "============================================================"
    header "  Phase 4: Register GitHub Actions runner"
    header "============================================================"
    echo ""

    # Auto-fetch runner registration token via gh API
    info "Fetching runner registration token via gh API..."
    GITHUB_RUNNER_TOKEN=$(gh api \
        --method POST \
        "repos/${GITHUB_REPO_SLUG}/actions/runners/registration-token" \
        --jq '.token' 2>/dev/null) \
        || fatal "Failed to fetch runner token. Ensure you have admin access to ${GITHUB_REPO_SLUG}"

    if [[ -z "${GITHUB_RUNNER_TOKEN}" ]]; then
        fatal "Runner token is empty. Check repo permissions."
    fi
    info "Runner token obtained (expires in 1 hour)"

    info "Registering runner on '${RUNNER_VM_NAME}' via az vm run-command..."

    REGISTER_SCRIPT=$(cat <<'RUNEOF'
set -e
RUNNER_DIR="/opt/actions-runner"
RUNNER_USER="__RUNNER_USER__"
REPO_URL="__REPO_URL__"
TOKEN="__TOKEN__"
LABELS="__LABELS__"

# Remove old registration if present
if [[ -f "${RUNNER_DIR}/.runner" ]]; then
    echo "Removing old runner registration..."
    su - "${RUNNER_USER}" -c "cd ${RUNNER_DIR} && ./config.sh remove --token ${TOKEN}" || true
fi

# Configure
su - "${RUNNER_USER}" -c "cd ${RUNNER_DIR} && ./config.sh \
    --url '${REPO_URL}' \
    --token '${TOKEN}' \
    --labels '${LABELS}' \
    --name '$(hostname)' \
    --work _work \
    --unattended \
    --replace"

# Install and start as systemd service
cd "${RUNNER_DIR}"
./svc.sh install "${RUNNER_USER}" 2>/dev/null || true
./svc.sh start 2>/dev/null || true

echo "Runner registered and service started successfully"
RUNEOF
)

    # Substitute placeholders
    REGISTER_SCRIPT="${REGISTER_SCRIPT//__RUNNER_USER__/${ADMIN_USER}}"
    REGISTER_SCRIPT="${REGISTER_SCRIPT//__REPO_URL__/${GITHUB_REPO_URL}}"
    REGISTER_SCRIPT="${REGISTER_SCRIPT//__TOKEN__/${GITHUB_RUNNER_TOKEN}}"
    REGISTER_SCRIPT="${REGISTER_SCRIPT//__LABELS__/${RUNNER_LABELS}}"

    RUN_OUTPUT=$(az vm run-command invoke \
        --resource-group "${RG_NAME}" \
        --name "${RUNNER_VM_NAME}" \
        --command-id RunShellScript \
        --scripts "${REGISTER_SCRIPT}" \
        --query "value[0].message" -o tsv 2>/dev/null) \
        || warn "run-command failed — register runner manually"

    echo "${RUN_OUTPUT:-}"

    if echo "${RUN_OUTPUT:-}" | grep -q "successfully"; then
        info "Runner registered and running"
    else
        warn "Check output above — runner may need manual registration"
    fi
else
    warn "No runner VM found — skipping runner registration (Phase 4)"
fi

# Final summary
echo ""
header "============================================================"
info "All phases complete. Infrastructure is deployed and locked down."
header "============================================================"
echo ""
echo "  Key Vault:       ${KV_NAME} (publicNetworkAccess=Disabled)"
echo "  Storage Account: ${SA_NAME}"
echo "  Subnet ID:       ${SUBNET_ID}"
echo "  MSI ID:          ${MSI_ID}"
echo "  MSI Client ID:   ${MSI_CLIENT_ID}"
echo "  Runner VM:       ${RUNNER_VM_NAME:-N/A}"
echo "  Secrets:         ${SECRET_COUNT}"

# ===================================================================
# Phase 5: Create GitHub Environment secrets
# ===================================================================
TENANT_ID=$(az account show --query tenantId -o tsv 2>/dev/null) || TENANT_ID=""

header "============================================================"
header "  Phase 5: Create GitHub Environment secrets"
header "============================================================"
echo ""

GH_REPO="${GITHUB_REPO_SLUG}"
info "Target repo:        ${GH_REPO}"
info "Target environment: ${GITHUB_ENVIRONMENT}"
echo ""

# Ensure the environment exists
gh api --method PUT \
    "repos/${GH_REPO}/environments/${GITHUB_ENVIRONMENT}" \
    --silent 2>/dev/null \
    || warn "Could not create environment (may already exist or need admin)"

_set_env_secret() {
    local name="$1" value="$2"
    if echo "${value}" | gh secret set "${name}" \
        --repo "${GH_REPO}" \
        --env "${GITHUB_ENVIRONMENT}" 2>/dev/null; then
        info "  Set: ${name}"
    else
        warn "  Failed to set: ${name}"
    fi
}

_set_env_secret "AZURE_CLIENT_ID"           "${MSI_CLIENT_ID}"
_set_env_secret "AZURE_TENANT_ID"           "${TENANT_ID}"
_set_env_secret "E2E_AZURE_SUBSCRIPTION_ID" "${SUB_ID}"
_set_env_secret "E2E_KEY_VAULT_NAME"        "${KV_NAME}"

echo ""
info "All 4 GitHub Environment secrets set in '${GITHUB_ENVIRONMENT}'"

echo ""
echo "  Everything else is loaded from Key Vault at workflow runtime."
echo ""
