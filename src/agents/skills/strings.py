# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Skill strings — all user-facing text for SAP agent skills.

Edit this file to customize skill names, descriptions, and instructions.
No Python knowledge required — just edit the text between the triple quotes.
Each constant is referenced by a skill module in this package.
"""

# ──────────────────────────────────────────────────────────────────
# SAP Triage Skill
# ──────────────────────────────────────────────────────────────────

TRIAGE_NAME = "sap-triage"

TRIAGE_DESCRIPTION = (
    "Investigate SAP system health issues. Use when asked to diagnose, "
    "troubleshoot, or check the health of an SAP HANA or SCS cluster. "
    "Collects evidence from cluster nodes via SSH, analyzes against "
    "400+ SAP-specific rules, and produces a structured diagnosis."
)

TRIAGE_INSTRUCTIONS = """\
## SAP System Triage

Use this skill to investigate SAP system health issues on Azure.

### Steps
1. Read the `workspaces` resource to find the target SAP system.
2. Optionally read `evidence-catalog` to see available evidence collectors.
3. Call the `investigate` script with `workspace_id` and a description
   of the problem. The script runs a **complete investigation** —
   evidence collection, rule-based analysis, and diagnosis — in one call.

### When to use
- User reports cluster issues, failover problems, or node crashes
- Health check or configuration review requests
- Any "what's wrong with my SAP system" question
- Proactive health assessment before maintenance windows

### What the investigate script does internally
1. Loads workspace configuration and validates SSH credentials.
2. Selects evidence collectors appropriate for the system topology
   (Scale-Up, Scale-Out HSR, Scale-Out Standby).
3. Collects evidence from all cluster nodes via SSH.
4. Analyzes collected evidence against 400+ SAP-specific rules.
5. Returns a structured JSON report with findings, severity, and
   remediation steps.
"""

TRIAGE_RES_WORKSPACES_NAME = "workspaces"
TRIAGE_RES_WORKSPACES_DESC = (
    "Available SAP system workspaces with SID, environment, and host details."
)

TRIAGE_RES_EVIDENCE_CATALOG_NAME = "evidence-catalog"
TRIAGE_RES_EVIDENCE_CATALOG_DESC = (
    "Evidence collectors available for investigation — IDs, descriptions, "
    "commands, and tags. Use to understand what data can be collected."
)

TRIAGE_SCRIPT_INVESTIGATE_NAME = "investigate"
TRIAGE_SCRIPT_INVESTIGATE_DESC = (
    "Run a full triage investigation on an SAP system. Collects evidence "
    "via SSH, analyzes against 400+ rules, and returns a structured JSON "
    "diagnosis with findings, severity, and remediation steps."
)

# ──────────────────────────────────────────────────────────────────
# STAF Test Skill
# ──────────────────────────────────────────────────────────────────

STAF_NAME = "sap-staf-test"

STAF_DESCRIPTION = (
    "Run SAP HA functional tests (STAF). Use when asked to execute "
    "configuration checks, database HA tests, or SCS HA tests. "
    "Manages the full test lifecycle: submit, poll, and fetch results."
)

STAF_INSTRUCTIONS = """\
## STAF Test Execution

Use this skill to run SAP HA functional tests on Azure.

### Steps
1. Read the `test-catalog` resource to see available test groups and
   individual test cases.
2. Call the `run_test` script with `workspace_id`, `test_group`, and
   optionally specific `test_ids`. The script manages the entire test
   lifecycle in one call.

### Test Groups
- **ConfigurationChecks** — Validate system configuration (HANA, Db2,
  SCS, application instances).
- **DatabaseHighAvailability** — HANA HA functional tests (failover,
  crash recovery, network isolation, fencing).
- **SCSHighAvailability** — Central Services HA functional tests (ASCS
  migration, process kill, network isolation).

### What the run_test script does internally
1. Validates workspace connectivity and configuration.
2. Submits the test job to the execution engine.
3. Polls job status until completion (with timeout).
4. Retrieves test results and execution log.
5. Returns structured JSON with pass/fail per test case, duration,
   and log excerpts for failures.
