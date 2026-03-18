# ha_db_hana

HANA Database High Availability functional testing for Pacemaker clusters on Azure.

## Scenarios

| Task File | Description |
|-----------|-------------|
| ha-config.yml | HA configuration validation |
| ha-config-offline.yml | Offline HA configuration validation |
| azure-lb.yml | Azure Load Balancer validation |
| resource-migration.yml | Resource migration test |
| primary-node-crash.yml | Primary node crash test |
| primary-node-kill.yml | Primary node kill test |
| primary-crash-index.yml | Primary indexserver crash test |
| primary-echo-b.yml | Primary echo-b test |
| secondary-node-kill.yml | Secondary node kill test |
| secondary-crash-index.yml | Secondary indexserver crash test |
| secondary-echo-b.yml | Secondary echo-b test |
| block-network.yml | Network isolation test |
| block-hana-shared.yml | HANA shared storage isolation test |
| fs-freeze.yml | ANF filesystem freeze test |
| sbd-fencing.yml | SBD fencing test |

## Supported Topologies

- Scale-Up (classic two-node HSR)
- Scale-Out HSR (multi-node with system replication)
- Scale-Out Standby (multi-node with standby nodes)

## Requirements

- SAP HANA with System Replication configured
- Pacemaker cluster (SUSE or RHEL)
- Azure Managed Identity with appropriate permissions
