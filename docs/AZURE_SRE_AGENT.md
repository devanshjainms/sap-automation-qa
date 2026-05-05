# Integrating STAF with Azure SRE Agent

Connect the SAP Testing Automation Framework (STAF) to
[Azure SRE Agent](https://learn.microsoft.com/en-us/azure/sre-agent/) so your
on-call team can triage SAP cluster incidents, run HA functional tests, and
validate configurations — all from a single chat interface.

| Capability | What STAF adds |
|------------|---------------|
| **HA functional testing** | 29 test scenarios (15 HANA + 14 SCS) executable on-demand or on a schedule |
| **Configuration validation** | Drift detection for HANA, Db2, SCS, and application instances |
| **SAP cluster triage** | Automated evidence collection across Pacemaker, HANA HSR, SCS/ERS, and Azure platform layers |

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Quick Start (5 Minutes)](#2-quick-start-5-minutes)
3. [Step-by-Step Setup](#3-step-by-step-setup)
   - [3a. Configure STAF MCP Server](#3a-configure-staf-mcp-server)
   - [3b. Add MCP Connector](#3b-add-mcp-connector)
   - [3c. Select Tools](#3c-select-tools)
   - [3d. Create SAP Expert Custom Agent](#3d-create-sap-expert-custom-agent)
   - [3e. Upload Skills](#3e-upload-skills)
   - [3f. Create Incident Response Plan (Optional)](#3f-create-incident-response-plan-optional)
   - [3g. Create Scheduled Tasks (Optional)](#3g-create-scheduled-tasks-optional)
4. [Using STAF with SRE Agent](#4-using-staf-with-sre-agent)
5. [Architecture](#5-architecture)
6. [Configuration Reference](#6-configuration-reference)
7. [Troubleshooting](#7-troubleshooting)
8. [Plugin Marketplace](#8-plugin-marketplace)
9. [Limitations](#9-limitations)
10. [Related Documentation](#10-related-documentation)

---

## 1. Prerequisites

| Requirement | Details |
|-------------|---------|
| **STAF deployed** | Docker (`deploy/docker-compose.yml`) or bare-metal install with the MCP server running |
| **Network connectivity** | SRE Agent must reach the STAF MCP server on port **8001** (TCP) |
| **Bearer token** | A shared secret configured on both sides (`MCP_AUTH_MODE=bearer`) |
| **Azure SRE Agent access** | An Azure subscription with SRE Agent enabled and your account granted **Administrator** role |
| **SAP workspaces** | At least one workspace configured under `WORKSPACES/` with valid `hosts.yaml` and `sap-parameters.yaml` |

---

## 2. Quick Start (5 Minutes)

Get a working integration in four steps:

### Step 1 — Deploy STAF with bearer auth

```bash
# In your STAF deployment directory
export MCP_AUTH_MODE=bearer
export MCP_BEARER_TOKEN="your-secure-token-here"   # min 32 characters recommended

cd deploy
docker compose up -d
```

Verify the MCP server is healthy:

```bash
curl -s http://localhost:8001/mcp | jq .
# Expected: {"status": "ok", ...}
```

### Step 2 — Add the MCP connector

1. Open the **Azure SRE Agent portal**.
2. Navigate to **Builder → Connectors → Add MCP Server**.
3. Fill in:
   - **Name:** `staf-mcp`
   - **Transport:** Streamable-HTTP
   - **URL:** `http://<your-staf-host>:8001/mcp`
   - **Authentication:** Bearer token → paste `your-secure-token-here`
4. Click **Test Connection**, then **Save**.

### Step 3 — Select Tier 1 tools

On the connector page, enable these **12 essential tools**:

`list_workspaces` · `get_workspace` · `collect_evidence` ·
`list_evidence_catalog` · `run_analysis` · `get_triage_report` ·
`query_knowledge` · `search_logs` · `run_staf_test` ·
`get_job_status` · `get_job_results` · `list_jobs`

> See [tool-selection-guide.md](sre-agent/tool-selection-guide.md) for the full
> tier breakdown (Tier 1: 12, Tier 2: 20, Tier 3: 26 tools).

### Step 4 — Test the integration

In the SRE Agent chat, type:

```
List my SAP workspaces and summarize their configurations.
```

The agent should call `list_workspaces`, return your configured workspaces, and
describe each system's topology. If this works, the integration is live.

---

## 3. Step-by-Step Setup

### 3a. Configure STAF MCP Server

The MCP server is built into STAF and exposed alongside the Core API. Configure
it with environment variables:

```bash
# Required
export MCP_AUTH_MODE=bearer                        # bearer | apikey | azuread | none
export MCP_BEARER_TOKEN="your-secure-token-here"

# Optional — override defaults
export MCP_PORT=8001                               # default: 8001
export MCP_TRANSPORT=streamable-http               # streamable-http (default) | stdio
export MCP_RATE_LIMIT_RPM=300                      # requests per minute (default: 300)
export MCP_RATE_LIMIT_BURST=50                     # burst allowance (default: 50)
```

**Docker Compose** — the `deploy/docker-compose.yml` already exposes port 8001.
Add the environment variables to the service definition:

```yaml
services:
  staf:
    # ... existing configuration ...
    ports:
      - "8000:8000"   # Core API
      - "8001:8001"   # MCP server
    environment:
      - MCP_AUTH_MODE=bearer
      - MCP_BEARER_TOKEN=${MCP_BEARER_TOKEN}
      - MCP_PORT=8001
```

**Verify health:**

```bash
# From the SRE Agent network (or any host with connectivity)
curl -sf http://<staf-host>:8001/mcp && echo "MCP server healthy"
```

### 3b. Add MCP Connector

Azure SRE Agent supports two transport modes for MCP connectors:

| Mode | When to use |
|------|-------------|
| **Streamable-HTTP** (remote) | STAF runs on a separate VM, container, or AKS cluster |
| **stdio** (local sidecar) | STAF runs as a sidecar process on the SRE Agent host |

**Streamable-HTTP setup (recommended):**

1. Open the Azure portal → **SRE Agent** → **Builder** → **Connectors**.
2. Click **+ Add MCP Server**.
3. Configure:
   | Field | Value |
   |-------|-------|
   | **Name** | `staf-mcp` |
   | **Transport** | Streamable-HTTP |
   | **URL** | `http://<your-staf-host>:8001/mcp` |
   | **Authentication** | Bearer token |
   | **Token** | *(paste your `MCP_BEARER_TOKEN` value)* |
4. Click **Test Connection** — expect a green checkmark.
5. Click **Save**.

The SRE Agent sends a **heartbeat ping every 60 seconds** and automatically
reconnects if the connection drops.

**stdio setup (local sidecar):**

Set `MCP_TRANSPORT=stdio` on the STAF process and configure the connector as a
local command in the SRE Agent builder. Authentication uses Managed Identity
when running as a sidecar.

### 3c. Select Tools

STAF exposes **26 tools**, **4 resources**, and **3 prompts**. Azure SRE Agent
enforces an **80-tool budget** across all connectors, so choose the tier that
fits your remaining budget:

| Tier | Tools | Budget used | Best for |
|------|-------|-------------|----------|
| **Tier 1 — Essential** | 12 | 15% | Most production operations teams |
| **Tier 2 — Standard** | 20 | 25% | Teams needing debugging and feedback loops |
| **Tier 3 — Full** | 26 | 32.5% | Platform engineers managing full lifecycle |

On the connector page in the SRE Agent portal, toggle on the tools for your
chosen tier. The complete tool list with per-tier assignments is in
**[tool-selection-guide.md](sre-agent/tool-selection-guide.md)**.

### 3d. Create SAP Expert Custom Agent

The SAP Expert agent gives SRE Agent deep SAP domain knowledge and structured
investigation workflows. You can create it in two ways:

**Option A — YAML import (recommended):**

1. Open **Builder → Agent Canvas**.
2. Click **Import from YAML**.
3. Upload
   **[`docs/sre-agent/sap-expert-agent.yaml`](sre-agent/sap-expert-agent.yaml)**.
4. Review the imported agent configuration and click **Save**.

**Option B — Portal form:**

1. Open **Builder → Agent Canvas → + New Agent**.
2. Fill in:
   | Field | Value |
   |-------|-------|
   | **Name** | `sap-expert` |
   | **Display name** | SAP Expert |
   | **Description** | Specialized agent for SAP HANA and SCS cluster operations on Azure |
   | **MCP connectors** | `staf-mcp` (select all enabled tools) |
   | **Skills** | `sap-cluster-triage`, `sap-ha-testing` (after uploading — see 3e) |
3. Paste the system prompt from
   [`sap-expert-agent.yaml`](sre-agent/sap-expert-agent.yaml) into the
   **System Instructions** field.
4. Click **Save**.

### 3e. Upload Skills

Skills teach the agent structured procedures for specific task types.

1. Open **Builder → Skills → + Upload Skill**.
2. Upload the triage skill:
   - **File:** [`.github/skills/sap-cluster-triage/SKILL.md`](../.github/skills/sap-cluster-triage/SKILL.md)
   - **Name:** `sap-cluster-triage`
3. Upload the HA testing skill:
   - **File:** [`.github/skills/sap-ha-testing/SKILL.md`](../.github/skills/sap-ha-testing/SKILL.md)
   - **Name:** `sap-ha-testing`
4. Associate both skills with the `sap-expert` agent in **Agent Canvas → Skills**.

| Skill | Purpose |
|-------|---------|
| `sap-cluster-triage` | 6-step investigation procedure: establish context → collect cluster state → parse HANA replication → parse SCS state → cross-layer correlation → report |
| `sap-ha-testing` | Test selection, safety checks, execution, monitoring, and result analysis for 29 HA test scenarios |

### 3f. Create Incident Response Plan (Optional)

An incident response plan routes SAP-related Azure Monitor alerts to the
`sap-expert` agent automatically.

1. Open **Builder → Incident Response Plans → + New Plan**.
2. Import
   **[`docs/sre-agent/incident-response-plan.yaml`](sre-agent/incident-response-plan.yaml)**,
   then customize:
   - Replace `<your-sap-hana-service>`, `<your-sap-scs-service>`, and
     `<your-sap-app-service>` with your actual Azure service names.
   - Replace `<your-teams-channel-webhook>` or `<your-slack-webhook>` with
     real webhook URLs.
3. Review the default settings:
   | Setting | Default | Notes |
   |---------|---------|-------|
   | **Severity filter** | P1, P2 | Extend to P3 if desired |
   | **Autonomy level** | `review` | Agent proposes actions; human approves |
   | **Investigation timeout** | 30 min | Increase for large-scale landscapes |
   | **Reinvestigation cooldown** | 3 hours | Prevents alert-storm loops |
4. Click **Save** and **Enable**.

### 3g. Create Scheduled Tasks (Optional)

Scheduled tasks run proactive checks without human initiation.

Three templates are provided in
**[scheduled-tasks.md](sre-agent/scheduled-tasks.md)**:

| Task | Schedule | Autonomy | Destructive? |
|------|----------|----------|-------------|
| **Daily SAP Health Check** | 08:00 daily | Review | No |
| **Weekly HA Config Validation** | 02:00 Sunday | Review | No |
| **Monthly HA Functional Test** | 02:00 first Sunday | Review (mandatory) | Yes — requires maintenance window |

To create a scheduled task:

1. Open **Builder → Scheduled Tasks → + New Task**.
2. Follow the template in
   [scheduled-tasks.md](sre-agent/scheduled-tasks.md) for cron expressions,
   agent assignment, and action sequences.
3. For the monthly HA functional test, ensure an approved maintenance window
   before enabling.

---

## 4. Using STAF with SRE Agent

### Triage an SAP Cluster Issue

**Example conversation:**

```
User: My SAP HANA cluster on workspace DEV-HANA-01 is showing replication errors.

Agent: I'll investigate the HANA replication issue on DEV-HANA-01. Let me
       gather evidence from the cluster.

       [calls list_workspaces]
       [calls get_workspace(workspace_id="DEV-HANA-01")]
       [calls collect_evidence(workspace_id="DEV-HANA-01",
              collectors=["pacemaker_status", "hana_replication", "system_logs"])]
       [calls run_analysis(workspace_id="DEV-HANA-01")]

Agent: I found 3 critical findings on DEV-HANA-01:

       1. ❌ stonith-enabled is set to FALSE — fencing is disabled
       2. ❌ HANA system replication state is SFAIL on node hana-vm-02
       3. ⚠️  Corosync token timeout is 5000ms (recommended: 30000ms for Azure)

       Recommended actions:
       - Immediately enable STONITH (required for supported HA configuration)
       - Investigate SFAIL state: check /var/log/messages around 14:32 UTC
         for indexserver crash signatures
       - Increase corosync token timeout to 30000ms per SAP Note 2002167

       Shall I run the ha-config validation test for a comprehensive check?
```

The agent follows the 6-step triage procedure defined in the
`sap-cluster-triage` skill, correlating SAP-layer evidence with Azure platform
signals (VM health events, disk latency, network connectivity).

### Run HA Functional Tests

```
User: Run the non-destructive HA tests on workspace PROD-HANA-01.

Agent: I'll run the safe (non-destructive) test cases on PROD-HANA-01:
       ha-config, ha-config-offline, and azure-lb.

       [calls run_staf_test(workspace_id="PROD-HANA-01",
              test_type="ha_test",
              test_group="DatabaseHighAvailability",
              test_cases=["ha-config", "ha-config-offline", "azure-lb"])]
       [calls get_job_status(job_id="job-abc123") — polls until complete]
       [calls get_job_results(job_id="job-abc123")]

Agent: All 3 tests completed on PROD-HANA-01:

       ✅ ha-config — PASSED (47 checks, 0 failures)
       ✅ ha-config-offline — PASSED (12 checks, 0 failures)
       ⚠️  azure-lb — PASSED WITH WARNINGS
           - Health probe port 62503 responding, but probe interval
             is 15s (recommended: 5s)

       No destructive tests were run. To test failover scenarios like
       primary-node-crash or resource-migration, confirm a maintenance
       window first.
```

### Correlate Azure + SAP Evidence

The SAP Expert agent can combine Azure Monitor data (built-in SRE Agent
capability) with STAF's SAP-specific evidence:

```
User: VM hana-primary-vm had a host maintenance event at 03:15 UTC.
      Did the SAP HANA cluster survive?

Agent: I'll cross-reference the Azure platform event with SAP cluster state.

       [Azure built-in: queries Azure Activity Log for hana-primary-vm]
       [calls collect_evidence(workspace_id="PROD-HANA-01",
              collectors=["pacemaker_status", "hana_replication"])]
       [calls search_logs(workspace_id="PROD-HANA-01",
              time_range="03:00-04:00", patterns=["takeover", "failover"])]

Agent: Timeline of events:

       03:15:00 — Azure: Planned maintenance started on hana-primary-vm
       03:15:12 — Pacemaker: Detected node hana-primary-vm UNCLEAN
       03:15:14 — SBD: Fencing triggered for hana-primary-vm
       03:15:18 — Pacemaker: Promoted hana-secondary-vm to primary
       03:15:22 — HANA: SR takeover completed (SOK state)
       03:17:45 — Azure: hana-primary-vm back online
       03:18:30 — HANA: hana-primary-vm re-registered as secondary

       ✅ The cluster survived the maintenance event. Failover completed
       in 8 seconds and full replication was restored within 3 minutes.
```

---

## 5. Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                     Azure SRE Agent                          │
│                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────┐  │
│  │  SRE Agent   │  │  SAP Expert  │  │  Incident Response │  │
│  │  (built-in)  │  │  (custom)    │  │  Plan / Schedules  │  │
│  └──────┬───────┘  └──────┬───────┘  └────────┬──────────┘  │
│         │                 │                    │              │
│         ▼                 ▼                    ▼              │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │              MCP Connector: staf-mcp                    │ │
│  │  Transport: Streamable-HTTP  │  Auth: Bearer token      │ │
│  │  Heartbeat: 60s              │  Tools: 12–26 (tiered)   │ │
│  └──────────────────────┬──────────────────────────────────┘ │
└─────────────────────────┼────────────────────────────────────┘
                          │ HTTPS / port 8001
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                  STAF MCP Server                             │
│                                                              │
│  26 tools  │  4 resources  │  3 prompts                      │
│  Rate limit: 300 RPM / 50 burst                              │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐  │
│  │              STAF Core API (port 8000)                 │  │
│  │                                                        │  │
│  │  Jobs  │  Schedules  │  Workspaces  │  Telemetry       │  │
│  └────────────────────────┬───────────────────────────────┘  │
└───────────────────────────┼──────────────────────────────────┘
                            │ SSH / Ansible
                            ▼
┌──────────────────────────────────────────────────────────────┐
│                    SAP Cluster Nodes                          │
│                                                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐    │
│  │  HANA     │  │  HANA     │  │  ASCS     │  │  ERS      │  │
│  │  Primary  │  │  Secondary │  │  Node     │  │  Node     │  │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘    │
│                                                              │
│  Pacemaker + Corosync + SBD  │  SUSE or RHEL                │
└──────────────────────────────────────────────────────────────┘
```

**Data flow:**

1. User (or incident/schedule) triggers the SRE Agent.
2. SRE Agent routes to the `sap-expert` custom agent if SAP keywords are
   detected.
3. The custom agent calls STAF tools via the MCP connector.
4. The MCP server translates tool calls into STAF Core API requests.
5. The Core API executes Ansible playbooks against SAP cluster nodes over SSH.
6. Results flow back through the same path to the user.

---

## 6. Configuration Reference

### STAF MCP Server Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `MCP_AUTH_MODE` | Yes | `none` | Authentication mode: `bearer`, `apikey`, `azuread`, `none` |
| `MCP_BEARER_TOKEN` | If bearer | — | Shared secret for bearer token auth |
| `MCP_API_KEY` | If apikey | — | API key for apikey auth |
| `AZURE_TENANT_ID` | If azuread | — | Azure AD tenant ID |
| `AZURE_CLIENT_ID` | If azuread | — | Azure AD application (client) ID |
| `MCP_PORT` | No | `8001` | Port the MCP server listens on |
| `MCP_TRANSPORT` | No | `streamable-http` | Transport mode: `streamable-http` or `stdio` |
| `MCP_RATE_LIMIT_RPM` | No | `300` | Maximum requests per minute |
| `MCP_RATE_LIMIT_BURST` | No | `50` | Burst request allowance |

### SRE Agent Connector Settings

| Setting | Value |
|---------|-------|
| **Connector name** | `staf-mcp` |
| **Transport** | Streamable-HTTP |
| **URL** | `http://<staf-host>:8001/mcp` |
| **Auth type** | Bearer token |
| **Heartbeat interval** | 60 seconds (managed by SRE Agent) |
| **Auto-reconnect** | Yes |

---

## 7. Troubleshooting

### Connection Failed

**Symptom:** SRE Agent connector shows "Connection failed" or "Unreachable".

| Check | Command / Action |
|-------|-----------------|
| MCP server running? | `curl -sf http://<staf-host>:8001/mcp` |
| Port open? | `nc -zv <staf-host> 8001` |
| Firewall / NSG? | Verify Azure NSG allows inbound TCP 8001 from SRE Agent IPs |
| Docker container up? | `docker compose ps` — check staf service is `Up` |

### Authentication Errors

**Symptom:** `401 Unauthorized` or `403 Forbidden` on tool calls.

- Verify `MCP_AUTH_MODE` matches the connector configuration in SRE Agent.
- Confirm the bearer token values are identical on both sides (no trailing
  whitespace).
- For Azure AD auth, check that `AZURE_TENANT_ID` and `AZURE_CLIENT_ID` are
  correct and the service principal has the required permissions.

### Tool Calls Failing

**Symptom:** Agent says "tool execution failed" or returns empty results.

- Check the STAF Core API is healthy: `curl -sf http://<staf-host>:8000/healthz`
- Review STAF logs: `docker compose logs staf --tail=100`
- Verify the workspace exists and SSH connectivity is configured:
  `ls WORKSPACES/<workspace-id>/hosts.yaml`

### Rate Limiting

**Symptom:** `429 Too Many Requests` responses.

- Default: 300 RPM / 50 burst. Increase via `MCP_RATE_LIMIT_RPM` and
  `MCP_RATE_LIMIT_BURST` if needed.
- Large-scale triage across many workspaces can spike request volume.

### Core API Down, MCP Server Up

**Symptom:** MCP health check passes but tool calls return errors.

- The MCP server and Core API are separate processes. Restart the Core API:
  `docker compose restart staf`
- Check Core API port 8000 independently:
  `curl -sf http://<staf-host>:8000/healthz`

---

## 8. Plugin Marketplace

STAF publishes a plugin manifest at
[`.github/plugin/marketplace.json`](../.github/plugin/marketplace.json) for
one-click installation in environments that support the SRE Agent plugin
marketplace.

**One-click install:**

1. Open **SRE Agent → Marketplace**.
2. Search for **SAP Testing Automation Framework**.
3. Click **Install** — this auto-configures:
   - The MCP connector (you still provide the URL and token)
   - Both skills (`sap-cluster-triage`, `sap-ha-testing`)
4. Complete the setup by entering your STAF MCP URL and bearer token.

**Manual setup** — follow [Step-by-Step Setup](#3-step-by-step-setup) above.

The marketplace manifest defines two plugins:

| Plugin | Description |
|--------|-------------|
| `sap-cluster-triage` | Automated triage for SAP cluster incidents |
| `sap-ha-testing` | On-demand and scheduled HA functional testing |

---

## 9. Limitations

| Limitation | Impact | Mitigation |
|------------|--------|------------|
| **Polling-based job monitoring** | Agent polls `get_job_status` until completion; no push notifications | Jobs include estimated duration; agent adjusts poll interval |
| **80-tool budget** | STAF's full 26 tools consume 32.5% of the budget | Use Tier 1 (12 tools / 15%) for most teams; see [tool-selection-guide.md](sre-agent/tool-selection-guide.md) |
| **Bearer token auth only (remote)** | Managed identity is supported only for stdio (sidecar) transport | Rotate tokens regularly; use Azure Key Vault to store the token |
| **No streaming output** | Long-running Ansible jobs don't stream real-time output to the agent | Use `get_job_log` and `get_job_events` for incremental progress |
| **Destructive tests require human approval** | HA failover tests (e.g., `primary-node-crash`) need maintenance windows | Incident response plans default to `review` autonomy level |
| **Single-workspace locking** | Only one job per workspace at a time | Agent queues or skips if workspace is busy |

---

## 10. Related Documentation

### STAF Documentation

| Document | Description |
|----------|-------------|
| [STAF Overview](STAF.md) | Framework overview, test scenarios, and CLI usage |
| [Architecture](ARCHITECTURE.md) | System architecture and design patterns |
| [High Availability](HIGH_AVAILABILITY.md) | HA test scenarios and cluster configurations |
| [Configuration Checks](CONFIGURATION_CHECKS.md) | Configuration validation reference |
| [Telemetry Setup](TELEMETRY_SETUP.md) | Azure Log Analytics and ADX telemetry |
| [Scheduling](SCHEDULE.md) | Cron-based job scheduling |
| [Changelog](CHANGELOG.md) | Version history |

### SRE Agent Integration Files

| File | Description |
|------|-------------|
| [`sre-agent/sap-expert-agent.yaml`](sre-agent/sap-expert-agent.yaml) | SAP Expert custom agent definition (importable YAML) |
| [`.github/skills/sap-cluster-triage/SKILL.md`](../.github/skills/sap-cluster-triage/SKILL.md) | Cluster triage skill (6-step procedure) |
| [`.github/skills/sap-ha-testing/SKILL.md`](../.github/skills/sap-ha-testing/SKILL.md) | HA testing skill (29 test scenarios) |
| [`sre-agent/tool-selection-guide.md`](sre-agent/tool-selection-guide.md) | Tool budget guide (3 tiers: 12 / 20 / 26) |
| [`sre-agent/incident-response-plan.yaml`](sre-agent/incident-response-plan.yaml) | Incident response plan template |
| [`sre-agent/scheduled-tasks.md`](sre-agent/scheduled-tasks.md) | Scheduled task templates (daily, weekly, monthly) |
| [`.github/plugin/marketplace.json`](../.github/plugin/marketplace.json) | Plugin marketplace manifest |
