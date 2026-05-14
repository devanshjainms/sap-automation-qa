---
name: sap-cluster-triage
description: >
  Triage SAP HANA and SCS/ERS Pacemaker clusters on Azure. Collects SSH evidence,
  queries the SAP knowledge base, and provides context for root cause analysis of
  cluster failures, fencing issues, and replication breakdowns. Triggered by
  "triage cluster", "cluster failure", "hana replication broken", "pacemaker issue",
  "fencing not triggered", "scs failover", or "cluster split brain".
compatibility: "Requires STAF MCP server connection. Target SAP systems must be reachable via SSH."
allowed-tools: shell
tools:
  - collect_evidence
  - get_analysis_context
  - get_evidence_output
  - run_evidence_collector
  - list_evidence_catalog
  - search_logs
  - query_knowledge
  - list_workspaces
  - get_workspace
  - RunAzCliReadCommands
  - GetAzCliHelp
---

# SAP Cluster Triage

Triage SAP HANA and SAP Central Services (SCS/ERS) Pacemaker clusters running on Azure.
Combines STAF MCP evidence collectors with Azure platform telemetry to identify root cause
of cluster failures, split-brain events, fencing issues, and replication breakdowns.

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

Do **not** hardcode expected property values in this skill. Instead, use the
`query_knowledge` MCP tool to retrieve applicable rules from the STAF knowledge
base. Rules are maintained in JSONL files under `src/core/knowledge/seed/rules/`
and cover:

- **Cluster properties** (`ha_db_cluster.jsonl`, `ha_scs_cluster.jsonl`) —
  `stonith-enabled`, `maintenance-mode`, `concurrent-fencing`, timeouts,
  resource defaults, colocation constraints, fence agent properties.
- **HANA configuration** (`hana.jsonl`) — system replication parameters,
  indexserver settings, provider paths.
- **Network and storage** (`network.jsonl`, `virtual_machine.jsonl`) —
  load balancer probes, accelerated networking, disk layout.
- **SAP application** (`sap.jsonl`, `app.jsonl`, `ascs.jsonl`) —
  sapcontrol settings, enqueue replication, instance profiles.
- **Package versions** (`package.jsonl`) — required cluster packages per OS.

To query rules for a specific system:

```
query_knowledge(query="HANA cluster stonith configuration")
```

The tool returns rules with severity, category, expected values, and tags —
use these to validate evidence rather than relying on static tables.

See [failure patterns](references/failure-patterns.md) when investigating specific failure scenarios.

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


---

## Additional Reference

- See [evidence collectors, Azure correlation, test scenarios, and decision flowchart](references/evidence-and-correlation.md) for detailed reference material.
