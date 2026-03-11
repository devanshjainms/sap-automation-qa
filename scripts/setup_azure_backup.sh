#!/usr/bin/env bash
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
#
# setup_azure_backup.sh — Automate Azure Backup setup for SAP HANA (HSR or standalone)
#
# Steps:
#   1. Create a Recovery Services vault
#   2. Run the pre-registration script on VM(s) via az vm run-command
#   3. Register VM(s) (containers) to the vault
#   4. Discover protectable HANA databases
#   5. Create a backup policy (full + log + differential)
#   6. Enable protection on discovered databases
#
# Supports both HSR (two-VM) and standalone (single-VM) modes.
# When --secondary-vm and --hsr-unique-id are omitted, runs in standalone mode.
#
# Reference:
#   https://learn.microsoft.com/en-us/azure/backup/quick-backup-hana-cli
#   https://learn.microsoft.com/en-us/azure/backup/sap-hana-database-with-hana-system-replication-backup

set -euo pipefail

# ──────────────────────────────────────────────
# Configuration — edit these or pass via env vars
# ──────────────────────────────────────────────
SUBSCRIPTION="${SUBSCRIPTION:-}"
RESOURCE_GROUP="${RESOURCE_GROUP:-}"
VM_RESOURCE_GROUP="${VM_RESOURCE_GROUP:-}"  # RG containing the VMs (defaults to RESOURCE_GROUP)
LOCATION="${LOCATION:-}"
VAULT_NAME="${VAULT_NAME:-}"
PRIMARY_VM="${PRIMARY_VM:-}"
SECONDARY_VM="${SECONDARY_VM:-}"
SID="${SID:-}"
INSTANCE_NUMBER="${INSTANCE_NUMBER:-00}"
BACKUP_KEY="${BACKUP_KEY:-AZUREWLBACKUPHANAUSER}"
HSR_UNIQUE_ID="${HSR_UNIQUE_ID:-}"
POLICY_NAME="${POLICY_NAME:-sap-hana-backup-policy}"
STORAGE_REDUNDANCY="${STORAGE_REDUNDANCY:-GeoRedundant}"
DATABASE_NAMES="${DATABASE_NAMES:-}"   # comma-separated, e.g. "SYSTEMDB,DB1"
HA_MODE=false                            # auto-detected: true when secondary-vm + hsr-unique-id provided

# Pre-registration script URL
PREREG_SCRIPT_URL="https://aka.ms/ScriptForPermsOnHANA"

# ──────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────
log() {
    local level="$1"; shift
    printf "[%s] [%-5s] %s\n" "$(date '+%Y-%m-%d %H:%M:%S')" "$level" "$*"
}

info()  { log "INFO"  "$@"; }
warn()  { log "WARN"  "$@"; }
error() { log "ERROR" "$@"; }
fatal() { error "$@"; exit 1; }

# ──────────────────────────────────────────────
# Validation
# ──────────────────────────────────────────────
show_usage() {
    cat << 'EOF'
Usage: setup_azure_backup.sh [OPTIONS]

Required:
  --subscription          Azure Subscription ID
  --resource-group        Resource group for the Recovery Services vault
  --location              Azure region (e.g., eastus2)
  --vault-name            Recovery Services vault name
  --primary-vm            Primary HANA VM name
  --sid                   SAP HANA System ID (e.g., HDB)

HSR mode (both required for HA):
  --secondary-vm          Secondary HANA VM name
  --hsr-unique-id         Unique HSR identifier (6-35 chars, alphanumeric)

Optional:
  --vm-resource-group     Resource group containing the HANA VMs (default: same as --resource-group)
  --instance-number       HANA instance number (default: 00)
  --backup-key            hdbuserstore key for backup user (default: AZUREWLBACKUPHANAUSER)
  --policy-name           Backup policy name (default: sap-hana-backup-policy)
  --storage-redundancy    Vault storage redundancy: GeoRedundant|LocallyRedundant (default: GeoRedundant)
  --database-names        Comma-separated DB names to protect (default: auto-discover all)
  --skip-prereg           Skip running pre-registration script on VMs
  --skip-vault            Skip vault creation (use existing vault)
  --skip-policy           Skip policy creation (use existing policy)
  -h, --help              Show this help

Examples:
  # Full setup for HSR (two VMs, same resource group)
  ./setup_azure_backup.sh \
    --subscription "aaaa-bbbb-cccc" \
    --resource-group "sap-hana-rg" \
    --location "eastus2" \
    --vault-name "sap-hana-vault" \
    --primary-vm "hana-vm1" \
    --secondary-vm "hana-vm2" \
    --sid "HDB" \
    --instance-number "00" \
    --hsr-unique-id "HSRProd01"

  # Standalone (non-HA) single VM, vault in a different RG
  ./setup_azure_backup.sh \
    --subscription "aaaa-bbbb-cccc" \
    --resource-group "vault-rg" \
    --vm-resource-group "vm-rg" \
    --location "eastus2" \
    --vault-name "hana-vault" \
    --primary-vm "hana-vm1" \
    --sid "HDB"

  # Skip vault creation, use existing
  ./setup_azure_backup.sh \
    --subscription "aaaa-bbbb-cccc" \
    --resource-group "sap-hana-rg" \
    --location "eastus2" \
    --vault-name "existing-vault" \
    --primary-vm "hana-vm1" \
    --secondary-vm "hana-vm2" \
    --sid "HDB" \
    --hsr-unique-id "HSRProd01" \
    --skip-vault
EOF
}

