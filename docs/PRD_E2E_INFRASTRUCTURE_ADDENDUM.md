# PRD Addendum: E2E Testing Infrastructure Specifications

> **Parent document**: [PRD: End-to-End Testing & Release Pipeline](./PRD_E2E_TESTING.md)
> **Version**: 1.0.0
> **Status**: Draft
> **Author**: Lambert (Ansible & Infrastructure Test Specialist)

This addendum provides detailed infrastructure specifications referenced from
the main PRD. It covers execution internals, Docker-to-SAP connectivity, cluster
recovery procedures, backup bootstrapping, offline validation fixtures, and
workspace/inventory management.

---

## Table of Contents

1. [Ansible Execution Model](#1-ansible-execution-model)
2. [Docker-to-SAP Connectivity](#2-docker-to-sap-connectivity)
3. [Cluster Recovery Specification](#3-cluster-recovery-specification)
4. [Backup Infrastructure Bootstrap](#4-backup-infrastructure-bootstrap)
5. [Offline Validation Fixture Specification](#5-offline-validation-fixture-specification)
6. [Workspace & Inventory Management](#6-workspace--inventory-management)

---

## 1. Ansible Execution Model

> **Cross-ref**: Main PRD §4 (Infrastructure Requirements), §5 Stage 5 (Live SAP
> System Tests), §7.5 (Timeout & Retry Policies)

### 1.1 subprocess.Popen — Not ansible-runner

STAF does **not** use `ansible-runner` for playbook execution. Instead,
`src/core/execution/executor.py` invokes `ansible-playbook` directly via
`subprocess.Popen`. This design was chosen for:

- **Direct signal control** — SIGTERM/SIGKILL escalation on stuck playbooks.
- **Output streaming** — Real-time log file writes without runner buffering.
- **Lean dependency surface** — No runner daemon or event directory overhead.

#### Two Execution Modes

| Mode | stdout | stderr | Timeout mechanism | Use case |
|------|--------|--------|-------------------|----------|
| **File-backed** | Redirected to log file handle | Merged via `STDOUT` | `proc.wait(timeout=3600)` | Production jobs via API |
| **In-memory** | `subprocess.PIPE` | `subprocess.PIPE` | `proc.communicate(timeout=3600)` | Ad-hoc CLI invocations |

**File-backed execution** (primary path):

```python
proc = subprocess.Popen(
    cmd,
    stdout=fh,                    # Direct file write, no buffering
    stderr=subprocess.STDOUT,     # Merge stderr into stdout stream
    text=True,
    env=merged_env,
)
```

**In-memory execution** (fallback):

```python
proc = subprocess.Popen(
    cmd,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
    env=env,
)
stdout, stderr = proc.communicate(timeout=3600)
# Returns last 5000 chars of stdout on success
# Returns last 2000 chars of stderr on failure
```

#### Process Registration

All running processes are tracked in a thread-safe dict (`self._processes`)
protected by `self._lock`. This enables:

- Cancellation by `job_id` from the API (`POST /api/v1/jobs/{id}/cancel`).
- Orphan detection on worker restart (crash recovery).
- Concurrent execution limit enforcement (one job per workspace).

### 1.2 ansible.cfg Requirements for E2E

The production `src/ansible.cfg` defines the baseline. E2E tests **must** use
this file unmodified to validate real execution behavior, with the following
settings being critical:

```ini
[defaults]
host_key_checking         = False           # Non-interactive SSH acceptance
interpreter_python        = auto_silent     # Auto-detect Python on targets
callbacks_enabled         = profile_tasks   # Task-level timing (P50/P95 data)
stdout_callback           = default         # Parseable output format
bin_ansible_callbacks     = True            # Load callbacks from cwd
error_on_undefined_vars   = True            # Fail-fast on missing vars
library                   = modules         # Custom module path (relative)
module_utils              = module_utils    # Custom utils path (relative)
allow_world_readable_tmpfiles = True        # Required for container execution

[callback_log_plays]
log_folder = /var/tmp/ansible/hosts
log_path   = /var/tmp/ansible/hosts

[connection]
ssh_args = -C -o ControlMaster=auto -o ControlPersist=60s \
           -o ServerAliveInterval=300 \
           -o ControlPath=/tmp/ansible-ssh-%h-%p-%r
```

#### E2E-Specific Overrides

For E2E test stability, the following **environment variable overrides** should
be applied (do NOT modify `ansible.cfg` — use `ANSIBLE_*` env vars):

| Variable | E2E Value | Rationale |
|----------|-----------|-----------|
| `ANSIBLE_TIMEOUT` | `30` | SSH connection timeout (seconds) |
| `ANSIBLE_FORKS` | `5` | Parallel host execution (match SAP node count) |
| `ANSIBLE_RETRY_FILES_ENABLED` | `False` | No `.retry` files cluttering workspace |
| `ANSIBLE_PIPELINING` | `True` | Reduce SSH round-trips for performance |
| `ANSIBLE_SSH_RETRIES` | `3` | Retry transient SSH failures |

### 1.3 SSH Session Management

The `[connection]` section configures SSH multiplexing and keepalives:

| Parameter | Value | Purpose |
|-----------|-------|---------|
| `ControlMaster=auto` | Auto-create multiplexed connections | Reuse TCP sessions across tasks |
| `ControlPersist=60s` | Keep socket alive 60s after last use | Avoid re-auth between plays |
| `ServerAliveInterval=300` | Keepalive every 5 minutes | Prevent idle TCP drops by Azure NSG/firewall |
| `ServerAliveCountMax` | Default (3) | 3 missed keepalives → disconnect (15 min total) |
| `-C` | Compression enabled | Reduce bandwidth on XML/log transfers |

**E2E recommendation**: For destructive HA tests that crash nodes,
`ServerAliveInterval` should be reduced to `30` seconds (via `ANSIBLE_SSH_ARGS`
override) so Ansible detects node unavailability faster after a kernel crash
(`echo b > /proc/sysrq-trigger`). The control socket path must be writable
inside the container (see §2).

### 1.4 Signal Handling for Stuck Playbooks

The executor implements a **two-phase graceful shutdown**:

```
Phase 1: proc.terminate()    →  SIGTERM  →  wait 5 seconds
Phase 2: proc.kill()         →  SIGKILL  →  wait 5 seconds
```

**Exit code interpretation**:

| Exit code | Meaning | Action |
|-----------|---------|--------|
| `0` | Success | Mark job completed |
| `1–4` | Ansible failure (unreachable, parse error, bad options) | Mark job failed, collect artifacts |
| `-9` | SIGKILL (OOM or forced termination) | Mark job failed, alert: possible memory issue |
| `-15` | SIGTERM (graceful cancel) | Mark job cancelled |
| `-11` | SIGSEGV | Mark job failed, alert: crash in Python/module |

**E2E timeout strategy**:

| Scenario type | Expected duration | Popen timeout | GitHub Actions `timeout-minutes` |
|---------------|-------------------|---------------|----------------------------------|
| Config validation | 2–5 min | 3600s (default) | 15 |
| Resource migration | 5–10 min | 3600s (default) | 20 |
| Node crash/kill | 10–20 min | 3600s (default) | 30 |
| Network isolation | 15–25 min | 3600s (default) | 35 |
| Full HA suite | 45–90 min | 3600s (default) | 120 |

### 1.5 Python Interpreter on SAP Target Hosts

The `interpreter_python = auto_silent` setting auto-detects the Python
interpreter on target hosts. SAP systems typically provide:

| OS | Python path | Version | Notes |
|----|-------------|---------|-------|
| SLES 15 SP3+ | `/usr/bin/python3` | 3.6+ | Default on SUSE for SAP |
| RHEL 8.x | `/usr/bin/python3` | 3.6+ | Platform Python |
| RHEL 9.x | `/usr/bin/python3` | 3.9+ | Default installation |

**Requirement**: Target hosts must have `python3` with the following standard
library modules available: `json`, `xml.etree.ElementTree`, `subprocess`,
`datetime`, `os`, `re`. No pip packages are required on targets — all custom
modules use stdlib only.

---

## 2. Docker-to-SAP Connectivity

> **Cross-ref**: Main PRD §4.1 (Management Server), §5 Stage 2 (Container
> Integration), Appendix A.2 (Nightly SAP E2E Workflow)

### 2.1 Network Architecture

The production `deploy/docker-compose.yml` defines a **bridge network**
(`sap-qa-network`) connecting six services. For E2E tests requiring SAP system
access, the container must reach SAP hosts over SSH (port 22) through the
Azure VNet.

#### Option A: Bridge Mode with VNet Peering (Recommended)

```
┌─────────────────────────────────────────────┐
│  Self-Hosted Runner VM (D4s_v5)             │
│  ┌───────────────────────────────────┐      │
│  │  Docker Bridge: sap-qa-network    │      │
│  │  172.18.0.0/16                    │      │
│  │  ┌─────────────┐ ┌────────────┐  │      │
│  │  │ sap-qa-svc  │ │ sap-ui     │  │      │
│  │  │ :8000       │ │ :3000      │  │      │
│  │  └──────┬──────┘ └────────────┘  │      │
│  └─────────┼────────────────────────┘      │
│            │ NAT (iptables MASQUERADE)       │
│            ▼                                │
│  eth0: 10.1.0.4 (VNet subnet)              │
└────────────┼────────────────────────────────┘
             │ VNet Peering / Same VNet
             ▼
┌────────────────────────┐  ┌──────────────────┐
│ SAP HANA Primary       │  │ SAP HANA Secondary│
│ 10.1.1.10 :22          │  │ 10.1.1.11 :22    │
└────────────────────────┘  └──────────────────┘
```

Docker bridge containers reach SAP hosts via the VM's default route. The
Azure VNet routing and NSG rules handle the rest. **No `network_mode: host`
required.**

#### Option B: Host Network Mode (Simplified)

```yaml
network_mode: host
```

Use only if bridge NAT causes issues (e.g., SAP hosts have IP-based ACLs).
Trade-off: no port isolation between containers.

### 2.2 Container-Level SSH Connectivity Validation

Before any E2E test run, the pipeline must validate SSH reachability from
inside the container. Add this as a preflight check in Stage 5:

```bash
#!/usr/bin/env bash
# tests/e2e/scripts/validate_ssh_connectivity.sh
set -euo pipefail

WORKSPACE="${1:?Usage: $0 <workspace_path>}"
INVENTORY="${WORKSPACE}/hosts.yaml"
SSH_KEY="${WORKSPACE}/ssh_key.pem"

# Parse hosts from inventory
HOSTS=$(python3 -c "
import yaml, sys
with open('${INVENTORY}') as f:
    inv = yaml.safe_load(f)
for group in inv.get('all', {}).get('children', {}).values():
    for host, vars in group.get('hosts', {}).items():
        print(vars.get('ansible_host', host))
")

FAILED=0
for HOST in ${HOSTS}; do
    echo -n "Testing SSH to ${HOST}... "
    if ssh -i "${SSH_KEY}" -o StrictHostKeyChecking=no \
           -o ConnectTimeout=10 -o BatchMode=yes \
           root@"${HOST}" "echo OK" 2>/dev/null; then
        echo "PASS"
    else
        echo "FAIL"
        FAILED=$((FAILED + 1))
    fi
done

if [ "${FAILED}" -gt 0 ]; then
    echo "ERROR: ${FAILED} host(s) unreachable. Aborting E2E run."
    exit 1
fi
echo "All hosts reachable."
```

### 2.3 docker-compose.e2e.yml Override Template

Create an E2E-specific override that extends the production compose file:

```yaml
# deploy/docker-compose.e2e.yml
# Usage: docker compose -f docker-compose.yml -f docker-compose.e2e.yml up -d
services:
  sap-qa-service:
    environment:
      # E2E-specific overrides
      LOG_FORMAT: "text"                    # Human-readable for CI logs
      LOG_LEVEL: "DEBUG"                    # Verbose for debugging failures
      ANSIBLE_TIMEOUT: "30"
      ANSIBLE_FORKS: "5"
      ANSIBLE_RETRY_FILES_ENABLED: "False"
      ANSIBLE_PIPELINING: "True"
      ANSIBLE_SSH_RETRIES: "3"
      # Telemetry: send to dedicated E2E workspace
      TELEMETRY_DATA_DESTINATION: "laws"
      LAWS_WORKSPACE_ID: "${E2E_LAWS_WORKSPACE_ID}"
      LAWS_SHARED_KEY: "${E2E_LAWS_SHARED_KEY}"
    volumes:
      # E2E workspace with SAP system credentials
      - "${E2E_WORKSPACE_PATH}:/app/WORKSPACES/E2E:ro"
      # SSH key mount (read-only)
      - "${E2E_SSH_KEY_PATH}:/app/WORKSPACES/E2E/ssh_key.pem:ro"
      # Custom ansible.cfg (if overrides needed beyond env vars)
      - "./ansible.e2e.cfg:/app/src/ansible.cfg:ro"
    extra_hosts:
      # Static DNS entries if VNet DNS is unavailable from container
      - "hana-primary:10.1.1.10"
      - "hana-secondary:10.1.1.11"
      - "scs-node1:10.1.2.10"
      - "scs-node2:10.1.2.11"

  # Disable non-essential services for E2E
  sap-ollama:
    profiles: ["full"]          # Only start with --profile full
  sap-mcp-server:
    profiles: ["full"]
  azure-mcp:
    profiles: ["full"]
  sap-devui:
    profiles: ["full"]
```

### 2.4 Volume Mount Strategy

| Mount | Container path | Mode | Purpose |
|-------|---------------|------|---------|
| SSH private key | `/app/WORKSPACES/<SID>/ssh_key.pem` | `ro` | Ansible `--private-key` flag |
| Inventory | `/app/WORKSPACES/<SID>/hosts.yaml` | `ro` | Ansible `-i` inventory |
| SAP parameters | `/app/WORKSPACES/<SID>/sap-parameters.yaml` | `ro` | Extra-vars for playbooks |
| ansible.cfg | `/app/src/ansible.cfg` | `ro` | Ansible configuration |
| SQLite DB | `/app/data/` (named volume) | `rw` | Job/schedule persistence |
| Artifacts | `/app/WORKSPACES/<SID>/quality_assurance/` | `rw` | HTML reports, cluster reports |
| SSH control sockets | `/app/.ssh-sockets/` | `rw` | `ControlPath` for multiplexing |

**Key considerations**:

1. **SSH key permissions**: The Dockerfile must `chmod 600` the key, or the
   `SshCredentialProvider` handles it at runtime. Docker bind-mount preserves
   host permissions — ensure the host file is `600` before mounting.
2. **ControlPath**: The default `ControlPath=/tmp/ansible-ssh-%h-%p-%r` works
   inside the container. If `/tmp` is `noexec`, override via `ANSIBLE_SSH_ARGS`.
3. **Named volume for SQLite**: Never bind-mount SQLite DB files — use Docker
   named volumes to avoid WAL mode corruption from host filesystem semantics.

### 2.5 DNS Resolution from Container to VNet

Three strategies, in order of preference:

1. **Azure Private DNS Zone** — Attach the runner VM's VNet to a private DNS
   zone containing SAP host records. Docker bridge inherits the VM's
   `/etc/resolv.conf` (if `dns` is not overridden in compose).

2. **`extra_hosts` in compose** — Static entries (shown in §2.3). Simple but
   requires manual updates when IPs change.

3. **Custom DNS server** — Run a lightweight DNS forwarder (e.g., `dnsmasq`)
   on the runner VM. Overkill for most deployments.

**Validation**: The SSH connectivity check in §2.2 implicitly validates DNS
resolution. If hostnames are used in inventory, they must resolve from inside
the container.

---

## 3. Cluster Recovery Specification

> **Cross-ref**: Main PRD §5 Stage 5 (Live SAP System Tests), §6.3 (Cleanup &
> Reset), §7.5 (Timeout & Retry Policies), §11 (Risk Register — flaky HA tests)

### 3.1 HANA Database HA Scenarios (15 total)

All task files located in `src/roles/ha_db_hana/tasks/`. Each destructive
scenario follows the `block/rescue/always` pattern with pre-validation,
execution, and post-validation phases.

| # | Scenario | Task file | Destructive action | Recovery steps | P50 recovery | P95 recovery |
|---|----------|-----------|--------------------|----------------|-------------|-------------|
| 1 | HA Config Validation | `ha-config.yml` | None (read-only) | N/A | 2 min | 4 min |
| 2 | HA Config Offline | `ha-config-offline.yml` | None (XML parse) | N/A | 30 sec | 1 min |
| 3 | Azure LB Validation | `azure-lb.yml` | LB probe test | Probe auto-recovery | 3 min | 5 min |
| 4 | Resource Migration | `resource-migration.yml` | `crm resource move` | `location_constraints` module removes constraints; cluster auto-rebalances | 5 min | 10 min |
| 5 | Primary Node Crash | `primary-node-crash.yml` | `HDB stop` (graceful) | Failover to secondary; `crm resource cleanup`; re-register if `AUTOMATED_REGISTER=false` via `hdbnsutil -sr_register` | 8 min | 15 min |
| 6 | Primary Node Kill | `primary-node-kill.yml` | `HDB kill-9` (force) | STONITH fences node; failover; register failed resource; `crm resource cleanup` | 10 min | 18 min |
| 7 | Primary Indexserver Crash | `primary-crash-index.yml` | Kill indexserver process | HANA auto-restarts indexserver; cluster detects and recovers | 5 min | 12 min |
| 8 | Primary Echo-B | `primary-echo-b.yml` | `echo b > /proc/sysrq-trigger` (kernel crash) | VM reboots via Azure; STONITH detects; failover; async poll until node online; `crm resource cleanup` | 12 min | 20 min |
| 9 | Secondary Node Kill | `secondary-node-kill.yml` | `kill -9` via `/proc/sysrq-trigger` on secondary | Node reboots; `crm resource cleanup` on secondary resources | 8 min | 15 min |
| 10 | Secondary Indexserver Crash | `secondary-crash-index.yml` | Kill secondary indexserver | HANA auto-restart; verify replication resumes | 5 min | 10 min |
| 11 | Secondary Echo-B | `secondary-echo-b.yml` | Kernel crash on secondary | VM reboots; verify secondary rejoins cluster | 10 min | 18 min |
| 12 | Network Isolation | `block-network.yml` | `iptables -A INPUT -j DROP` (isolation) | Rescue block: `iptables -F` (flush rules); verify cluster reform | 12 min | 22 min |
| 13 | HANA Shared Block | `block-hana-shared.yml` | Block HANA shared mount | Rescue block: unblock/remount; `crm resource cleanup` | 10 min | 18 min |
| 14 | Filesystem Freeze (ANF) | `fs-freeze.yml` | `mount -o ro` (read-only freeze) | Rescue block: `mount -o rw` (remount read-write); verify I/O resumes | 8 min | 15 min |
| 15 | SBD Fencing | `sbd-fencing.yml` | Kill SBD inquisitor process | Process auto-restart; verify SBD watchdog active | 5 min | 10 min |

### 3.2 SCS HA Scenarios (14 total)

All task files located in `src/roles/ha_scs/tasks/`. SCS scenarios include
ENSA1/ENSA2 variant detection via `pgrep -f 'enq.sap'`.

| # | Scenario | Task file | Destructive action | Recovery steps | P50 recovery | P95 recovery |
|---|----------|-----------|--------------------|----------------|-------------|-------------|
| 1 | HA Config Validation | `ha-config.yml` | None (read-only) | N/A | 2 min | 4 min |
| 2 | HA Config Offline | `ha-config-offline.yml` | None (XML parse) | N/A | 30 sec | 1 min |
| 3 | Azure LB Validation | `azure-lb.yml` | LB probe test | Probe auto-recovery | 3 min | 5 min |
| 4 | SAPControl Config | `sapcontrol-config.yml` | None (validation) | N/A | 2 min | 4 min |
| 5 | ASCS Migration | `ascs-migration.yml` | `crm resource move` ASCS | Constraint removal; ASCS/ERS swap validation | 5 min | 10 min |
| 6 | ASCS Node Crash | `ascs-node-crash.yml` | `echo b > /proc/sysrq-trigger` on ASCS node | VM reboots; ASCS fails to ERS node; `crm resource cleanup`; ENSA1/ENSA2-specific validation | 12 min | 20 min |
| 7 | Kill Message Server | `kill-message-server.yml` | `kill -9` message server PID | SAP auto-restart or failover; cluster stabilization | 5 min | 12 min |
| 8 | Kill Enqueue Server | `kill-enqueue-server.yml` | `kill -9` enqueue server PID | ENSA1: lock loss → ERS takes over; ENSA2: lock preserved → restart | 5 min | 12 min |
| 9 | Kill Enqueue Replication | `kill-enqueue-replication.yml` | `kill -9` enqueue replication PID | Replication server restarts; lock table validated | 5 min | 10 min |
| 10 | Kill SAPStartSrv | `kill-sapstartsrv-process.yml` | `kill -9` sapstartsrv daemon | Process respawns via systemd; SAP services remain available | 3 min | 8 min |
| 11 | Manual Restart | `manual-restart.yml` | `sapcontrol -function Stop` | `sapcontrol -function Start`; poll `GetProcessList` until GREEN | 5 min | 10 min |
| 12 | HA Failover to Node | `ha-failover-to-node.yml` | Explicit pacemaker failover | Wait for cluster stabilization; validate resource placement | 8 min | 15 min |
| 13 | Network Isolation | `block-network.yml` | `iptables -A INPUT -j DROP` | Rescue: `iptables -F`; cluster reform; ASCS/ERS placement check | 12 min | 22 min |

### 3.3 Automated Recovery Steps — Common Pattern

Every destructive scenario in STAF follows this Ansible structure:

```yaml
# 1. Test Case Setup
- include_tasks: "roles/misc/tasks/test-case-setup.yml"
  # → Generates UUID, initializes telemetry fields

# 2. Pre-Validation
- include_tasks: "roles/misc/tasks/pre-validations-db.yml"   # or pre-validations-scs.yml
  # → Removes stale constraints, detects topology, records primary/secondary

# 3. Destructive Action (block/rescue/always)
- block:
    - name: "Execute destructive action"
      # ... kill, crash, block, etc.
    - name: "Validate cluster recovery"
      get_cluster_status_db:
        retries: "{{ default_retries }}"     # Typically 25
        delay: "{{ default_delay }}"         # Typically 30 seconds
        until: >
          cluster_status.primary_node != "" and
          cluster_status.primary_node == cluster_status_pre.secondary_node
  rescue:
    - include_tasks: "roles/misc/tasks/rescue.yml"
      # → Collect /var/log/messages, set FAILED status, clear host errors

# 4. Post-Validation (always runs)
- include_tasks: "roles/misc/tasks/post-validations.yml"
  # → Merge logs, send telemetry (LAWS + ADX), generate report
```

**Recovery validation** uses `BaseClusterStatusChecker` (template method
pattern) with up to **25 polling attempts**. The checker:

1. Calls `systemctl is-active pacemaker` to verify cluster daemon.
2. Parses `crm_mon --output-as=xml` for node status.
3. Validates all nodes `online="true"`.
4. Checks primary/secondary role assignment via abstract hooks.
5. Returns `TestStatus.SUCCESS` or `TestStatus.FAILURE`.

### 3.4 Circuit Breaker Logic

**Specification**: If a scenario fails **2 consecutive times** across separate
E2E runs, the pipeline should skip that scenario and raise an alert.

Implementation approach:

```yaml
# In GitHub Actions workflow (e2e-nightly.yml)
- name: Check circuit breaker
  id: circuit_breaker
  run: |
    # Query last 2 runs for this scenario from telemetry
    FAIL_COUNT=$(curl -s "${LAWS_QUERY_ENDPOINT}" \
      --data-urlencode "query=
        StafTestResults_CL
        | where test_case_name_s == '${SCENARIO}'
        | top 2 by timestamp desc
        | where test_case_status_s == 'FAILED'
        | count" | jq '.tables[0].rows[0][0]')

    if [ "${FAIL_COUNT}" -ge 2 ]; then
      echo "skip=true" >> "$GITHUB_OUTPUT"
      echo "::warning::Circuit breaker OPEN for ${SCENARIO} (${FAIL_COUNT} consecutive failures)"
    else
      echo "skip=false" >> "$GITHUB_OUTPUT"
    fi

- name: Run scenario
  if: steps.circuit_breaker.outputs.skip != 'true'
  run: |
    # Execute the scenario via API
```

**Alert channels**:

- GitHub Actions annotation (`::warning::`)
- Slack/Teams webhook (optional, configured per environment)
- Telemetry record with `circuit_breaker_triggered=true` flag

### 3.5 Weekly Full Reset Procedure

**Schedule**: Sunday 02:00 UTC (before Monday nightly runs).

**Purpose**: Restore all SAP test systems to a known-good baseline, clearing
any accumulated drift from destructive tests.

```bash
#!/usr/bin/env bash
# scripts/weekly_cluster_reset.sh
set -euo pipefail

WORKSPACE="${1:?Usage: $0 <workspace_path>}"
INVENTORY="${WORKSPACE}/hosts.yaml"
SSH_KEY="${WORKSPACE}/ssh_key.pem"
SSH_OPTS="-i ${SSH_KEY} -o StrictHostKeyChecking=no"

echo "=== Weekly Cluster Reset: $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="

# Step 1: Clear all location constraints
echo "[1/6] Clearing location constraints..."
ansible all -i "${INVENTORY}" --private-key "${SSH_KEY}" -b \
  -m shell -a "crm resource clear \$(crm_resource --list-raw 2>/dev/null | head -1) 2>/dev/null || true"

# Step 2: Cleanup all resources
echo "[2/6] Cleaning up Pacemaker resources..."
ansible all -i "${INVENTORY}" --private-key "${SSH_KEY}" -b \
  -m shell -a "crm_resource --cleanup 2>/dev/null || pcs resource cleanup 2>/dev/null || true"

# Step 3: Flush iptables (in case network isolation left remnants)
echo "[3/6] Flushing iptables rules..."
ansible all -i "${INVENTORY}" --private-key "${SSH_KEY}" -b \
  -m shell -a "iptables -F && iptables -X && iptables -P INPUT ACCEPT"

# Step 4: Verify HANA replication status
echo "[4/6] Verifying HANA replication..."
ansible all -i "${INVENTORY}" --private-key "${SSH_KEY}" -b \
  -m shell -a "su - {{ sap_sid }}adm -c 'hdbnsutil -sr_state' 2>/dev/null || true"

# Step 5: Restart Pacemaker cluster
echo "[5/6] Restarting cluster services..."
ansible all -i "${INVENTORY}" --private-key "${SSH_KEY}" -b \
  -m shell -a "crm cluster restart 2>/dev/null || pcs cluster start --all 2>/dev/null || true"

# Step 6: Wait for stabilization and validate
echo "[6/6] Waiting 120s for cluster stabilization..."
sleep 120
ansible all -i "${INVENTORY}" --private-key "${SSH_KEY}" -b \
  -m shell -a "crm_mon -1 --output-as=xml" | head -50

echo "=== Reset complete ==="
```

### 3.6 Manual Escalation Runbook

When automated recovery fails (circuit breaker opens), follow this escalation
procedure:

| Step | Action | Owner | SLA |
|------|--------|-------|-----|
| 1 | Circuit breaker alert fires | Automation | Immediate |
| 2 | Check telemetry for failure pattern | On-call engineer | 30 min |
| 3 | SSH to affected node, check `crm status` and `/var/log/messages` | On-call engineer | 1 hour |
| 4 | Attempt manual recovery (see per-scenario table in §3.1/3.2) | On-call engineer | 2 hours |
| 5 | If manual recovery fails: restore from Azure backup (§4) | Infrastructure team | 4 hours |
| 6 | If restore fails: re-provision SAP system from template | Infrastructure team | 8 hours |
| 7 | Update circuit breaker state to allow retries | On-call engineer | Post-fix |

**Common manual recovery commands**:

```bash
# HANA: Re-register secondary after takeover
su - <sid>adm -c "hdbnsutil -sr_register --remoteHost=<primary> \
  --remoteInstance=<inst> --replicationMode=sync --operationMode=logreplay \
  --name=<site>"

# HANA: Start system replication
su - <sid>adm -c "HDB start"

# Pacemaker: Clear failed resources
crm resource cleanup <resource_id>

# SCS: Restart SAP instance
sapcontrol -nr <inst> -function Start
sapcontrol -nr <inst> -function GetProcessList   # Poll until GREEN

# Network: Reset firewall
iptables -F && iptables -X && iptables -P INPUT ACCEPT

# SBD: Restart watchdog
systemctl restart sbd
```

---

## 4. Backup Infrastructure Bootstrap

> **Cross-ref**: Main PRD §4.2 (SAP Test Landscape — Backup & Recovery
> Infrastructure), §6.3 (Cleanup & Reset)

### 4.1 Recovery Services Vault Provisioning

```bash
#!/usr/bin/env bash
# infra/bootstrap_backup.sh — One-time setup

RESOURCE_GROUP="rg-staf-e2e"
VAULT_NAME="rsv-staf-e2e"
LOCATION="eastus2"

# Create Recovery Services vault
az backup vault create \
  --resource-group "${RESOURCE_GROUP}" \
  --name "${VAULT_NAME}" \
  --location "${LOCATION}" \
  --sku Standard

# Enable soft delete (30-day retention for accidental deletion)
az backup vault backup-properties set \
  --resource-group "${RESOURCE_GROUP}" \
  --name "${VAULT_NAME}" \
  --soft-delete-feature-state Enable

# Enable cross-region restore (for DR scenarios)
az backup vault backup-properties set \
  --resource-group "${RESOURCE_GROUP}" \
  --name "${VAULT_NAME}" \
  --cross-region-restore-flag Enable
```

### 4.2 Backup Policy Creation

Three policy types required for comprehensive SAP HANA backup:

#### Full Backup Policy (Weekly)

```bash
az backup policy create \
  --resource-group "${RESOURCE_GROUP}" \
  --vault-name "${VAULT_NAME}" \
  --name "policy-hana-full-weekly" \
  --backup-management-type AzureWorkload \
  --workload-type SAPHANA \
  --policy '{
    "policyType": "Full",
    "schedulePolicy": {
      "schedulePolicyType": "SimpleSchedulePolicy",
      "scheduleRunFrequency": "Weekly",
      "scheduleRunDays": ["Sunday"],
      "scheduleRunTimes": ["2024-01-01T02:00:00Z"]
    },
    "retentionPolicy": {
      "retentionPolicyType": "LongTermRetentionPolicy",
      "weeklySchedule": {
        "daysOfTheWeek": ["Sunday"],
        "retentionTimes": ["2024-01-01T02:00:00Z"],
        "retentionDuration": { "count": 4, "durationType": "Weeks" }
      }
    }
  }'
```

#### Differential Backup Policy (Daily)

```bash
az backup policy create \
  --resource-group "${RESOURCE_GROUP}" \
  --vault-name "${VAULT_NAME}" \
  --name "policy-hana-diff-daily" \
  --backup-management-type AzureWorkload \
  --workload-type SAPHANA \
  --policy '{
    "policyType": "Differential",
    "schedulePolicy": {
      "schedulePolicyType": "SimpleSchedulePolicy",
      "scheduleRunFrequency": "Daily",
      "scheduleRunTimes": ["2024-01-01T06:00:00Z"]
    },
    "retentionPolicy": {
      "retentionPolicyType": "SimpleRetentionPolicy",
      "retentionDuration": { "count": 14, "durationType": "Days" }
    }
  }'
```

#### Log Backup Policy (Continuous)

```bash
az backup policy create \
  --resource-group "${RESOURCE_GROUP}" \
  --vault-name "${VAULT_NAME}" \
  --name "policy-hana-log-continuous" \
  --backup-management-type AzureWorkload \
  --workload-type SAPHANA \
  --policy '{
    "policyType": "Log",
    "schedulePolicy": {
      "schedulePolicyType": "LogSchedulePolicy",
      "scheduleFrequencyInMins": 15
    },
    "retentionPolicy": {
      "retentionPolicyType": "SimpleRetentionPolicy",
      "retentionDuration": { "count": 7, "durationType": "Days" }
    }
  }'
```

### 4.3 Initial Backup Seeding Procedure

After SAP systems are provisioned and verified healthy, capture the initial
baseline backup:

```bash
# 1. Register SAP HANA instance with the vault
az backup container register \
  --resource-group "${RESOURCE_GROUP}" \
  --vault-name "${VAULT_NAME}" \
  --backup-management-type AzureWorkload \
  --workload-type SAPHANA \
  --resource-id "/subscriptions/${SUB_ID}/resourceGroups/${RG}/providers/Microsoft.Compute/virtualMachines/${VM_NAME}"

# 2. Discover protectable items
az backup protectable-item list \
  --resource-group "${RESOURCE_GROUP}" \
  --vault-name "${VAULT_NAME}" \
  --backup-management-type AzureWorkload \
  --workload-type SAPHANA

# 3. Enable protection (applies full + diff + log policies)
az backup protection enable-for-azurewl \
  --resource-group "${RESOURCE_GROUP}" \
  --vault-name "${VAULT_NAME}" \
  --policy-name "policy-hana-full-weekly" \
  --protectable-item-name "saphanadatabase;${SID};${DB_NAME}" \
  --protectable-item-type SAPHANADatabase \
  --server-name "${VM_NAME}" \
  --workload-type SAPHANA

# 4. Trigger initial full backup (don't wait for schedule)
az backup protection backup-now \
  --resource-group "${RESOURCE_GROUP}" \
  --vault-name "${VAULT_NAME}" \
  --container-name "VMAppContainer;Compute;${RG};${VM_NAME}" \
  --item-name "saphanadatabase;${SID};${DB_NAME}" \
  --backup-type Full \
  --retain-until "$(date -d '+30 days' +%Y-%m-%d)"
```

### 4.4 Cross-VM Restore Target Requirements

For E2E tests that validate backup/restore workflows
(`playbook_00_backup_db_functional_tests.yml`):

| Requirement | Specification |
|-------------|---------------|
| Target VM | Must be in the same region as source |
| HANA version | Must match source HANA version exactly |
| Storage layout | `/hana/data`, `/hana/log`, `/hana/shared` must exist with sufficient space |
| Pre-registration | Target must be registered with the Recovery Services vault |
| Network | Target must be reachable from the STAF runner for validation |
| SAP user | `<sid>adm` must exist with correct UID/GID |

### 4.5 HANA hdbuserstore Key Configuration

The `hdbuserstore` is required for Ansible modules to connect to HANA without
embedding passwords in playbooks:

```bash
# On each HANA node, as <sid>adm:
hdbuserstore SET STAFKEY <hostname>:3<inst>13 SYSTEM <password>

# Verify:
hdbuserstore LIST STAFKEY

# Expected output:
# KEY STAFKEY
#   ENV : <hostname>:3<inst>13
#   USER: SYSTEM
```

**E2E validation**: The pre-validation tasks should verify the key exists:

```bash
su - <sid>adm -c "hdbuserstore LIST STAFKEY" | grep -q "ENV"
```

### 4.6 Estimated Storage Costs

| Component | Size estimate | Monthly cost (LRS) |
|-----------|--------------|-------------------|
| Full backup (per HANA system, 500 GB DB) | ~150 GB compressed | $7.50 |
| Differential daily (14-day retention) | ~30 GB × 14 = 420 GB | $21.00 |
| Log backup (7-day retention, 15-min RPO) | ~5 GB/day × 7 = 35 GB | $1.75 |
| **Per system total** | **~605 GB** | **~$30.25** |
| **6 SAP test systems** | **~3.6 TB** | **~$181.50** |

> **Note**: Costs based on Azure Backup for SAP HANA pricing in East US 2
> (RA-GRS). Actual compression ratios vary by workload.

---

## 5. Offline Validation Fixture Specification

> **Cross-ref**: Main PRD §5 Stage 4 (Offline SAP Validation), §3 (Test
> Architecture — Tier 3a)

### 5.1 Fixture Types Required

Each fixture is a sanitized CIB XML snapshot representing a specific SAP
cluster configuration. The offline validation module
(`src/roles/misc/tasks/offline-validation.yml`) processes these fixtures through
`get_pcmk_properties_db` or `get_pcmk_properties_scs` without requiring a
live cluster.

| # | Fixture name | OS family | Topology | SR Provider | ENSA | Use case |
|---|-------------|-----------|----------|-------------|------|----------|
| 1 | `suse-scaleup-saphanasr.xml` | SUSE | Scale-Up | SAPHanaSR | N/A | Standard two-node HSR |
| 2 | `suse-scaleup-angi.xml` | SUSE | Scale-Up | SAPHanaSR-angi | N/A | Next-gen provider |
| 3 | `rhel-scaleup-saphanasr.xml` | RHEL | Scale-Up | SAPHanaSR | N/A | RHEL pcs-based cluster |
| 4 | `suse-scaleout-hsr.xml` | SUSE | Scale-Out HSR | SAPHanaSR-ScaleOut | N/A | Multi-node replication |
| 5 | `suse-scaleout-standby.xml` | SUSE | Scale-Out Standby | SAPHanaSR | N/A | Standby node topology |
| 6 | `suse-scs-ensa1.xml` | SUSE | N/A | N/A | ENSA1 | Classic enqueue server |
| 7 | `suse-scs-ensa2.xml` | SUSE | N/A | N/A | ENSA2 | Standalone enqueue server 2 |
| 8 | `rhel-scs-ensa2.xml` | RHEL | N/A | N/A | ENSA2 | RHEL SCS cluster |

### 5.2 Automated Capture Procedure

Fixtures should be captured from known-good production-like SAP systems and
sanitized to remove sensitive data:

```bash
#!/usr/bin/env bash
# scripts/capture_cib_fixture.sh
set -euo pipefail

HOST="${1:?Usage: $0 <host> <fixture_name> [ssh_key]}"
FIXTURE_NAME="${2:?}"
SSH_KEY="${3:-~/.ssh/id_rsa}"
FIXTURE_DIR="tests/fixtures/cib"

echo "Capturing CIB from ${HOST}..."

# Step 1: Extract raw CIB XML
ssh -i "${SSH_KEY}" -o StrictHostKeyChecking=no root@"${HOST}" \
  "cibadmin --query" > "${FIXTURE_DIR}/${FIXTURE_NAME}.raw.xml"

# Step 2: Sanitize sensitive data
python3 -c "
import xml.etree.ElementTree as ET
import re, sys

tree = ET.parse('${FIXTURE_DIR}/${FIXTURE_NAME}.raw.xml')
root = tree.getroot()

# Replace IP addresses with test IPs (10.0.0.0/8 range)
xml_str = ET.tostring(root, encoding='unicode')

# Sanitize hostnames → generic names
xml_str = re.sub(r'(value=\")\d+\.\d+\.\d+\.\d+', r'\g<1>10.0.0.1', xml_str)

# Remove any password/secret attributes
for elem in ET.fromstring(xml_str).iter():
    for attr in ['passwd', 'password', 'secret']:
        if attr in elem.attrib:
            elem.set(attr, 'REDACTED')

tree = ET.ElementTree(ET.fromstring(xml_str))
tree.write('${FIXTURE_DIR}/${FIXTURE_NAME}.xml', xml_declaration=True, encoding='unicode')
print('Sanitized fixture written.')
"

# Step 3: Remove raw file
rm -f "${FIXTURE_DIR}/${FIXTURE_NAME}.raw.xml"

# Step 4: Validate fixture is parseable
python3 -c "
import xml.etree.ElementTree as ET
tree = ET.parse('${FIXTURE_DIR}/${FIXTURE_NAME}.xml')
root = tree.getroot()
nodes = root.findall('.//node')
resources = root.findall('.//primitive')
print(f'Valid CIB: {len(nodes)} nodes, {len(resources)} resources')
assert len(nodes) >= 2, 'CIB must contain at least 2 nodes'
assert len(resources) >= 1, 'CIB must contain at least 1 resource'
"

echo "Fixture '${FIXTURE_NAME}' captured and validated."
```

### 5.3 Schema Version Tracking and Staleness Detection

Each fixture must include metadata for version tracking:

```yaml
# tests/fixtures/cib/fixture_manifest.yaml
fixtures:
  suse-scaleup-saphanasr:
    file: "suse-scaleup-saphanasr.xml"
    captured_from: "hana-su-suse-01"
    captured_at: "2024-12-15T10:30:00Z"
    cib_schema_version: "pacemaker-3.7"
    pacemaker_version: "2.1.5"
    saphanasr_version: "0.162.3"
    os_version: "SLES 15 SP5"
    stale_after_days: 90
    last_validated: "2024-12-15T10:30:00Z"
```

**Staleness detection** (run in CI as a scheduled check):

```python
# tests/e2e/check_fixture_staleness.py
import yaml
from datetime import datetime, timedelta, timezone

with open("tests/fixtures/cib/fixture_manifest.yaml") as f:
    manifest = yaml.safe_load(f)

stale = []
for name, meta in manifest["fixtures"].items():
    captured = datetime.fromisoformat(meta["captured_at"])
    max_age = timedelta(days=meta["stale_after_days"])
    if datetime.now(timezone.utc) - captured > max_age:
        stale.append(f"{name}: captured {meta['captured_at']} "
                     f"(>{meta['stale_after_days']} days ago)")

if stale:
    print("WARNING: Stale CIB fixtures detected:")
    for s in stale:
        print(f"  - {s}")
    print("Run scripts/capture_cib_fixture.sh to refresh.")
    exit(1)
```

### 5.4 Fixture Validation Requirements

Each fixture must pass these checks before being committed:

| Check | Validation | Tool |
|-------|-----------|------|
| **Parseable** | `ET.parse()` succeeds without exceptions | Python stdlib |
| **Min nodes** | ≥ 2 `<node>` elements present | XPath query |
| **Min resources** | ≥ 1 `<primitive>` element present | XPath query |
| **No secrets** | No `passwd`, `password`, `secret` attributes with real values | Regex scan |
| **No real IPs** | No public IP addresses (only 10.x.x.x or 192.168.x.x) | Regex scan |
| **Schema match** | `validate-with` attribute matches expected Pacemaker schema | Attribute check |
| **Resource types** | Expected resource agents present (e.g., `ocf:suse:SAPHana`) | XPath query |
| **STONITH configured** | At least one STONITH resource present | XPath query |

---

## 6. Workspace & Inventory Management

> **Cross-ref**: Main PRD §4.1 (Management Server), §4.4 (Authentication &
> Credentials), §6.1 (Provisioning), §6.4 (State Management)

### 6.1 Static IP Enforcement on Azure VMs

All SAP test VMs **must** use static private IP addresses. Dynamic DHCP
assignments would break inventory files between VM restarts.

```bash
# Enforce static IP on existing VM NIC
az network nic ip-config update \
  --resource-group "${RESOURCE_GROUP}" \
  --nic-name "${NIC_NAME}" \
  --name ipconfig1 \
  --private-ip-address-allocation Static \
  --private-ip-address "10.1.1.10"
```

**Validation** (run as preflight in E2E pipeline):

```bash
# Verify all VMs have static IPs
for VM in hana-su-primary hana-su-secondary scs-node1 scs-node2; do
  ALLOC=$(az vm show -g "${RESOURCE_GROUP}" -n "${VM}" \
    --query "networkProfile.networkInterfaces[0].id" -o tsv \
    | xargs -I{} az network nic show --ids {} \
    --query "ipConfigurations[0].privateIpAllocationMethod" -o tsv)
  if [ "${ALLOC}" != "Static" ]; then
    echo "ERROR: ${VM} has ${ALLOC} IP allocation (must be Static)"
    exit 1
  fi
done
```

### 6.2 Inventory Template with Parameterization

STAF workspaces use `hosts.yaml` as the Ansible inventory. The E2E framework
should provide a parameterized template:

```yaml
# WORKSPACES/E2E-HANA-SU/hosts.yaml
all:
  vars:
    ansible_user: root
    ansible_ssh_private_key_file: "{{ workspace_path }}/ssh_key.pem"
    ansible_python_interpreter: /usr/bin/python3
  children:
    db:
      hosts:
        hana-primary:
          ansible_host: "{{ hana_primary_ip }}"      # 10.1.1.10
          node_tier: "db"
          hana_site: "{{ hana_primary_site }}"        # e.g., "DC1"
        hana-secondary:
          ansible_host: "{{ hana_secondary_ip }}"     # 10.1.1.11
          node_tier: "db"
          hana_site: "{{ hana_secondary_site }}"      # e.g., "DC2"
```

**Corresponding `sap-parameters.yaml`**:

```yaml
# WORKSPACES/E2E-HANA-SU/sap-parameters.yaml
sap_sid: "HDB"
db_sid: "HDB"
sap_instance_number: "00"
db_instance_number: "00"
platform: "HANA"
cluster_type: "scaleup"
hana_topology: "scale_up"
ansible_os_family: "Suse"        # or "RedHat"
fencing_mechanism: "SBD"          # or "azure_fence_agent"
AUTOMATED_REGISTER: "true"
```

### 6.3 sap-parameters.yaml Validation Against Live System

Before E2E runs, validate that workspace parameters match the actual SAP
system configuration:

```python
# tests/e2e/validate_workspace_params.py
"""Validate workspace sap-parameters.yaml against live SAP system."""
import yaml
import subprocess
import sys


def validate(workspace_path: str, inventory_path: str) -> list[str]:
    """Return list of validation errors (empty = success)."""
    errors = []

    with open(f"{workspace_path}/sap-parameters.yaml") as f:
        params = yaml.safe_load(f)

    sid = params.get("sap_sid", "").upper()
    inst = params.get("db_instance_number", "00")

    # Check SID matches on remote host
    result = subprocess.run(
        ["ansible", "all", "-i", inventory_path, "-b",
         "-m", "shell", "-a", f"su - {sid.lower()}adm -c 'HDB info' 2>/dev/null | head -5"],
        capture_output=True, text=True, timeout=30,
    )
    if sid not in result.stdout:
        errors.append(f"SID '{sid}' not found on target hosts")

    # Check instance number
    if f"HDB{inst}" not in result.stdout and f"{inst}" not in result.stdout:
        errors.append(f"Instance number '{inst}' not found in HDB info")

    # Check OS family matches
    os_result = subprocess.run(
        ["ansible", "all", "-i", inventory_path, "-b",
         "-m", "setup", "-a", "filter=ansible_os_family"],
        capture_output=True, text=True, timeout=30,
    )
    expected_os = params.get("ansible_os_family", "")
    if expected_os and expected_os not in os_result.stdout:
        errors.append(
            f"OS family '{expected_os}' not found (got: {os_result.stdout[:200]})"
        )

    return errors


if __name__ == "__main__":
    workspace = sys.argv[1]
    inventory = f"{workspace}/hosts.yaml"
    errs = validate(workspace, inventory)
    if errs:
        print("Workspace validation FAILED:")
        for e in errs:
            print(f"  ✗ {e}")
        sys.exit(1)
    print("Workspace validation PASSED ✓")
```

### 6.4 Dynamic Inventory Alternative (Azure Resource Graph)

For environments with many SAP systems, a dynamic inventory plugin can
replace static `hosts.yaml` files:

```python
# src/inventory/azure_sap_inventory.py
"""
Azure Resource Graph-based dynamic inventory for SAP systems.

Usage:
  ansible-playbook -i azure_sap_inventory.py playbook.yml

Environment variables:
  AZURE_SUBSCRIPTION_ID  - Target subscription
  SAP_ENVIRONMENT_TAG    - Filter VMs by tag (e.g., "e2e-hana-su")
"""
import json
import os
import subprocess
import sys


def build_inventory() -> dict:
    """Query Azure Resource Graph for SAP-tagged VMs."""
    env_tag = os.environ.get("SAP_ENVIRONMENT_TAG", "e2e")
    subscription = os.environ.get("AZURE_SUBSCRIPTION_ID", "")

    query = f"""
    Resources
    | where type == 'microsoft.compute/virtualmachines'
    | where tags.sap_environment == '{env_tag}'
    | project name, privateIp=properties.networkProfile.networkInterfaces[0],
              tags, resourceGroup
    """

    result = subprocess.run(
        ["az", "graph", "query", "-q", query,
         "--subscriptions", subscription, "-o", "json"],
        capture_output=True, text=True, timeout=30,
    )
    vms = json.loads(result.stdout).get("data", [])

    inventory = {
        "all": {"children": {"db": {"hosts": {}}, "scs": {"hosts": {}}}},
        "_meta": {"hostvars": {}},
    }

    for vm in vms:
        name = vm["name"]
        tier = vm.get("tags", {}).get("node_tier", "db")
        group = "db" if tier in ("db", "hana") else "scs"

        inventory["all"]["children"][group]["hosts"][name] = {}
        inventory["_meta"]["hostvars"][name] = {
            "ansible_host": vm.get("tags", {}).get("private_ip", name),
            "node_tier": tier,
            "ansible_user": "root",
            "ansible_python_interpreter": "/usr/bin/python3",
        }

    return inventory


if __name__ == "__main__":
    if "--list" in sys.argv:
        print(json.dumps(build_inventory(), indent=2))
    elif "--host" in sys.argv:
        print(json.dumps({}))
```

**Tagging convention** for SAP VMs:

| Tag | Example value | Purpose |
|-----|--------------|---------|
| `sap_environment` | `e2e-hana-su` | Environment/workspace identifier |
| `node_tier` | `db`, `scs`, `app` | Ansible group assignment |
| `private_ip` | `10.1.1.10` | Stable IP for inventory |
| `sap_sid` | `HDB` | SAP System ID |
| `hana_site` | `DC1` | Replication site name |

---

## Document History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0.0 | 2025-07-18 | Lambert | Initial infrastructure addendum |
