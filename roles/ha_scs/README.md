# ha_scs

SAP Central Services High Availability functional testing for Pacemaker clusters on Azure.

## Scenarios

| Task File | Description |
|-----------|-------------|
| ha-config.yml | HA configuration validation |
| ha-config-offline.yml | Offline HA configuration validation |
| azure-lb.yml | Azure Load Balancer validation |
| sapcontrol-config.yml | SAP control validation |
| ascs-migration.yml | ASCS migration test |
| ascs-node-crash.yml | ASCS node crash test |
| kill-message-server.yml | Kill message server test |
| kill-enqueue-server.yml | Kill enqueue server test |
| kill-enqueue-replication.yml | Kill enqueue replication test |
| kill-sapstartsrv-process.yml | Kill SAPStartSrv process test |
| manual-restart.yml | Manual restart test |
| ha-failover-to-node.yml | HA failover to node test |
| block-network.yml | Network isolation test |

## Requirements

- SAP Central Services (ASCS/ERS) with ENSA1 or ENSA2
- Pacemaker cluster (SUSE or RHEL)
- Azure Managed Identity with appropriate permissions
