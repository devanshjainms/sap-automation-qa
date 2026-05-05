# Skill: SAP Cluster Triage

**Description:** Triage SAP HANA and SAP Central Services (SCS/ERS) Pacemaker clusters running on Azure. Combines STAF MCP evidence collectors with Azure platform telemetry to identify root cause of cluster failures, split-brain events, fencing issues, and replication breakdowns.

**When to use:** Activate when an incident involves:

- SAP HANA System Replication (HSR) failure or takeover
- SCS/ERS failover or enqueue replication loss
- Pacemaker resource failures, fencing events, or maintenance-mode drift
- Azure VM unavailability, load balancer health probe failures, or storage throttling affecting SAP clusters
- Any alert from Azure Monitor, SAP HANA Studio, or Pacemaker that indicates cluster instability

---

## Procedure

Follow this workflow top-to-bottom. Each step produces evidence that feeds the next.

### Step 1 — Establish Context

Collect the system identity and topology before examining cluster state.

| Question | How to Answer |
|----------|---------------|
| Which SAP SID? | Workspace `sap-parameters.yaml` → `sap_sid`, `db_sid` |
| HANA topology? | `scale_up` (2-node HSR), `scale_out_hsr` (multi-node HSR), `scale_out_standby` (standby nodes, no Pacemaker) |
| SR provider? | `SAPHanaSR` (classic), `SAPHanaSR-angi` (next-gen), `SAPHanaController` (scale-out) |
| Fencing mechanism? | `ISCSI` (SBD), `AFA` (Azure Fence Agent), `ASD` (Azure Storage Disk) |
| OS family? | SUSE → `crm` commands; RHEL → `pcs` commands |
| Storage backend? | Premium/UltraSSD disks, ANF (Azure NetApp Files), AFS (Azure File Share), LVM |
| Component? | `DB` (HANA), `SCS` (Central Services + ERS) |

### Step 2 — Collect Cluster State

Run evidence collectors in this order. Each collector is available through STAF as a command or module.

#### 2a. Pacemaker Status

```bash
# OS-agnostic — works on both SUSE and RHEL
crm_mon --output-as=xml          # Full cluster state as XML
crm_mon -1rR                     # Human-readable cluster status with inactive resources
systemctl is-active pacemaker    # Confirm Pacemaker daemon is running
```

Parse the XML output for:

- `nodes_configured` — must be ≥ 2
- All nodes `online="true"` — any offline node is a red flag
- Resource states: `Started`, `Stopped`, `Failed`, `Blocked`, `Unmanaged`
- Pending operations and transition errors

#### 2b. CIB Configuration

```bash
cibadmin --query                           # Full CIB XML
cibadmin --query --scope constraints       # Location, colocation, order constraints
cibadmin --query --scope resources         # Resource definitions
cibadmin --query --scope crm_config        # Cluster properties
```

#### 2c. Node Attributes

```bash
# SUSE
crm_attribute --type crm_config --name priority-fencing-delay --quiet
crm_attribute --type crm_config --name maintenance-mode --query
crm configure get_property stonith-action

# RHEL
pcs property config stonith-action
pcs property config priority-fencing-delay
```

For HANA, also query SAPHanaSR node attributes:

```bash
# Scale-up: look for hana_<sid>_sync_state, hana_<sid>_op_mode, hana_<sid>_roles
# These are populated by the SAPHanaSR/SAPHanaSR-angi hook in global.ini
crm_mon --output-as=xml   # Node attributes are embedded in the XML
```

#### 2d. Corosync Health

```bash
corosync-cfgtool -s     # Ring status — all rings must show no errors
corosync-quorumtool     # Quorum status — cluster must be quorate
```

#### 2e. SBD Status (ISCSI/ASD fencing only)

```bash
sbd -d <device> list              # List SBD slots
sbd -d <device> dump              # Dump SBD header
systemctl is-active sbd           # SBD daemon status
```

#### 2f. HANA Nameserver and Replication

