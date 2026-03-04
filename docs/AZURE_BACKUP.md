# Azure Backup Functional Testing for SAP HANA

The SAP Testing Automation Framework includes an Azure Backup testing component that validates backup and restore operations for SAP HANA databases deployed on Azure. It exercises the [Azure Backup for SAP HANA](https://learn.microsoft.com/azure/backup/sap-hana-database-about) service through the Python SDK (`azure-mgmt-recoveryservicesbackup`) and native HANA recovery commands.

## Supported Scenarios

The framework supports both **HA (two-node cluster)** and **Non-HA (single-node)** HANA deployments. Five test cases cover the end-to-end backup-restore lifecycle:

| # | Test Case | Task Name | Description |
|---|-----------|-----------|-------------|
| 1 | Azure Backup Setup Verification | `backup-setup-verification` | Discovers all protected HANA databases in the Recovery Services vault, verifies backup configuration health, and checks that recent restore points exist. |
| 2 | Restore Backup to HANA DB | `restore-to-db` | Triggers a full or point-in-time restore to the original HANA database via Azure Backup, monitors the restore job, then validates HANA is running. |
| 3 | Restore Backup to FileSystem | `restore-to-filesystem` | Restores the HANA backup as files to a filesystem path, verifies the files are present, then recovers the HANA DB from those files and validates it is operational. |
| 4 | Recover DB using Database Commands | `recover-db-commands` | Tests native HANA recovery using `recoverSys.py` / `RECOVER DATA`. Queries the backup catalog, stops HANA, performs recovery, restarts, and validates consistency. |
| 5 | Cross-VM Restore | `restore-cross-vm` | Restores a HANA backup from VM-1 to VM-2 (AlternateWorkloadRestore). Validates the target HANA instance starts and the database is consistent. Requires ≥ 2 HANA nodes. |

## Prerequisites

### 1. Azure Backup Configuration

- A **Recovery Services vault** must exist with SAP HANA backup configured.
- At least one HANA database must be **registered and protected** with a backup policy.
- A recent backup (full or incremental) must have completed successfully so restore points are available.

For setup guidance, see [Back up SAP HANA databases in Azure VMs](https://learn.microsoft.com/azure/backup/sap-hana-database-instances-backup).

### 2. Managed Identity Permissions

The management server's managed identity (system- or user-assigned) requires:

| Role | Scope | Purpose |
|------|-------|---------|
| **Backup Operator** | Recovery Services vault | Discover protected items, list restore points, trigger restore operations, monitor restore jobs |
| **Reader** | HANA VM resource group | Resolve target VM ARM IDs for cross-VM and filesystem restores |

For identity setup, see [Setup Guide — Identity and Authorization](./SETUP.MD#4-identity-and-authorization).

### 3. HANA Node Access

- The management server must have SSH connectivity to all HANA DB hosts.
- The `<sid>adm` user must be able to run `HDB stop`, `HDB start`, `sapcontrol`, and `hdbsql` commands.
- For test case 3 (restore-to-filesystem), the target filesystem path must be writable.
- For test case 5 (cross-VM restore), at least 2 HANA nodes must be in the inventory.

## Configuration

### 1. Update `vars.yaml`

Set the test type to `AzureBackupDatabase`:

```yaml
TEST_TYPE:                  SAPFunctionalTests
SAP_FUNCTIONAL_TEST_TYPE:   AzureBackupDatabase
```

### 2. Configure Backup Parameters

Add the following variables to your system's `sap-parameters.yaml` file (under `WORKSPACES/SYSTEM/<SYSTEM_CONFIG_NAME>/`):

```yaml
# Required: Recovery Services vault resource ID
backup_vault_resource_id:         "/subscriptions/xxxx/resourceGroups/my-backup-rg/providers/Microsoft.RecoveryServices/vaults/my-rsv-vault"

# Required for restore test cases (2-5)
backup_container_name:            "VMAppContainer;Compute;my-rg;hanavm01"
backup_item_name:                 "saphanadatabase;h05;systemdb"

# Required for filesystem restore (test case 3)
backup_target_filesystem_path:    "/hana/backup/restore"

# Required for cross-VM restore (test case 5)
backup_target_container_name:     "VMAppContainer;Compute;my-rg;hanavm02"
backup_target_database_name:      "SYSTEMDB"

# Optional: point-in-time restore (ISO 8601 UTC timestamp)
backup_restore_point_time:        ""
```

### 3. User-Assigned Managed Identity (Optional)

If your management server uses a user-assigned managed identity, set the client ID in `vars.yaml`:

```yaml
user_assigned_identity_client_id: "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
```

If omitted or set to `null`, the framework uses system-assigned managed identity.

## Test Execution

Run the tests using the `sap_automation_qa.sh` script:

```bash
# Run all Azure Backup test cases
./scripts/sap_automation_qa.sh --test_groups=BACKUP_DB_HANA

# Run specific test cases
./scripts/sap_automation_qa.sh --test_groups=BACKUP_DB_HANA --test_cases=[backup-setup-verification]
./scripts/sap_automation_qa.sh --test_groups=BACKUP_DB_HANA --test_cases=[restore-to-db,restore-to-filesystem]
./scripts/sap_automation_qa.sh --test_groups=BACKUP_DB_HANA --test_cases=[restore-cross-vm]

# Run with verbose output
./scripts/sap_automation_qa.sh --test_groups=BACKUP_DB_HANA -vv
```

### Via SAP QA Service API

```bash
# Create a job through the API
./scripts/sap_automation_qa.sh job create --workspace DEV-WEEU-SAP01-X00 --test-group AzureBackupDatabase
```

## Viewing Test Results

Test results are generated the same way as HA tests. Navigate to your workspace directory:

```bash
cd WORKSPACES/SYSTEM/<SYSTEM_CONFIG_NAME>/quality_assurance/
```

The HTML report summarises each test case with PASS/FAIL/SKIPPED status. For details on the report format, see [High Availability — Viewing Test Results](./HIGH_AVAILABILITY.md#viewing-test-results).