"""

STAF_RES_TEST_CATALOG_NAME = "test-catalog"
STAF_RES_TEST_CATALOG_DESC = (
    "Available test groups and individual test cases. Each entry shows "
    "the test ID, description, test group, and whether it is destructive."
)

STAF_SCRIPT_RUN_TEST_NAME = "run_test"
STAF_SCRIPT_RUN_TEST_DESC = (
    "Execute a STAF test end-to-end. Submits the job, polls until "
    "complete, and returns structured JSON results with pass/fail per "
    "test case, duration, and log excerpts for failures."
)

# ──────────────────────────────────────────────────────────────────
# Project Info Skill
# ──────────────────────────────────────────────────────────────────

PROJECT_INFO_NAME = "project-info"

PROJECT_INFO_DESCRIPTION = (
    "Information about the SAP Testing Automation Framework (STAF). "
    "Use when asked about supported tests, framework architecture, "
    "configuration options, or deployment setup."
)

PROJECT_INFO_INSTRUCTIONS = """\
## SAP Testing Automation Framework

Use this skill for questions about the framework itself — what it does,
how it works, what tests are available, and how to configure or deploy it.

### Resources
- `architecture` — High-level architecture and technology stack.
- `ha-test-scenarios` — Full catalog of HA test scenarios for HANA DB
  and SAP Central Services.
- `configuration` — Configuration parameters and environment variables.
- `deployment` — Docker deployment and setup instructions.
"""

PROJECT_INFO_RES_ARCHITECTURE_NAME = "architecture"
PROJECT_INFO_RES_ARCHITECTURE_DESC = (
    "Framework architecture: technology stack, design patterns, and component overview."
)

PROJECT_INFO_RES_SCENARIOS_NAME = "ha-test-scenarios"
PROJECT_INFO_RES_SCENARIOS_DESC = (
    "Full catalog of HA test scenarios for HANA Database and SAP Central Services."
)

PROJECT_INFO_RES_CONFIG_NAME = "configuration"
PROJECT_INFO_RES_CONFIG_DESC = (
    "Configuration parameters, environment variables, and workspace structure."
)

PROJECT_INFO_RES_DEPLOYMENT_NAME = "deployment"
PROJECT_INFO_RES_DEPLOYMENT_DESC = "Docker deployment instructions and local setup guide."

# ──────────────────────────────────────────────────────────────────
# Project Info Resource Content (static)
# ──────────────────────────────────────────────────────────────────

PROJECT_INFO_ARCHITECTURE_CONTENT = """\
# SAP Testing Automation Framework — Architecture

## Technology Stack
| Layer | Technologies |
|-------|-------------|
| Language | Python 3.10+ (Docker uses 3.12) |
| API | FastAPI, uvicorn, Pydantic v2 |
| Automation | Ansible-core 2.17, ansible-runner 2.4, Jinja2 |
| Azure | azure-identity, azure-keyvault-secrets, azure-kusto-data/ingest |
| Scheduling | APScheduler (CronTrigger) |
| Persistence | SQLite (WAL mode), file-based log/artifact storage |
| Frontend | React (port 3000, in development) |
| Testing | pytest, pytest-asyncio, pytest-cov, pytest-mock, httpx |
| Container | Azure Linux 3.12 base, multi-stage Docker build, non-root user |
| Target OS | SUSE (crm commands) and RHEL (pcs commands) |

## Components
- **API Layer** (`src/api/`) — FastAPI routes for jobs, schedules, workspaces.
- **Core** (`src/core/`) — Execution engine, job worker, storage, observability.
- **MCP Server** (`src/mcp_server/`) — Model Context Protocol tools for agent use.
- **Agent** (`src/agents/`) — LLM agent with intent classification and handoff.
- **Ansible** (`src/roles/`, `src/modules/`) — HA test playbooks and custom modules.
- **CLI** (`scripts/`) — Shell entrypoint for direct and API-driven workflows.
"""

PROJECT_INFO_HA_SCENARIOS_CONTENT = """\
# HA Test Scenarios