```bash
# As <sid>adm user
hdbnsutil -sr_state               # Replication state: SOK, SFAIL, SWAIT, UNKNOWN
hdbnsutil -sr_stateConfiguration  # Detailed replication configuration
HDBSettings.sh landscapeHostConfiguration.py --sapcontrol=1   # Nameserver landscape
```

#### 2g. System Logs

STAF's log parser searches `/var/log/messages` using 40 curated keywords across three categories:

**Pacemaker keywords (22):** `LogAction`, `LogNodeActions`, `pacemaker-fenced`, `check_migration_threshold`, `corosync`, `Result of`, `reboot`, `cannot run anywhere`, `attrd_peer_update`, `High CPU load detected`, `cli-ban`, `cli-prefer`, `cib-bootstrap-options-maintenance-mode`, `-is-managed`, `-maintenance`, `-standby`, `sbd`, `pacemaker-controld`, `pacemaker-execd`, `pacemaker-based`, `pacemaker-attrd`

**SAP/Resource keywords (17):** `SAPHana`, `SAPHanaController`, `SAPHanaTopology`, `SAPInstance`, `fence_azure_arm`, `rsc_st_azure`, `rsc_ip_`, `rsc_nc_`, `rsc_Db2_`, `rsc_HANA_`, `corosync`, `Result of`, `reboot`

**Exclude:** `setroubleshoot` (noise)

Filter by time range around the incident. Log timestamp formats differ by OS:

- **RHEL:** `%b %d %H:%M:%S` (e.g., `Jan 01 12:34:56`)
- **SUSE:** ISO 8601 with microseconds

### Step 3 — Validate Configuration Against Rules

Apply the analysis rules from the next section to every collected property. Flag any deviation as a finding.

### Step 4 — Correlate with Azure Platform

Combine STAF cluster evidence with Azure-side data:

| Azure Source | What to Check |
|-------------|---------------|
| **Activity Log** | VM restart/redeploy events, planned maintenance, allocation failures |
| **Azure Monitor Metrics** | VM availability, CPU/memory pressure, disk IOPS and throughput |
| **Resource Graph** | Current VM power state, proximity placement groups, availability zones |
| **Load Balancer metrics** | Health probe status (up/down per backend), SNAT exhaustion |
| **Azure NetApp Files metrics** | Volume IOPS, throughput, latency — compare against tier limits |
| **Network Watcher** | NSG flow logs, effective routes — needed for network isolation analysis |
| **Scheduled Events** | `http://169.254.169.254/metadata/scheduledevents` — freeze/reboot/redeploy |

### Step 5 — Determine Root Cause

Match the collected evidence to a known failure pattern (see Common Failure Patterns below). If no exact match, synthesize from the evidence categories:

1. Was the cluster quorate throughout the incident?
2. Did fencing fire? If not, why not (STONITH disabled, timeout, SBD unresponsive)?
3. What was the replication state before, during, and after?
4. Did Azure platform events coincide with the cluster event?
5. Were resources migrated or banned manually (`cli-ban`, `cli-prefer` in logs)?

---

## Evidence Categories

Each piece of evidence falls into one of these categories. Collect at least one item from every category before concluding.

| Category | Evidence | Why It Matters |
|----------|----------|----------------|
| **Cluster Topology** | Node count, online/offline state, quorum | Split brain requires quorum loss |
| **Resource State** | Started/Stopped/Failed per resource | Shows what moved and what didn't |
| **CRM Properties** | stonith-enabled, maintenance-mode, timeouts | Misconfigured properties prevent recovery |
| **Fencing** | stonith-action, fence agent config, SBD status | Fencing is the last line of defense |
| **Replication** | SR state (SOK/SFAIL/SWAIT), op_mode, roles | Determines data consistency |
| **Constraints** | Location, colocation, order constraints | May pin resources incorrectly |
| **Node Attributes** | SAPHanaSR attributes, health scores | Hook-populated; stale values indicate hook failure |
| **Corosync** | Ring errors, quorum votes | Transport layer health |
| **System Logs** | Pacemaker transitions, fencing events | Timeline reconstruction |
| **Azure Platform** | VM events, LB probes, storage metrics | External causes invisible to the cluster |