SKIP_PREREG=false
SKIP_VAULT=false
SKIP_POLICY=false

parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --subscription)       SUBSCRIPTION="$2";       shift 2 ;;
            --resource-group)     RESOURCE_GROUP="$2";     shift 2 ;;
            --vm-resource-group)  VM_RESOURCE_GROUP="$2";  shift 2 ;;
            --location)           LOCATION="$2";           shift 2 ;;
            --vault-name)         VAULT_NAME="$2";         shift 2 ;;
            --primary-vm)         PRIMARY_VM="$2";         shift 2 ;;
            --secondary-vm)       SECONDARY_VM="$2";       shift 2 ;;
            --sid)                SID="$2";                shift 2 ;;
            --instance-number)    INSTANCE_NUMBER="$2";    shift 2 ;;
            --backup-key)         BACKUP_KEY="$2";         shift 2 ;;
            --hsr-unique-id)      HSR_UNIQUE_ID="$2";      shift 2 ;;
            --policy-name)        POLICY_NAME="$2";        shift 2 ;;
            --storage-redundancy) STORAGE_REDUNDANCY="$2"; shift 2 ;;
            --database-names)     DATABASE_NAMES="$2";     shift 2 ;;
            --skip-prereg)        SKIP_PREREG=true;        shift   ;;
            --skip-vault)         SKIP_VAULT=true;         shift   ;;
            --skip-policy)        SKIP_POLICY=true;        shift   ;;
            -h|--help)            show_usage; exit 0               ;;
            *) fatal "Unknown option: $1. Use --help for usage."   ;;
        esac
    done
}

