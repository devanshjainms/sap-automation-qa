# backup_db_hana

Azure Backup functional testing for SAP HANA database restoration.

## Scenarios

| Task File | Description |
|-----------|-------------|
| backup-setup-verification.yml | Verify Azure Backup configuration |
| restore-to-db.yml | Restore backup to database |
| restore-to-filesystem.yml | Restore backup to filesystem |
| restore-cross-vm.yml | Cross-VM restore test |
| encryption-check.yml | Backup encryption validation |
| encryption-cleanup.yml | Encryption cleanup |
| encryption-key-transfer.yml | Encryption key transfer |
| recover-db-commands.yml | Database recovery commands |
| rescue-backup.yml | Backup test error handling |
| post-validations-backup.yml | Post-restore validations |

## Requirements

- Azure Backup configured for SAP HANA
- Azure Managed Identity with Recovery Services permissions