---

## Analysis Rules

The following rules cover the critical properties, expected values, and validation logic STAF enforces. Properties are grouped by scope.

### Cluster Properties (crm_config)

| Property | Expected Value | Required | Notes |
|----------|---------------|----------|-------|
| `stonith-enabled` | `true` | No | **Must be true in production.** False disables all fencing. |
| `stonith-action` | `reboot` | No | Accepted: `reboot`, `poweroff`, `off`. `reboot` is standard. |
| `stonith-timeout` | `210s` (ISCSI/ASD), `900s` (AFA) | No | Too low → fencing times out; too high → long recovery. |
| `maintenance-mode` | `false` | No | `true` disables all recovery. Check if accidentally left on after maintenance. |
| `concurrent-fencing` | `true` | No | Required for multi-node clusters with parallel fencing. |
| `priority-fencing-delay` | `30s` (SUSE), `15s` (RHEL) | Yes | Delays fencing on the non-primary node to give primary time to self-fence. |
| `node-health-strategy` | `custom` | No | Enables Azure health integration via `#health-azure` attribute. |
| `cluster-infrastructure` | `corosync` | No | Should always be `corosync` on Azure. |
| `have-watchdog` | `true` (ISCSI/ASD), `false` (AFA) | No | Must match fencing mechanism. |

### Operation Defaults

| Property | Expected Value |
|----------|---------------|
| `record-pending` | `true` |
| `timeout` | `600s` |

### Resource Defaults (DB vs SCS)

| Property | HANA DB | SCS |
|----------|---------|-----|
| `migration-threshold` | `5000` | `3` |
| `resource-stickiness` | `1000` | `1` |
| `priority` | `1` | `1` |

> **Why the difference:** HANA resources are extremely expensive to migrate (full data copy risk), so the threshold is set high to avoid unnecessary failovers. SCS resources are lightweight and can move quickly.

### HANA Resource Properties

| Property | Expected | Notes |
|----------|----------|-------|
| `PREFER_SITE_TAKEOVER` | `true` | Auto-takeover on primary failure. `false` means manual intervention. |
| `AUTOMATED_REGISTER` | `true` | Auto-register former primary as secondary after takeover. `false` requires manual `hdbnsutil -sr_register`. |
| `DUPLICATE_PRIMARY_TIMEOUT` | `7200` | Seconds to wait before fencing a detected duplicate primary. |
| `clone-max` | `2` (scale-up) | Maximum clone instances. Matches node count. |
| `clone-node-max` | `1` | Only one HANA instance per node. |
| `notify` | `true` | Required for SAPHanaSR hook notifications. |
| `interleave` | `true` | Allows parallel clone operations. |
| `priority` | `100` | Required. Controls resource start/stop ordering. |

### HANA Operation Timeouts

| Operation | Timeout (Scale-Up) | Timeout (Scale-Out) |
|-----------|--------------------|--------------------|
| `start` | `3600s` | `3600s` |
| `stop` | `3600s` | `3600s` |
| `promote` | `3600s` | `900s` |
| `demote` | `3600s` | `320s` |
| `monitor` | `700s` | `700s` |

### SCS/ASCS Resource Properties

| Property | Expected | Notes |
|----------|----------|-------|
| `AUTOMATIC_RECOVER` | `false` | ASCS should not auto-recover — let Pacemaker handle failover. |
| `MINIMAL_PROBE` | `true` (ASCS), `false` (ERS) | Reduces unnecessary probing on ASCS. |
| `resource-stickiness` | `5000` | ASCS is sticky to prefer staying on the current node. |
| `priority` | `100` | Required. |

### SCS Operation Timeouts

