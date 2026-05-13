## Evidence Collectors Available

STAF provides these evidence collectors, each with built-in command sanitization and OS-family dispatch.

### CommandCollector

Executes shell commands with security guardrails:

- **Input validation:** User field must match `^[a-zA-Z0-9_-]+$`
- **Command sanitization:** Blocked patterns include `sudo rm`, `rm -rf` (full `DANGEROUS_COMMANDS` blocklist)
- **Max command length:** 3000 characters
- **Context substitution:** `{{ CONTEXT.key }}` replaced with workspace context values
- **User switching:** Non-root commands wrapped with `su - {user} -c {command}`

### AzureDataParser

Collects Azure resource metadata:

- Managed disk types, IOPS, throughput
- ANF volume details (service level, capacity, throughput limits)
- AFS share configuration
- LVM volume group and stripe information

### FileSystemCollector

Gathers filesystem topology and performance data:

- Mount points (`findmnt`), disk free (`df`)
- LVM layout (volume groups, logical volumes, stripe sizes)
- NFS backend detection (ANF vs AFS) with IP matching
- Azure disk throughput limits from IMDS metadata
- Output per filesystem: `target`, `source`, `fstype`, `size`, `free`, `max_mbps`, `max_iops`, `nfs_type`, `service_level`

### Cluster Status Module (`get_cluster_status_db` / `get_cluster_status_scs`)

Automated multi-step cluster validation:

1. Check stonith-action value
2. Retry loop (up to 25 attempts) for cluster readiness
3. Parse `crm_mon --output-as=xml` output
4. Validate: Pacemaker active, nodes configured ≥ 2, all nodes online
5. Process node attributes (topology-dependent)
6. Return: `primary_node`, `secondary_node` (scale-up) or `primary_site_nodes[]`, `secondary_site_nodes[]`, `majority_maker_node` (scale-out)

### Pacemaker Property Validator (`get_pcmk_properties_db` / `get_pcmk_properties_scs`)

Validates CIB XML against expected configuration using a priority-based lookup:

```
Lookup order:
  1. Fencing-mechanism-specific overrides (ISCSI → have-watchdog: true)
  2. Provider+topology overrides (SAPHanaSR-angi scale-out → migration-threshold: 50)
  3. OS-family overrides (RHEL → priority-fencing-delay: 15s)
  4. Category defaults (crm_config, rsc_defaults, op_defaults)
```

Returns per-property: `category`, `id`, `name`, `actual_value`, `expected_value`, `status` (PASS/FAIL), `required`.

### Azure Load Balancer Validator (`get_azure_lb`)

Authenticates via Managed Identity (MSI) and validates:

- Frontend IP matches expected SAP virtual IP
- Load balancing rules: idle timeout, distribution, floating IP
- Health probes: interval, probe count, port configuration
- Returns structured comparison: expected vs actual per parameter

### Log Parser (`log_parser`)

Parses `/var/log/messages` with time-range filtering and keyword matching:

- 40 curated keywords across Pacemaker, SAP, and system categories
- OS-aware timestamp parsing (RHEL `%b %d %H:%M:%S`, SUSE ISO 8601)
- Excludes noise keywords (`setroubleshoot`)
- Returns matched log lines with timestamps for timeline reconstruction

---

## Correlation with Azure

STAF evidence covers the cluster-internal view. Always cross-reference with Azure platform data to identify external causes.

### Correlation Matrix

| STAF Finding | Azure Data Source | What to Check |
|-------------|-------------------|---------------|
| Node went offline | **Activity Log** | `Microsoft.Compute/virtualMachines` restart/redeploy operations |
| Fencing fired | **Activity Log** | `fence_azure_arm` stop/start VM actions |
| Corosync ring error | **Network Watcher** | NSG flow logs for blocked UDP 5405 traffic |
| LB health probe down | **Load Balancer metrics** | `HealthProbeStatus` per backend instance |
| Storage timeout | **ANF/Disk metrics** | Read/write latency, IOPS consumption vs limit |
| HANA SWAIT persistent | **VM metrics** | Network throughput (log shipping bottleneck) |
| Scheduled maintenance | **IMDS Scheduled Events** | `http://169.254.169.254/metadata/scheduledevents?api-version=2020-07-01` |
| Split brain suspected | **Resource Graph** | Both VMs running, check proximity placement / availability set |

### Azure Monitor Alert Signals to Check

```kusto
// VMs in SAP resource group with availability drops
AzureMetrics
| where ResourceProvider == "MICROSOFT.COMPUTE"
| where MetricName == "VmAvailabilityMetric"
| where Average < 1
| where TimeGenerated > ago(1h)

// Load Balancer health probe failures
AzureMetrics
| where ResourceProvider == "MICROSOFT.NETWORK"
| where MetricName == "DipAvailability"
| where Average < 100
| where TimeGenerated > ago(1h)
```

### Azure Resource Graph Queries

