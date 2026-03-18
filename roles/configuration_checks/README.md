# configuration_checks

Configuration validation for SAP workloads on Azure — validates HANA, Db2, SCS, and application instance configurations.

## Tasks

| Task File | Description |
|-----------|-------------|
| main.yml | Entry point — runs configuration checks via ThreadPoolExecutor |
| ha_modules.yml | HA-specific Pacemaker and Load Balancer validation |
| disks.yml | Disk and filesystem configuration checks |
| build-telemetry-batch.yml | Build telemetry batch from check results |
| build-telemetry-entry.yml | Build individual telemetry entry |

## Requirements

- Azure Managed Identity with compute/network read access
- Access to instance metadata service (IMDS)