| Operation | Timeout (ANF) | Timeout (AFS) |
|-----------|--------------|--------------|
| `monitor` (interval `11s`) | `105s` | `60s` |
| `start` | `180s` | `180s` |
| `stop` | `240s` | `240s` |
| `promote` | `320s` | `320s` |
| `demote` | `300s` | `300s` |

### Colocation Constraints

| Component | Score | Role |
|-----------|-------|------|
| HANA DB | `4000` | `Master` / `Promoted` |
| SCS | `-5000` | `Started` |

### Azure Fence Agent Properties (AFA)

| Property | Expected |
|----------|----------|
| `pcmk_delay_max` | `15s` |
| `pcmk_monitor_retries` | `4` |
| `pcmk_action_limit` | `3` |
| `pcmk_reboot_timeout` | `900s` |
| `power_timeout` | `240s` |

### SBD STONITH Properties (ISCSI/ASD)

| Property | Expected |
|----------|----------|
| `monitor interval` | `600s` |
| `monitor timeout` | `15s` |

### Azure Load Balancer Health Probes

Validate for each LB fronting SAP resources:

- `idle_timeout_in_minutes` — must match expected value
- `load_distribution` — typically `Default` (5-tuple hash)
- `enable_floating_ip` — `true` (required for SAP virtual IPs)
- Probe `interval_in_seconds` and `number_of_probes` — affects failover detection speed

### SAPHanaSR Provider Paths

Verify the correct hook is installed and referenced in HANA `global.ini`:

| Provider | SUSE Path | RHEL Path |
|----------|-----------|-----------|
| `SAPHanaSR` | `/usr/share/SAPHanaSR` | `/usr/share/SAPHanaSR/srHook` |
| `SAPHanaSR-angi` | `/usr/share/SAPHanaSR-angi` | `/usr/share/SAPHanaSR-angi/srHook` |
| `SAPHanaController` | `/usr/share/SAPHanaSR-ScaleOut` | `/usr/share/SAPHanaSR-ScaleOut/srHook` |

### HANA System Replication States

| State | Meaning | Action |
|-------|---------|--------|
| `SOK` | Replication in sync | Normal. No action needed. |
| `SFAIL` | Replication broken | **Investigate immediately.** Check network, disk, HANA trace files. |
| `SWAIT` | Replication initializing / catching up | Monitor progress. If stuck, check log shipping. |
| `UNKNOWN` | State cannot be determined | Hook may have failed. Check `global.ini` hook config and SAPHanaSR attribute in CIB. |

---

## Common Failure Patterns

### Pattern 1: HSR Sync Failure After Takeover

**Symptoms:**

- Takeover completed but former primary cannot register as secondary
- `hdbnsutil -sr_state` shows `SFAIL` or registration error
- Pacemaker shows resource in `Failed` or `Stopped` state on one node

**Root Causes:**

1. **`AUTOMATED_REGISTER` is `false`** — manual `hdbnsutil -sr_register` required
2. **Network partition healed** — former primary came back as a second primary (duplicate primary)
3. **Data divergence** — log positions incompatible; HANA refuses to register
4. **`DUPLICATE_PRIMARY_TIMEOUT` too short** — secondary was fenced before old primary surrendered

**Investigation:**

```
1. Check AUTOMATED_REGISTER:
   crm_resource --resource <SAPHana_rsc> --get-parameter=AUTOMATED_REGISTER

2. Check for duplicate primary in logs:
   grep "DUPLICATE_PRIMARY" /var/log/messages

3. Verify replication state on both nodes:
   su - <sid>adm -c "hdbnsutil -sr_state"

4. Check if HANA trace shows registration errors:
   grep -i "sr_register\|replication" /usr/sap/<SID>/HDB<inst>/trace/nameserver_*.trc
```

### Pattern 2: Fencing Not Triggered During Node Failure

**Symptoms:**

- Node became unresponsive but was never fenced
- Resources stuck in `Started` state on the dead node
- No `pacemaker-fenced` entries in logs