## HANA Database HA (ha_db_hana)
| Scenario | Test ID | Destructive |
|----------|---------|-------------|
| HA configuration validation | ha-config | No |
| HA configuration (offline) | ha-config-offline | No |
| Azure Load Balancer validation | azure-lb | No |
| Resource migration | resource-migration | Yes |
| Primary node crash | primary-node-crash | Yes |
| Primary node kill | primary-node-kill | Yes |
| Primary indexserver crash | primary-crash-index | Yes |
| Primary echo-b | primary-echo-b | Yes |
| Secondary node kill | secondary-node-kill | Yes |
| Secondary indexserver crash | secondary-crash-index | Yes |
| Secondary echo-b | secondary-echo-b | Yes |
| Network isolation | block-network | Yes |
| HANA-shared isolation | block-hana-shared | Yes |
| Filesystem freeze (ANF) | fs-freeze | Yes |
| SBD fencing | sbd-fencing | Yes |

## SAP Central Services HA (ha_scs)
| Scenario | Test ID | Destructive |
|----------|---------|-------------|
| HA configuration validation | ha-config | No |
| HA configuration (offline) | ha-config-offline | No |
| Azure Load Balancer validation | azure-lb | No |
| SAP control validation | sapcontrol-config | No |
| ASCS migration | ascs-migration | Yes |
| ASCS node crash | ascs-node-crash | Yes |
| Kill message server | kill-message-server | Yes |
| Kill enqueue server | kill-enqueue-server | Yes |
| Kill enqueue replication | kill-enqueue-replication | Yes |
| Kill SAPStartSrv process | kill-sapstartsrv-process | Yes |
| Manual restart | manual-restart | Yes |
| Failover to node | ha-failover-to-node | Yes |
| Network isolation | block-network | Yes |

## Supported Topologies
- **Scale-Up** — Classic two-node HSR (default).
- **Scale-Out HSR** — Multi-node with system replication.
- **Scale-Out Standby** — Multi-node with standby nodes.
"""

PROJECT_INFO_CONFIGURATION_CONTENT = """\
# Configuration

## Workspace Structure
Each SAP system is a workspace under `WORKSPACES/SYSTEM/<system-name>/`:
- `sap-parameters.yaml` — SAP system parameters (SID, instance numbers, etc.)
- `hosts.yaml` — Ansible inventory with host IPs and roles.
- SSH credentials (key files or Key Vault references).

## Key Parameters (vars.yaml / sap-parameters.yaml)
| Parameter | Description |
|-----------|-------------|
| TEST_TYPE | SAPFunctionalTests or ConfigurationChecks |
| SAP_FUNCTIONAL_TEST_TYPE | DatabaseHighAvailability, CentralServicesHighAvailability, AzureBackupDatabase |
| SYSTEM_CONFIG_NAME | Name of the SAP system workspace directory |
| AUTHENTICATION_TYPE | VMPASSWORD or SSHKEY |
| telemetry_data_destination | azureloganalytics or azuredataexplorer |

## Environment Variables
| Variable | Description | Default |
|----------|-------------|---------|
| MCP_PORT | MCP server port | 8001 |
| CORE_API_URL | Core API base URL | http://localhost:8000 |
| WORKSPACES_BASE | Workspace root directory | WORKSPACES/SYSTEM |
| DATA_DIR | Data storage directory | data |
| CORS_ORIGINS | Allowed CORS origins | — |
"""

PROJECT_INFO_DEPLOYMENT_CONTENT = """\
# Deployment

## Docker (recommended)
```bash
cd deploy && docker compose up -d
```
The Docker image uses Azure Linux 3.12 with a non-root user (appuser:1000).
SQLite data is persisted via a named volume. Workspaces are bind-mounted.

## Local Development
```bash
# Setup Python environment
./scripts/setup.sh

# Start backend API (port 8000)
PYTHONPATH=src uvicorn api.app:app --reload --host 0.0.0.0 --port 8000

# Start MCP server (port 8001) — auto-started by the API

# Start frontend (port 3000)
cd client && npm start
```

## CLI Usage
```bash
# Run tests directly via CLI
./scripts/sap_automation_qa.sh --test_groups DatabaseHighAvailability --test_cases ha-config

# Use API mode
./scripts/sap_automation_qa.sh api start
./scripts/sap_automation_qa.sh api job create --workspace DEV-WEEU-SAP01-X00 --test-group ConfigurationChecks
```
"""