```kusto
// Current power state of SAP cluster VMs
resources
| where type == "microsoft.compute/virtualmachines"
| where resourceGroup =~ "<rg_name>"
| extend powerState = tostring(properties.extended.instanceView.powerState.displayStatus)
| project name, powerState, location

// Proximity placement groups (split brain risk if missing)
resources
| where type == "microsoft.compute/proximityplacementgroups"
| where resourceGroup =~ "<rg_name>"
| extend vmCount = array_length(properties.virtualMachines)
| project name, vmCount
```

---

## Quick Reference: STAF Test Scenario IDs

When the triage reveals a specific failure mode, these STAF test scenarios can validate the fix or reproduce the issue in a controlled way.

### HANA Database HA (15 scenarios)

| Scenario | File | What It Tests |
|----------|------|--------------|
| HA Config Validation | `ha-config.yml` | Full CRM property check against rules |
| HA Config Offline | `ha-config-offline.yml` | CRM validation without live cluster changes |
| Azure LB Validation | `azure-lb.yml` | Load balancer frontend, rules, probes |
| Resource Migration | `resource-migration.yml` | Controlled HANA primary migration |
| Primary Node Crash | `primary-node-crash.yml` | `echo b > /proc/sysrq-trigger` on primary |
| Primary Node Kill | `primary-node-kill.yml` | Hard VM stop of primary |
| Primary Indexserver Crash | `primary-crash-index.yml` | Kill HANA indexserver on primary |
| Primary Echo-B | `primary-echo-b.yml` | SysRq crash on primary |
| Secondary Node Kill | `secondary-node-kill.yml` | Hard VM stop of secondary |
| Secondary Indexserver Crash | `secondary-crash-index.yml` | Kill HANA indexserver on secondary |
| Secondary Echo-B | `secondary-echo-b.yml` | SysRq crash on secondary |
| Network Isolation | `block-network.yml` | iptables block between cluster nodes |
| HANA-Shared Block | `block-hana-shared.yml` | Block access to /hana/shared |
| Filesystem Freeze (ANF) | `fs-freeze.yml` | Freeze ANF filesystem to simulate throttle |
| SBD Fencing | `sbd-fencing.yml` | Kill SBD inquisitor to trigger watchdog |

### SCS/ERS HA (14 scenarios)

| Scenario | File | What It Tests |
|----------|------|--------------|
| HA Config Validation | `ha-config.yml` | SCS CRM property check |
| HA Config Offline | `ha-config-offline.yml` | SCS offline CRM validation |
| Azure LB Validation | `azure-lb.yml` | SCS/ERS Load Balancer check |
| SAP Control Config | `sapcontrol-config.yml` | SAP instance control validation |
| ASCS Migration | `ascs-migration.yml` | Controlled ASCS resource migration |
| ASCS Node Crash | `ascs-node-crash.yml` | Crash the node hosting ASCS |
| Kill Message Server | `kill-message-server.yml` | Kill SAP message server process |
| Kill Enqueue Server | `kill-enqueue-server.yml` | Kill enqueue server process |
| Kill Enqueue Replication | `kill-enqueue-replication.yml` | Kill ERS replication process |
| Kill SAPStartSrv | `kill-sapstartsrv-process.yml` | Kill sapstartsrv process |
| Manual Restart | `manual-restart.yml` | Stop and start SAP instances manually |
| Failover to Node | `ha-failover-to-node.yml` | Force failover to specific node |
| Network Isolation | `block-network.yml` | Network partition between SCS nodes |

---

## Decision Flowchart

When the triage does not match a known pattern, use this decision tree:

```
Is Pacemaker running?
├─ NO → Check systemd: systemctl status pacemaker
│       Check if node was fenced or rebooted (Activity Log)
│       Check SBD/watchdog: was the node self-fenced?
│
└─ YES → Is the cluster quorate?
         ├─ NO → Corosync ring failure → check corosync-cfgtool -s
         │       NSG blocking UDP 5405? → Network Watcher flow logs
         │       Node count below quorum? → check expected_votes vs total_votes
         │
         └─ YES → Are resources in expected state?
                  ├─ NO → Is maintenance-mode true?
                  │       ├─ YES → Someone left maintenance on. Disable and re-check.
                  │       └─ NO → Check resource failcount:
                  │               crm_resource --resource <rsc> --get-parameter failcount
                  │               If failcount >= migration-threshold → resource banned
                  │               Clear with: crm resource cleanup <rsc>
                  │
                  └─ YES → Is replication in sync (SOK)?
                           ├─ NO → SFAIL: Check HANA trace, network, disk I/O
                           │       SWAIT: Check log shipping progress, ANF throughput
                           │       UNKNOWN: Check SAPHanaSR hook in global.ini
                           │
                           └─ YES → Cluster is healthy.
                                    If user reports issues, check application layer
                                    (SAP work processes, ABAP dumps, RFC connections).
```