**Root Causes:**

1. **`stonith-enabled` is `false`** — fencing entirely disabled
2. **`maintenance-mode` is `true`** — all automated actions suspended
3. **SBD device unreachable** — if ISCSI, check iSCSI target connectivity
4. **Azure Fence Agent auth failure** — MSI token expired or RBAC missing
5. **`stonith-timeout` too short** — fencing timed out before Azure completed the VM restart
6. **`have-watchdog` mismatch** — set to `true` without SBD, or `false` with SBD

**Investigation:**

```
1. Verify STONITH is enabled:
   cibadmin --query --scope crm_config | grep stonith-enabled

2. Check maintenance mode:
   crm_attribute --type crm_config --name maintenance-mode --query

3. Test fence agent manually:
   fence_azure_arm --action=status --plug=<vm_name> --resourceGroup=<rg> \
     --subscriptionId=<sub> --msi

4. For SBD, verify device health:
   sbd -d /dev/disk/by-id/<device> list
```

### Pattern 3: ANF Volume Throttling During Backup

**Symptoms:**

- HANA backup or log shipping slows dramatically
- `SWAIT` replication state persists for hours
- ANF metrics show throughput at tier ceiling

**Root Causes:**

1. **Service level mismatch** — Standard tier (16 MiB/s per TiB) insufficient for backup throughput
2. **Volume size too small** — ANF throughput scales with volume capacity
3. **Concurrent workload** — production queries compete with backup I/O

**Investigation:**

```
1. Get filesystem details (STAF FileSystemCollector):
   - NFS type: ANF vs AFS
   - Service level: Standard / Premium / Ultra
   - max_mbps and max_iops from Azure metadata

2. Check Azure Monitor:
   - ANF volume throughput (read + write) over incident window
   - Compare against tier limits

3. Verify mountpoint options:
   findmnt -t nfs,nfs4    # Check mount options (nconnect, rsize, wsize)
```

### Pattern 4: Enqueue Replication Server Failover Failure (ENSA2)

**Symptoms:**

- ASCS migrated but enqueue locks were lost
- ERS did not replicate lock table before failover
- SAP application servers report `EnqueueException`

**Root Causes:**

1. **ERS not running** — resource was in `Stopped` or `Failed` state before the ASCS failure
2. **`AUTOMATIC_RECOVER` set to `true`** — ASCS restarted locally before Pacemaker could migrate it, losing the enqueue table
3. **Monitor timeout too short** — Pacemaker declared resource dead before SAP finished graceful shutdown
4. **Colocation constraint incorrect** — ASCS and ERS placed on the same node

**Investigation:**

```
1. Check ASCS/ERS resource state before incident:
   crm_mon -1rR | grep -E "ASCS|ERS"

2. Verify AUTOMATIC_RECOVER:
   cibadmin --query --scope resources | grep AUTOMATIC_RECOVER
   Expected: false

3. Check colocation constraint:
   cibadmin --query --scope constraints | grep rsc_colocation
   Score should be -5000 (anti-colocation)

4. Verify ERS MINIMAL_PROBE:
   Expected: false (ERS needs full monitoring)
```

### Pattern 5: Network Isolation Causes Split Brain

**Symptoms:**

- Both nodes believe they are primary
- Pacemaker logs show `cannot run anywhere` or quorum loss
- Corosync ring errors visible in `corosync-cfgtool -s`

**Root Causes:**

1. **Corosync ring failure** — single ring with no redundancy
2. **NSG rule change** — Azure NSG blocking Corosync UDP ports (5405)
3. **Azure accelerated networking driver issue** — transient network stack failure
4. **`concurrent-fencing` is `false`** — only one fence operation at a time, delaying resolution
5. **`priority-fencing-delay` not set** — both nodes race to fence each other

**Investigation:**