validate_params() {
    local missing=()
    [[ -z "$SUBSCRIPTION" ]]   && missing+=("--subscription")
    [[ -z "$RESOURCE_GROUP" ]] && missing+=("--resource-group")
    [[ -z "$LOCATION" ]]       && missing+=("--location")
    [[ -z "$VAULT_NAME" ]]     && missing+=("--vault-name")
    [[ -z "$PRIMARY_VM" ]]     && missing+=("--primary-vm")
    [[ -z "$SID" ]]            && missing+=("--sid")

    if [[ ${#missing[@]} -gt 0 ]]; then
        fatal "Missing required parameters: ${missing[*]}"
    fi

    # Default VM_RESOURCE_GROUP to RESOURCE_GROUP if not specified
    VM_RESOURCE_GROUP="${VM_RESOURCE_GROUP:-$RESOURCE_GROUP}"

    # Determine HA vs standalone mode
    if [[ -n "$SECONDARY_VM" && -n "$HSR_UNIQUE_ID" ]]; then
        HA_MODE=true
        info "Mode: HSR (High Availability) — two VMs"
    elif [[ -n "$SECONDARY_VM" || -n "$HSR_UNIQUE_ID" ]]; then
        fatal "HSR mode requires both --secondary-vm and --hsr-unique-id. Provide both or neither."
    else
        HA_MODE=false
        info "Mode: Standalone (single VM, non-HA)"
    fi

    # Validate HSR unique ID format when in HA mode
    if [[ "$HA_MODE" == "true" ]]; then
        if [[ ${#HSR_UNIQUE_ID} -lt 6 || ${#HSR_UNIQUE_ID} -gt 35 ]]; then
            fatal "HSR_UNIQUE_ID must be 6-35 characters. Got: ${#HSR_UNIQUE_ID}"
        fi
    fi

    # Validate combined VM name + VM RG length <= 84
    local combined_len=$(( ${#PRIMARY_VM} + ${#VM_RESOURCE_GROUP} ))
    if [[ $combined_len -gt 84 ]]; then
        fatal "Combined VM name + resource group length ($combined_len) exceeds 84 characters."
    fi
}

check_az_cli() {
    if ! command -v az &>/dev/null; then
        fatal "Azure CLI (az) is not installed. Install from https://aka.ms/installazurecli"
    fi
    # Ensure logged in
    if ! az account show &>/dev/null; then
        fatal "Not logged in to Azure CLI. Run 'az login' first."
    fi
    az account set --subscription "$SUBSCRIPTION"
    info "Using subscription: $SUBSCRIPTION"
}

# ──────────────────────────────────────────────
# Helper: get VM resource ID
# ──────────────────────────────────────────────
get_vm_resource_id() {
    local vm_name="$1"
    az vm show \
        --name "$vm_name" \
        --resource-group "$VM_RESOURCE_GROUP" \
        --query "id" -o tsv 2>/dev/null \
    || fatal "VM '$vm_name' not found in resource group '$VM_RESOURCE_GROUP'"
}

# ──────────────────────────────────────────────
# Helper: wait for container registration
# ──────────────────────────────────────────────
wait_for_registration() {
    local vm_name="$1"
    local max_attempts=30
    local attempt=0

    info "Waiting for '$vm_name' to register with vault..."
    while [[ $attempt -lt $max_attempts ]]; do
        local status
        status=$(az backup container list \
            --resource-group "$RESOURCE_GROUP" \
            --vault-name "$VAULT_NAME" \
            --backup-management-type AzureWorkload \
            --query "[?properties.friendlyName=='$vm_name'].properties.registrationStatus" \
            -o tsv 2>/dev/null || echo "")

        if [[ "$status" == "Registered" ]]; then
            info "VM '$vm_name' registered successfully."
            return 0
        fi
        ((attempt++))
        sleep 10
    done
    fatal "Timeout waiting for '$vm_name' registration after $((max_attempts * 10))s"
}

# ──────────────────────────────────────────────
# Step 1: Create Recovery Services Vault
# ──────────────────────────────────────────────
create_vault() {
    if [[ "$SKIP_VAULT" == "true" ]]; then
        info "Skipping vault creation (--skip-vault)."
        return 0
    fi

    info "Creating Recovery Services vault '$VAULT_NAME' in '$LOCATION'..."

    # Check if vault already exists
    local existing
    existing=$(az backup vault show \
        --resource-group "$RESOURCE_GROUP" \
        --name "$VAULT_NAME" \
        --query "name" -o tsv 2>/dev/null || echo "")

    if [[ -n "$existing" ]]; then
        info "Vault '$VAULT_NAME' already exists. Skipping creation."
    else
        az backup vault create \
            --resource-group "$RESOURCE_GROUP" \
            --name "$VAULT_NAME" \
            --location "$LOCATION" \
            --output none

        info "Vault '$VAULT_NAME' created."
    fi

    # Set storage redundancy
    info "Setting storage redundancy to '$STORAGE_REDUNDANCY'..."
    az backup vault backup-properties set \
        --resource-group "$RESOURCE_GROUP" \
        --name "$VAULT_NAME" \
        --backup-storage-redundancy "$STORAGE_REDUNDANCY" \
        --output none 2>/dev/null || warn "Could not set storage redundancy (vault may already have protected items)."

    info "Vault setup complete."
}

# ──────────────────────────────────────────────
# Step 2: Run pre-registration script via
#         az vm run-command on both VMs
# ──────────────────────────────────────────────
run_prereg_script() {
    if [[ "$SKIP_PREREG" == "true" ]]; then
        info "Skipping pre-registration script (--skip-prereg)."
        return 0
    fi

    local port
    # MDC port format: 3<instance_number>13
    port="3${INSTANCE_NUMBER}13"

    # Build VM list
    local -a vm_list=("$PRIMARY_VM")
    if [[ "$HA_MODE" == "true" ]]; then
        vm_list+=("$SECONDARY_VM")
    fi

    info "Running pre-registration script on ${#vm_list[@]} VM(s)..."
    info "  SID=$SID, Instance=$INSTANCE_NUMBER, Port=$port"
    if [[ "$HA_MODE" == "true" ]]; then
        info "  HSR_ID=$HSR_UNIQUE_ID"
    fi

    # Build HSR-specific flags for the pre-registration script
    local hsr_flags=""
    if [[ "$HA_MODE" == "true" ]]; then
        hsr_flags="-hn ${HSR_UNIQUE_ID}"
    fi

    for vm_name in "${vm_list[@]}"; do
        info "Running pre-registration script on '$vm_name'..."
        az vm run-command invoke \
            --resource-group "$VM_RESOURCE_GROUP" \
            --name "$vm_name" \
            --command-id RunShellScript \
            --scripts "
                sudo su
                set -e
                SCRIPT_PATH='/tmp/msawb-plugin-config-com-sap-hana.sh'

                # Download the latest pre-registration script
                curl -sSL '${PREREG_SCRIPT_URL}' -o \"\${SCRIPT_PATH}\"
                chmod +x \"\${SCRIPT_PATH}\"

                # Run the pre-registration script
                \"\${SCRIPT_PATH}\" -a \
                    -s ${SID} \
                    -n ${INSTANCE_NUMBER} \
                    -sk SYSTEMKEY \
                    -bk ${BACKUP_KEY} \
                    ${hsr_flags} \
                    -p ${port} \
                    -sn
            " \
            --output none \
        && info "Pre-registration script completed on '$vm_name'." \
        || warn "Pre-registration script may have failed on '$vm_name'. Check VM logs."
    done
}

# ──────────────────────────────────────────────
# Step 3: Register VMs (containers) to vault
# ──────────────────────────────────────────────
register_containers() {
    info "Registering VM containers to vault..."

    # Build VM list
    local -a vm_list=("$PRIMARY_VM")
    if [[ "$HA_MODE" == "true" ]]; then
        vm_list+=("$SECONDARY_VM")
    fi

    for vm_name in "${vm_list[@]}"; do
        local resource_id
        resource_id=$(get_vm_resource_id "$vm_name")

        # Check if already registered
        local reg_status
        reg_status=$(az backup container list \
            --resource-group "$RESOURCE_GROUP" \
            --vault-name "$VAULT_NAME" \
            --backup-management-type AzureWorkload \
            --query "[?properties.friendlyName=='$vm_name'].properties.registrationStatus" \
            -o tsv 2>/dev/null || echo "")

        if [[ "$reg_status" == "Registered" ]]; then
            info "VM '$vm_name' is already registered. Skipping."
            continue
        fi

        info "Registering '$vm_name' (resource-id: $resource_id)..."
        az backup container register \
            --resource-group "$RESOURCE_GROUP" \
            --vault-name "$VAULT_NAME" \
            --workload-type SAPHANA \
            --backup-management-type AzureWorkload \
            --resource-id "$resource_id" \
            --output none

        wait_for_registration "$vm_name"
    done

    info "Container registration complete."

    # Verify registered containers
    info "Registered containers:"
    az backup container list \
        --resource-group "$RESOURCE_GROUP" \
        --vault-name "$VAULT_NAME" \
        --backup-management-type AzureWorkload \
        --output table
}

# ──────────────────────────────────────────────
# Step 4: Discover protectable HANA databases
# ──────────────────────────────────────────────
discover_databases() {
    info "Initiating database discovery on primary VM..."

    local container_name="VMAppContainer;Compute;${VM_RESOURCE_GROUP};${PRIMARY_VM}"

    az backup protectable-item initialize \
        --resource-group "$RESOURCE_GROUP" \
        --vault-name "$VAULT_NAME" \
        --container-name "$container_name" \
        --workload-type SAPHanaDatabase \
        --output none

    info "Discovery initiated. Waiting for discovery to complete..."
    sleep 30

    info "Discovered protectable items:"
    az backup protectable-item list \
        --resource-group "$RESOURCE_GROUP" \
        --vault-name "$VAULT_NAME" \
        --workload-type SAPHANA \
        --output table
}

# ──────────────────────────────────────────────
# Step 5: Create backup policy
# ──────────────────────────────────────────────
create_backup_policy() {
    if [[ "$SKIP_POLICY" == "true" ]]; then
        info "Skipping policy creation (--skip-policy)."
        return 0
    fi

    info "Creating backup policy '$POLICY_NAME'..."

    # Check if policy already exists
    local existing_policy
    existing_policy=$(az backup policy show \
        --resource-group "$RESOURCE_GROUP" \
        --vault-name "$VAULT_NAME" \
        --name "$POLICY_NAME" \
        --query "name" -o tsv 2>/dev/null || echo "")

    if [[ -n "$existing_policy" ]]; then
        info "Policy '$POLICY_NAME' already exists. Skipping creation."
        return 0
    fi

    local tmp_policy
    tmp_policy=$(mktemp /tmp/backup-policy-XXXXXX.json)

    # Policy: Full weekly (Sunday 02:00 UTC, retain 12 weeks)
    #         Differential daily Mon-Sat (06:00 UTC, retain 30 days)
    #         Log every 15 minutes (retain 15 days)
    cat > "$tmp_policy" << 'POLICY_EOF'
{
    "properties": {
        "backupManagementType": "AzureWorkload",
        "workLoadType": "SAPHanaDatabase",
        "settings": {
            "timeZone": "UTC",
            "issqlcompression": false,
            "isCompression": false
        },
        "subProtectionPolicy": [
            {
                "policyType": "Full",
                "schedulePolicy": {
                    "schedulePolicyType": "SimpleSchedulePolicy",
                    "scheduleRunFrequency": "Weekly",
                    "scheduleRunDays": [
                        "Sunday"
                    ],
                    "scheduleRunTimes": [
                        "2026-01-01T02:00:00Z"
                    ],
                    "scheduleWeeklyFrequency": 0
                },
                "retentionPolicy": {
                    "retentionPolicyType": "LongTermRetentionPolicy",
                    "weeklySchedule": {
                        "daysOfTheWeek": [
                            "Sunday"
                        ],
                        "retentionTimes": [
                            "2026-01-01T02:00:00Z"
                        ],
                        "retentionDuration": {
                            "count": 12,
                            "durationType": "Weeks"
                        }
                    },
                    "monthlySchedule": null,
                    "yearlySchedule": null
                }
            },
            {
                "policyType": "Differential",
                "schedulePolicy": {
                    "schedulePolicyType": "SimpleSchedulePolicy",
                    "scheduleRunFrequency": "Weekly",
                    "scheduleRunDays": [
                        "Monday",
                        "Tuesday",
                        "Wednesday",
                        "Thursday",
                        "Friday",
                        "Saturday"
                    ],
                    "scheduleRunTimes": [
                        "2026-01-01T06:00:00Z"
                    ],
                    "scheduleWeeklyFrequency": 0
                },
                "retentionPolicy": {
                    "retentionPolicyType": "SimpleRetentionPolicy",
                    "retentionDuration": {
                        "count": 30,
                        "durationType": "Days"
                    }
                }
            },
            {
                "policyType": "Log",
                "schedulePolicy": {
                    "schedulePolicyType": "LogSchedulePolicy",
                    "scheduleFrequencyInMins": 15
                },
                "retentionPolicy": {
                    "retentionPolicyType": "SimpleRetentionPolicy",
                    "retentionDuration": {
                        "count": 15,
                        "durationType": "Days"
                    }
                }
            }
        ]
    }
}
POLICY_EOF

    az backup policy create \
        --resource-group "$RESOURCE_GROUP" \
        --vault-name "$VAULT_NAME" \
        --name "$POLICY_NAME" \
        --backup-management-type AzureWorkload \
        --workload-type SAPHanaDatabase \
        --policy "$tmp_policy" \
        --output none

    rm -f "$tmp_policy"
    info "Backup policy '$POLICY_NAME' created."
}

# ──────────────────────────────────────────────
# Step 6: Enable protection on discovered databases
# ──────────────────────────────────────────────
enable_protection() {
    info "Enabling backup protection on discovered databases..."

    # In HA mode, look for HSR container parent for --server-name parameter
    local hsr_parent=""
    if [[ "$HA_MODE" == "true" ]]; then
        hsr_parent=$(az backup protectable-item list \
            --resource-group "$RESOURCE_GROUP" \
            --vault-name "$VAULT_NAME" \
            --workload-type SAPHANA \
            --query "[?properties.protectableItemType=='HanaHSRContainer'].properties.parentName" \
            -o tsv 2>/dev/null | head -1)

        if [[ -z "$hsr_parent" ]]; then
            warn "No HSR container found. Databases may need to be protected individually."
        else
            info "HSR container parent: $hsr_parent"
        fi
    fi

    # Get list of SAPHanaDatabase items
    local -a dbs
    if [[ -n "$DATABASE_NAMES" ]]; then
        # User specified databases
        IFS=',' read -ra dbs <<< "$DATABASE_NAMES"
    else
        # Auto-discover all SAPHanaDatabase items under HSR container
        mapfile -t dbs < <(az backup protectable-item list \
            --resource-group "$RESOURCE_GROUP" \
            --vault-name "$VAULT_NAME" \
            --workload-type SAPHANA \
            --query "[?properties.protectableItemType=='SAPHanaDatabase'].name" \
            -o tsv 2>/dev/null)
    fi

    if [[ ${#dbs[@]} -eq 0 ]]; then
        # Check if databases are already protected
        local protected_count
        protected_count=$(az backup item list \
            --resource-group "$RESOURCE_GROUP" \
            --vault-name "$VAULT_NAME" \
            --query "length([?properties.workloadType=='SAPHanaDatabase'])" \
            -o tsv 2>/dev/null || echo "0")

        if [[ "$protected_count" -gt 0 ]]; then
            info "All $protected_count database(s) are already protected. Nothing to do."
            az backup item list \
                --resource-group "$RESOURCE_GROUP" \
                --vault-name "$VAULT_NAME" \
                --output table
            return 0
        fi

        warn "No protectable HANA databases found. Verify discovery completed."
        return 1
    fi

    info "Found ${#dbs[@]} database(s) to protect."

    for db_item in "${dbs[@]}"; do
        info "Enabling protection for '$db_item'..."

        # Get the server-name for this specific item
        local server_name
        server_name=$(az backup protectable-item list \
            --resource-group "$RESOURCE_GROUP" \
            --vault-name "$VAULT_NAME" \
            --workload-type SAPHANA \
            --query "[?properties.protectableItemType=='SAPHanaDatabase' && name=='$db_item'].properties.serverName" \
            -o tsv 2>/dev/null | head -1)
        server_name="${server_name:-$hsr_parent}"

        info "  Using server-name: $server_name"

        az backup protection enable-for-azurewl \
            --resource-group "$RESOURCE_GROUP" \
            --vault-name "$VAULT_NAME" \
            --policy-name "$POLICY_NAME" \
            --protectable-item-name "$db_item" \
            --protectable-item-type SAPHanaDatabase \
            --workload-type SAPHanaDatabase \
            --server-name "$server_name" \
            --output table \
        && info "Protection enabled for '$db_item'." \
        || warn "Failed to enable protection for '$db_item'."
    done

    info "Backup protection setup complete."
}

# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────
main() {
    parse_args "$@"
    validate_params
    check_az_cli

    local mode_label="Standalone"
    if [[ "$HA_MODE" == "true" ]]; then
        mode_label="HSR (High Availability)"
    fi

    info "============================================="
    info "Azure Backup Setup for SAP HANA — $mode_label"
    info "============================================="
    info "  Vault:            $VAULT_NAME"
    info "  Vault RG:         $RESOURCE_GROUP"
    info "  VM RG:            $VM_RESOURCE_GROUP"
    info "  Location:         $LOCATION"
    info "  Primary VM:       $PRIMARY_VM"
    if [[ "$HA_MODE" == "true" ]]; then
        info "  Secondary VM:     $SECONDARY_VM"
        info "  HSR Unique ID:    $HSR_UNIQUE_ID"
    fi
    info "  SID:              $SID"
    info "  Policy:           $POLICY_NAME"
    info "============================================="
    echo ""

    create_vault
    echo ""
    run_prereg_script
    echo ""
    register_containers
    echo ""
    discover_databases
    echo ""
    create_backup_policy
    echo ""
    enable_protection

    echo ""
    info "============================================="
    info "Azure Backup setup completed successfully!"
    info "============================================="
    info ""
    info "Next steps:"
    info "  1. Verify backup health:  az backup item list --resource-group $RESOURCE_GROUP --vault-name $VAULT_NAME --output table"
    info "  2. Run on-demand backup:  az backup protection backup-now --resource-group $RESOURCE_GROUP --vault-name $VAULT_NAME --item-name <item> --container-name <container> --backup-type Full"
    info "  3. Run QA tests:          ./sap_automation_qa.sh --test_groups=BACKUP_DB_HANA --test_cases=[backup-setup-verification]"
    info ""
    info "Docs: https://learn.microsoft.com/en-us/azure/backup/sap-hana-database-with-hana-system-replication-backup"
}

main "$@"
