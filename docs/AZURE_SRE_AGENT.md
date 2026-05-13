# Integrating STAF with Azure SRE Agent

This document describes an alternative way to use SAP Testing Automation Framework — through
[Azure SRE Agent](https://learn.microsoft.com/en-us/azure/sre-agent/) and the
Model Context Protocol (MCP). This integration adds AI-driven troubleshooting,
conversational test execution, and knowledge retrieval on top of STAF's
existing capabilities.

> **Note:** Direct execution from a management server remains fully supported. See
> [SETUP.MD](SETUP.MD) for the standard deployment guide. The SRE Agent
> integration described here is an additional deployment option that runs
> the STAF MCP server as a containerized service in Azure.

## Overview

Azure SRE Agent provides built-in capabilities for Azure infrastructure
monitoring, incident response, and root cause analysis. However, it has no
native awareness of SAP application-layer state — HANA System Replication
status, Pacemaker cluster health, SCS/ERS failover behavior, or SAP-specific
configuration parameters.

STAF bridges this gap by exposing **23 MCP tools** that give Azure SRE Agent
the ability to:

- **Discover SAP systems** — list configured workspaces with SID, topology,
  platform, and host details.
- **Analyze against SAP best practices** — provide collected evidence and
  applicable rules to the LLM for reasoning about cluster properties,
  resource configuration, fencing, load balancer setup, and replication state.
- **Execute HA functional tests** — run 15 HANA and 14 SCS test scenarios
  including resource migration, node crash, indexserver kill, network
  isolation, and filesystem freeze.
- **Collect cluster evidence** — gather Pacemaker CIB, corosync ring status,
  HANA SR attributes, SBD device state, and system logs via SSH.
- **Manage test schedules** — create, update, and trigger recurring test executions.

The integration uses the **Streamable-HTTP** MCP transport with **Bearer token
authentication**. STAF runs as a containerized service (Azure Container Apps)
and stores workspace configurations in Azure Blob Storage using managed
identity for authentication.

---

## Prerequisites

- Azure SRE Agent configured in Azure (using SRE Agent Administrator role)
- Azure Key Vault for SAP environment SSH credentials
- Azure Blob Storage account for workspace configurations
- Azure Container Apps
  - Azure Container Apps environment
    - **VNet integration required** — the Container App must be deployed in a
      VNet that can reach your SAP hosts over SSH (port 22). Configure NSG
      rules to allow outbound SSH from the Container App subnet to the SAP
      subnet. Without this, all evidence collection and test execution will fail.
    - System-assigned or user-assigned managed identity with:
      - `Key Vault Secrets User` on the SSH credentials Key Vault
      - `Storage Blob Data Contributor` on the workspace storage account
      - `Storage Table Data Contributor` on the storage account (if using
        Azure Table Storage for job/schedule persistence)
  - Azure Container App for running the STAF MCP server

---

## Step 1. Configure Cloud Workspaces

Same as the classic execution using management server, [workspace](./SETUP.MD) represents a system
which includes configuration files specific to your SAP system. Each workspace represents one SAP
landscape (SID) and consists of two files:
`hosts.yaml` (Ansible inventory with host IPs, SSH users, and node tiers) and
`sap-parameters.yaml` (SAP system attributes including SID, platform, instance
numbers, HA configuration, and topology).

### Upload to Azure Blob Storage

Create a blob container (e.g. `workspaces`) in your storage account and upload
workspace files via **Azure Portal → Storage Browser** (drag-and-drop) or CLI.

If you already have workspaces configured on a management server, you can
upload the existing `WORKSPACES/SYSTEM` directory as-is. Ensure the *Storage Blob Data Contributor*
role assignement exists for the managed identity of the Management server to access the blob storage.

```bash
az storage blob upload-batch -s ./WORKSPACES/SYSTEM -d workspaces \
  --account-name <storage-account>
```

Expected blob structure:

```
workspaces/
├── DEV-HANA-01
    ├── hosts.yaml
    └── sap-parameters.yaml
└── PROD-SCS-01
    ├── hosts.yaml
    └── sap-parameters.yaml
```

### SSH Credentials

Store SSH private keys or passwords in **Azure Key Vault**. Add the Key Vault
secret URL to `sap-parameters.yaml`:

```yaml
secret_id: "https://your-keyvault.vault.azure.net/secrets/ssh-private-key"
user_assigned_identity_client_id: "00000000-0000-0000-0000-000000000000"  # optional
```

**Do not store SSH keys in Blob Storage.** The Container App's managed identity
must have `Get` permission on Key Vault secrets.

---

## Step 2. Create Azure Container App

1. Navigate to the **Azure Portal → Container Apps → Create**.
2. Configure the following settings:

   | Setting | Value |
   |---------|-------|
   | **Name** | `staf-mcp` |
   | **Region** | Same region as your SAP infrastructure |
   | **Container Apps Environment** | Create new or select existing |
   | **Ingress** | Enabled — accepting traffic from anywhere |
   | **Ingress type** | HTTP |
   | **Target port** | `8001` |

3. Under **Identity**, enable a managed identity:
   - **System-assigned** — enable the toggle under the System assigned tab, or
   - **User-assigned** — create or select an existing user-assigned managed
     identity under the User assigned tab.

4. After creation, assign the following roles to the managed identity (system-assigned
   or user-assigned):

   | Resource | Role | Purpose |
   |----------|------|---------|
   | Blob Storage account | `Storage Blob Data Contributor` | Read workspace configurations |
   | Azure Key Vault | `Key Vault Secrets User` | Retrieve SSH credentials |

---

## Step 3. Deploy the MCP Server

Deploy the STAF MCP server from the repository root:

```bash
az containerapp up \
  --name staf-mcp \
  --source . \
  --ingress external \
  --target-port 8001 \
  --env-vars \
    MCP_AUTH_MODE=bearer \
    MCP_BEARER_TOKEN=<your-secret-token> \
    PYTHONPATH=/app \
    DATA_DIR=/app/data \
    KNOWLEDGE_SEED_DIR=/app/src/core/knowledge/seed \
    BLOB_ACCOUNT_URL=https://<storage-account>.blob.core.windows.net \
    BLOB_CONTAINER_NAME=workspaces
```

Generate a bearer token: `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`

---

## Step 4. Connect to SRE Agent

1. Open the Azure SRE Agent portal.
2. Navigate to **Builder → Connectors → Add MCP Server**.
3. Configure the connection:

   | Field | Value |
   |-------|-------|
   | **Name** | `staf-mcp` |
   | **Connection type** | Streamable-HTTP |
   | **URL** | `https://<your-container-app>.azurecontainerapps.io/mcp` |
   | **Authentication** | Bearer token |
   | **Token** | Same value as `MCP_BEARER_TOKEN` |

4. Select tools — see [tool-selection-guide.md](sre-agent/tool-selection-guide.md)
   for tier recommendations (11 essential / 18 standard / 23 full).
5. Test the connection by asking `"List my SAP workspaces"` in SRE Agent chat.

---

## Step 5. Upload Skills (Optional)

Skills provide structured procedures that the SRE Agent follows during
investigation and testing. Upload to **Builder → Skills**:

| File | Skill Name |
|------|------------|
| [`.github/skills/sap-cluster-triage/SKILL.md`](../.github/skills/sap-cluster-triage/SKILL.md) | `sap-cluster-triage` |
| [`.github/skills/sap-ha-testing/SKILL.md`](../.github/skills/sap-ha-testing/SKILL.md) | `sap-ha-testing` |

---

## Step 6. Create Custom Agent (Optional)

Import [`docs/sre-agent/sap-expert-agent.yaml`](sre-agent/sap-expert-agent.yaml)
in **Builder → Agent Canvas → Create Custom Agent** (YAML editor). This creates
an SAP domain expert with structured investigation and HA testing workflows.
The agent references MCP tools via `staf-mcp/*` — update the connection-id
if your connector has a different name.

---

## Available Tools

### Workspace (2)

| Tool | Description |
|------|-------------|
| `list_workspaces` | List SAP system workspaces |
| `get_workspace` | Get workspace details (SID, platform, topology, hosts) |

### Triage — Evidence (5)

| Tool | Description |
|------|-------------|
| `list_evidence_catalog` | List evidence collectors by category |
| `collect_evidence` | Gather cluster evidence via SSH |
| `run_evidence_collector` | Run a single collector on a specific host |
| `get_evidence_output` | Read raw output of a collected artifact |
| `search_logs` | Search SAP host logs with time-window and pattern filtering |

### Triage — Analysis (1)

| Tool | Description |
|------|-------------|
| `get_analysis_context` | Get evidence and applicable rules for LLM reasoning |

### Knowledge (1)

| Tool | Description |
|------|-------------|
| `query_knowledge` | Search rules, playbooks, and learned patterns |

### Test Execution (7)

| Tool | Description |
|------|-------------|
| `run_staf_test` | Execute HA functional tests |
| `get_job_status` | Poll job status |
| `get_job_results` | Get completed job results |
| `list_jobs` | List jobs with filters |
| `get_job_log` | Retrieve Ansible execution log |
| `get_job_events` | Get ordered job event log |
| `cancel_job` | Cancel a running job |

### Scheduling (7)

| Tool | Description |
|------|-------------|
| `create_schedule` | Create a cron schedule |
| `list_schedules` | List all schedules |
| `get_schedule` | Get schedule details |
| `update_schedule` | Update a schedule |
| `delete_schedule` | Delete a schedule |
| `trigger_schedule` | Trigger a schedule immediately |
| `get_schedule_jobs` | Get jobs triggered by a schedule |

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| **Connector shows "Disconnected"** | Verify the MCP server is running and reachable. Check `az containerapp logs show`. |
| **401 Unauthorized** | `MCP_BEARER_TOKEN` must match exactly between Container App env var and SRE Agent connector. |
| **Empty workspace list** | Verify `BLOB_ACCOUNT_URL` is set, blob container has workspace files, and managed identity has `Storage Blob Data Contributor`. |
| **Job creation fails** | `run_staf_test` requires the STAF Core API (`CORE_API_URL`). Not available in MCP-only deployments — use triage tools instead. |
| **SSH provisioning fails** | Verify `secret_id` in `sap-parameters.yaml` points to a valid Key Vault secret and the managed identity has `Get` permission. |
| **429 Too Many Requests** | Increase `MCP_RATE_LIMIT_RPM` (default: 60) and `MCP_RATE_LIMIT_BURST` (default: 10). |