```
1. Check corosync ring status:
   corosync-cfgtool -s
   Look for: "ring 0 active with no faults"

2. Check quorum state:
   corosync-quorumtool
   Expected: "Quorate: Yes" or explicit two_node quorum

3. Review Azure NSG rules:
   az network nsg rule list --nsg-name <nsg> -g <rg> -o table
   Port 5405/UDP must be allowed between cluster nodes

4. Check priority-fencing-delay:
   crm_attribute --type crm_config --name priority-fencing-delay --quiet
   Expected: 30s (SUSE) or 15s (RHEL)

5. Review Azure Activity Log for network events:
   az monitor activity-log list --resource-group <rg> \
     --start-time <incident_time> --offset 1h
```

---

## SAP Topologies

### Scale-Up (2-Node HSR)

The standard topology: two VMs, each running one HANA instance, connected by synchronous system replication.

- **Nodes:** Primary + Secondary
- **Resource agent:** `SAPHana` (clone with `Master`/`Slave` or `Promoted`/`Unpromoted`)
- **Fencing:** SBD (ISCSI) or Azure Fence Agent (AFA)
- **Key attributes:** `hana_<sid>_sync_state`, `hana_<sid>_roles`, `hana_<sid>_op_mode`
- **Validation focus:** `AUTOMATED_REGISTER`, `PREFER_SITE_TAKEOVER`, `DUPLICATE_PRIMARY_TIMEOUT`
- **Post-takeover:** Former primary must register as secondary. Verify `SOK` replication.

### Scale-Out HSR (Multi-Node)

Multiple worker nodes per site, system replication between sites, with an optional majority maker.

- **Nodes:** Primary site workers + Secondary site workers + Majority maker (odd-count tiebreaker)
- **Resource agent:** `SAPHanaController` (scale-out variant)
- **Provider path:** `/usr/share/SAPHanaSR-ScaleOut/`
- **Key differences from scale-up:**
  - `promote` timeout is `900s` (not `3600s`)
  - `migration-threshold` may be `50` for `SAPHanaSR-angi` scale-out
  - Post-takeover validation checks `primary_node in cluster_status_pre.secondary_site_nodes`
- **Validation focus:** Majority maker quorum role, inter-site replication, worker node distribution

### Scale-Out Standby

Multiple worker nodes with standby hosts for local HA. **No Pacemaker cluster** — standby failover is handled by HANA internally.

- **Nodes:** Active workers + Standby workers
- **No CRM validation** — Pacemaker is not used
- **Validation focus:** HANA host auto-failover configuration, standby readiness, nameserver landscape

---

## OS Family Differences

Commands differ between SUSE and RHEL. STAF dispatches automatically based on `ansible_os_family`.

### Cluster Management

| Action | SUSE | RHEL |
|--------|------|------|
| Get stonith-action | `crm configure get_property stonith-action` | `pcs property config stonith-action` |
| Clear resource | `crm resource clear {rsc}` | `pcs resource clear {rsc}` |
| Set maintenance mode | `crm configure property maintenance-mode=true` | `pcs property set maintenance-mode=true` |
| Put node standby | `crm node standby {node}` | `pcs node standby {node}` |
| Show constraints | `crm configure show` | `pcs constraint list --full` |
| Resource cleanup | `crm resource cleanup {rsc}` | `pcs resource cleanup {rsc}` |

### Shared Commands (OS-agnostic)

These work identically on both SUSE and RHEL:

```bash
crm_mon --output-as=xml                    # Cluster status XML
crm_mon -1rR                               # Cluster status text
cibadmin --query                           # Full CIB
cibadmin --query --scope constraints       # Constraints
cibadmin --query --scope crm_config        # Cluster properties
crm_attribute --type crm_config --name <property> --quiet
systemctl is-active pacemaker
corosync-cfgtool -s
corosync-quorumtool
```

### OS Tuning Parameters

| OS | Tuning Tool |
|----|-------------|
| SUSE | `saptune`, `sapconf`, `tuned` |
| RHEL | `tuned` only |

---

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
