# Design Document: RCA Framework for SAP Incident Triage

> **Status**: Draft
> **Version**: 0.4
> **Date**: 2026-03-20
> **Authors**: SAP Automation QA Team
> **License**: MIT (Microsoft Corporation)

---

## Table of Contents

1. [Problem & Scope](#1-problem--scope)
2. [Architecture](#2-architecture)
3. Execution Control Plane *(planned)*
4. [MCP Server Design](#4-mcp-server-design)
5. Agent Architecture *(planned)*
6. Analyzer & Triage Engine *(planned)*
7. [Knowledge Model](#7-knowledge-model)
8. Security Model *(planned)*
9. CLI & UI Design *(planned)*
10. Deployment & Packaging *(planned)*
11. Integration with Existing STAF *(planned)*
12. Open Questions & Trade-offs *(planned)*

---

## 1. Problem & Scope

### 1.1 Why This Exists

STAF knows how SAP systems on Azure are expected to behave. These expectations exist today in Ansible roles, Python modules, and templates and are used primarily during pre‑deployment validation.
In production incidents, however, operators must manually re‑derive those expectations from logs, cluster state, OS configuration, and Azure metadata. This leads to slow, inconsistent, and error‑prone incident triage.
This design reuses existing STAF expectations for production incident triage by:

- Collecting evidence from running systems
- Comparing actual behavior against known‑good expectations
- Producing deterministic, auditable root‑cause analysis (RCA)

The goal is explainable triage, not autonomous remediation.

### 1.2 Scope

- Read‑only evidence collection from SAP systems
- Deterministic analysis using rules and playbooks
- MCP server exposing SAP triage capabilities
- Integration with Azure SRE Agent and Azure MCP Server
- Structured knowledge model with controlled self‑learning
- Deployment on the existing STAF management server

**Out of scope:** Modifying SAP systems (no writes, restarts, or config
changes).

## 2. Architecture

### 2.1 Deployment Topology

```
Management Server / Jump Box
(Customer VNet)

┌────────────────────────────────────────────────────────────────┐
│                                                                │
│  ┌───────────────────┐     ┌────────────────────────────────┐ │
│  │ FastAPI  :8000     │     │ MCP Server  :8001 (FastMCP)    │ │
│  │ REST API           │     │ Streamable HTTP transport      │◄┼── Azure SRE Agent
│  │ /api/v1/*          │     │                                │ │
│  └──────┬─────────────┘     │  Tools:  collect_evidence,     │ │
│         │                   │    run_analysis, query_knowledge│ │
│         │                   │    get_triage_report,           │ │
│         │                   │    run_staf_test, get_job_status│ │
│         │                   │    get_job_results,             │ │
│         │                   │    list_workspaces              │ │
│         │                   │  Resources: workspace config,   │ │
│         │                   │    knowledge, hosts, job results│ │
│         │                   │  Prompts: triage, HA test,      │ │
│         │                   │    config check                 │ │
│         │                   └──────────┬─────────────────────┘ │
│         │                              │                       │
│         ▼                              ▼                       │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ Execution Control Plane                                  │  │
│  │ (jobs, workspaces, locking, artifacts)                   │  │
│  └──────────────┬───────────────────────────────────────────┘  │
│                 ▼                                              │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ Triage Executor (SSH, read‑only)                         │  │
│  └──────────────┬───────────────────────────────────────────┘  │
│                 ▼                                              │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ Analyzer (artifacts → findings)                          │  │
│  └──────────────┬───────────────────────────────────────────┘  │
│                 ▼                                              │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ Knowledge Store (JSONL seed + SQLite runtime)            │  │
│  └──────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────┘

SSH (key‑based)
        ▼
SAP Systems (Azure VMs)
(HANA, SCS, App Servers; HA or standalone)
```

Two processes on the same jump box:

- **FastAPI** (`:8000`) — REST API for job management, schedules,
  workspaces. Used by the CLI, React UI, and CI/CD pipelines.
- **FastMCP** (`:8001`) — MCP server using the official MCP Python SDK
  (`mcp` v1.26.0). Streamable HTTP transport. Used by Azure SRE Agent,
  the built-in `SapAgent`, and any MCP-compatible client.

Both share the same underlying SQLite databases, artifact directories,
and workspace files. Each initializes its own service dependencies
during its lifespan startup.

### 2.2 Components

| Component | What it does | Status |
|-----------|-------------|--------|
| **REST API** | Job CRUD, schedules, workspaces. Used by UI and CLI. | Existing — `src/api/routes/` |
| **MCP Server** | Exposes **20 tools**, 4 resource templates, and 3 prompts over Streamable HTTP via official MCP Python SDK (`FastMCP`). Tools are split into 3 domain modules: **Triage** (6 tools: collect evidence, run analysis, query knowledge, get triage report, list/get workspaces), **STAF** (7 tools: run test, job status/results/events/log, list/cancel jobs), **Ops** (7 tools: schedule CRUD, trigger, schedule-job listing). Runs on port 8001 as a separate process. Integration surface for Azure SRE Agent and other MCP clients. | **Implemented** — `src/mcp_server/tools/{triage,staf,ops}.py` |
| **Execution Control Plane** | Job lifecycle, workspace locking, SSH credentials, artifact storage. | Existing — `src/core/execution/`. Add `triage` job type. |
| **STAF Executor** | Runs Ansible playbooks (HA tests, config checks). Can be destructive. | Existing — `AnsibleExecutor` |
| **Triage Executor** | SSH + allow-listed read-only commands → artifact files. | **New** — implements `ExecutorProtocol` |
| **Analyzer** | Reads artifacts, applies rules, outputs findings with severity + evidence refs. | **New** — `src/core/analyzer/` |
| **Agent Layer** | Multi-agent GroupChat built on Microsoft Agent Framework 1.0.0rc5 (`agent-framework-core` + `agent-framework-azure-ai` + `agent-framework-orchestrations`). `SapAgentFactory` creates 3 specialist agents (Triage, STAF, Ops), each with its own `MCPStreamableHTTPTool` connection to the MCP server, plus an orchestrator agent (SAP-Router) that routes user turns to the right specialist via `GroupChatBuilder`. `ChatService` bridges REST endpoints with workflow execution (sync + SSE streaming). | **Implemented** — `src/agents/agent.py`, `src/core/services/chat.py` |
| **Knowledge Store** | Seed knowledge (JSONL in repo) + learned knowledge (SQLite). Hybrid retrieval. | **New** — `src/core/knowledge/` |

### 2.3 Data Flow

```
User / Alert
   │
   ▼
Agent (Azure SRE Agent or built‑in)
   │
   ▼
MCP tool calls (SAP + Azure)
   │
   ▼
Execution Control Plane
   │
   ▼
Evidence Collection
   │
   ▼
Analyzer (deterministic)
   │
   ▼
Findings + Evidence
   │
   ▼
Formatted RCA report
```

LLMs are used only for:

Planning evidence collection
Formatting final output

All analysis is deterministic.

### 2.4 Key Decisions

| Decision | Choice | Why not the alternative |
|----------|--------|------------------------|
| **MCP transport** | Streamable HTTP on port 8001 (separate from FastAPI on 8000) | stdio needs subprocess per client; same-port mounting adds coupling |
| **Triage executor** | Direct SSH (paramiko/subprocess) | Ansible adds 2-5s overhead per run; overkill for 5-20 read commands |
| **Command safety** | Explicit allow-list | Blocklist always misses something; allow-list is closed by default |
| **Analyzer isolation** | Reads files only; no execution imports | Testable with fixtures, auditable artifacts, no accidental execution |
| **LLM provider** | Pluggable via Protocol | Hardcoding Azure OpenAI makes it unusable for non-Azure users |
| **Agent loop** | Microsoft Agent Framework 1.0.0rc5 | Custom loop is simpler but lacks streaming, content safety, and structured output. The framework handles tool-calling, retries, and Azure OpenAI integration out of the box. |
| **Multi-agent** | GroupChat with orchestrator routing (3 specialists + router) | Single agent degrades tool selection accuracy at 20+ tools; specialist split keeps each agent’s context focused |
| **Embedding provider** | Agent Framework’s `BaseEmbeddingClient` via sync adapter (`EmbeddingAdapter`) | Azure OpenAI in production, Ollama (`OpenAIEmbeddingClient` with `base_url`) for local dev. Adapter wraps AF’s async protocol to our sync `EmbeddingProvider` protocol. No custom OpenAI SDK code. |
| **Vector storage** | SQLite + `sqlite-vec` | No extra service; already using SQLite for jobs/schedules |
| **Rule storage** | JSONL in git (seed), SQLite (learned) | Version-controlled, PR-reviewable, clean diffs (one object/line) |
| **Deployment** | Same Docker image + process as STAF | One jump box, one landscape — microservices add needless complexity |

### 2.5 Azure SRE Agent Integration

[Azure SRE Agent](https://learn.microsoft.com/azure/sre-agent/overview) is
an Azure-hosted AI service (preview) that automates incident triage,
scheduled tasks, and remediation. It supports MCP connectors, custom
subagents, a knowledge base, and integration with PagerDuty, ServiceNow,
and Azure Monitor alerts.

This framework integrates with Azure SRE Agent through its MCP server, which exposes SAP‑specific triage tools. The built‑in agent loop exists as a fallback and reference implementation for environments without Azure SRE Agent.

**Key decision: Azure SRE Agent calls our MCP server (tools), NOT our
agent.** Two LLM orchestrators in series (SRE Agent → our SapAgent → tools)
would double latency, double cost, create conversation ownership conflicts,
and destroy composability. Azure SRE Agent is the orchestrator; our tools
contain the domain logic. When Azure SRE Agent is absent, our built‑in
`SapAgent` fills the orchestrator role. Both paths exercise the same MCP
tool implementations.

```
Cloud                              │ Jumpserver (customer vnet)
                                   │
Azure SRE Agent ───HTTPS──────────►│ Our MCP Server (port 8001)
  (Azure-hosted, its own LLM)      │   ├─ Triage: collect_evidence,
                                   │   │   run_analysis, query_knowledge,
                                   │   │   get_triage_report,
                                   │   │   list_workspaces, get_workspace
                                   │   ├─ STAF: run_staf_test,
                                   │   │   get_job_status, get_job_results,
                                   │   │   list_jobs, cancel_job,
                                   │   │   get_job_events, get_job_log
                                   │   └─ Ops: create/list/get/update/
                                   │       delete_schedule, trigger_schedule,
                                   │       get_schedule_jobs
                                   │
Our SapAgent (fallback) ───────────┤ Our MCP Server (port 8001)
  (runs on jumpserver)             │   └─ (same 20 tools)
     │                             │
     ├─── localhost ──────────────►│ Azure MCP Server (port 8002)
     │                             │   └─ (filtered tools)
     │                             │
     └─── localhost ──────────────►│ Future MCP Server (port 800X)
                                   │   └─ (filtered tools)
```

**Why Azure SRE Agent doesn't need Azure MCP on the jumpserver:**
Azure SRE Agent has its own native Azure tools (Monitor, CLI, Log
Analytics). The jumpserver's Azure MCP instance only serves our
built‑in `SapAgent`, which lacks Azure SRE Agent's native tooling.

**Two integration modes:**

| Mode | Description |
|-----|-------------|
| MCP Connector | Azure SRE Agent connects directly to the SAP MCP server |
| SAP Subagent | Dedicated SAP subagent with ReadOnly tools and SAP knowledge |

**Responsibility Split**

Azure SRE Agent:

- Incident intake and workflow
- Notifications and integrations
- Cross‑session conversational memory
- Governance and run modes

STAF:

- SAP‑side evidence collection
- SAP HA and configuration semantics
- Deterministic RCA
- SAP‑specific knowledge and learning history and cross-domain correlations

**Portable preamble — tool descriptions.** We don't control Azure SRE
Agent's system prompt. Our "preamble" for external consumers lives in
rich MCP tool `description` fields: what each tool does, when to use it,
what it returns, and what to call next in a typical flow.

### 2.6 Azure MCP Server Usage

[Azure MCP Server](https://github.com/Azure/azure-mcp-server) provides
MCP tools for interacting with Azure services. The agent layer (whether
our built-in loop or Azure SRE Agent) uses these tools alongside our
SAP-specific tools.

| Azure MCP capability | How we use it |
|---------------------|---------------|
| **Azure CLI commands** (`az vm show`, `az network lb show`, etc.) | Collect Azure infrastructure evidence: VM power state, load balancer health probes, NIC effective routes, disk IOPS limits. Replaces some of our Azure collector definitions with standard MCP tool calls. |
| **Azure Monitor / Log Analytics** | Query platform metrics (VM CPU, disk throughput) and diagnostic logs without SSH. Correlate Azure-side signals with SAP-side evidence. |
| **Azure Resource Graph** | Bulk-query resource configurations across resource groups (e.g., "list all VMs in this RG with their availability zone and proximity placement group"). |
| **Azure documentation search** | Fetch relevant Azure troubleshooting guides at triage time. Augments our curated reference JSONL with live documentation lookups. |

The agent layer treats Azure MCP tools the same as our SAP tools — both
are in a single tool catalog. During an investigation, the agent decides
which tools to call based on what it's investigating:

- SAP-side evidence → our MCP tools (SSH-based)
- Azure-side evidence → Azure MCP tools (ARM API-based)
- Both in the same triage session, correlated by the analyzer

This means the evidence collection definitions in Section 7.6 for Azure
collectors (`type: "azure"`) can delegate to Azure MCP tools instead of
making direct ARM API calls. Simpler code; the Azure MCP server handles
authentication and pagination.

---

## 4. MCP Server Design

This section defines how the MCP server is built, what principles it
follows, and how tools, security, error handling, performance, and
testing are organized. The design incorporates best practices from
the [Model Context Protocol specification](https://modelcontextprotocol.io/)
and the [Microsoft MCP Best Practices guide](https://github.com/microsoft/mcp-for-beginners/blob/main/08-BestPractices/README.md).

> **Implementation status (Phase 4 + 5).** The MCP server is implemented
> in `src/mcp_server/` using the official MCP Python SDK (`mcp`
> v1.26.0, `FastMCP` class). What's built:
>
> - **20 tools** (6 triage + 7 STAF + 7 ops), **4 resource templates**,
>   **3 prompts** — all registered via `@mcp.tool()`, `@mcp.resource()`,
>   `@mcp.prompt()` decorators. Tools split into domain submodules:
>   `src/mcp_server/tools/{triage,staf,ops}.py`
> - **Lifespan DI** via `SapContext` dataclass + `sap_lifespan()`
>   async context manager
> - **Separate process** on port 8001 (`Streamable HTTP` transport)
> - **Evidence collection** wired to `KnowledgeStore` (21 OS-agnostic
>   seed definitions), `SshCredentialProvider`, and workspace host
>   resolution from Ansible inventory files
> - **Authentication** via `SapTokenVerifier` — bearer token
>   validation with configurable issuer/audience
> - **Input validation** via `InputValidator` — Pydantic-based
>   parameter validation with path traversal prevention
> - **Rate limiting** via `McpRateLimiter` — per-client token bucket
> - **128+ unit tests** covering tools, auth, validation, rate
>   limiting, and evidence collection
>
> What's not yet built (planned):
>
> - Typed `ToolError` hierarchy — Section 4.5
> - SSE progress streaming — Section 4.7
> - External server discovery — Section 4.8

### 4.1 Core Principles

Five principles guide the MCP server implementation:

1. **Standardized communication.** JSON-RPC 2.0 framing for all
   requests, responses, and errors. No custom wire formats.

2. **User-centric control.** Explicit user consent before accessing
   data or performing operations. The user always sees which tools
   the agent is calling and what parameters are being sent. No
   silent data collection.

3. **Security first.** Authentication, parameter validation, command
   allow-listing, and rate limiting are built in from day one — not
   bolted on later.

4. **Modular tools.** Each tool has a single, focused purpose. No
   monolithic tools that combine unrelated concerns. This makes
   tools composable, testable, and easy for the LLM to select.

5. **Stateful connections.** MCP sessions maintain state across
   multiple requests. A triage conversation can call `collect_evidence`,
   then `run_analysis`, then `get_triage_report` — each call builds
   on the context established by the previous one via `TriageSession`.

### 4.2 Tool Design

#### Single Responsibility

Each MCP tool does exactly one thing. The tool catalog splits into three
domain groups — triage tools (investigation), STAF tools (test execution),
and ops tools (scheduling):

**Triage tools** (`src/mcp_server/tools/triage.py` — 6 tools):

| Tool | Purpose | Backing class |
|------|---------|---------------|
| `collect_evidence` | Gather evidence from a target system | `TriageExecutor` |
| `run_analysis` | Analyze collected evidence against rules | `Analyzer` + `CbrExtract` + `LearningPipeline` |
| `query_knowledge` | Search knowledge base (rules, playbooks, references) | `HybridRetriever` |
| `get_triage_report` | Retrieve a completed triage report | `TriageSession` + `ReportFormatter` |
| `list_workspaces` | List available SAP system workspaces | Filesystem scan |
| `get_workspace` | Get workspace configuration details | Filesystem scan |

**STAF tools** (`src/mcp_server/tools/staf.py` — 7 tools):

| Tool | Purpose | Backing class |
|------|---------|---------------|
| `run_staf_test` | Trigger a STAF test (config check, HA scenario) | `JobWorker` |
| `get_job_status` | Poll a running job's status | `JobStore` |
| `get_job_results` | Retrieve job results and artifacts | `JobStore` |
| `get_job_events` | Get event stream for a job | `JobStore` |
| `get_job_log` | Get Ansible log output for a job | `JobStore` |
| `list_jobs` | List jobs with optional filters | `JobStore` |
| `cancel_job` | Cancel a running job | `JobStore` |

**Ops tools** (`src/mcp_server/tools/ops.py` — 7 tools):

| Tool | Purpose | Backing class |
|------|---------|---------------|
| `create_schedule` | Create a cron schedule | `ScheduleStore` |
| `list_schedules` | List all schedules | `ScheduleStore` |
| `get_schedule` | Get schedule details | `ScheduleStore` |
| `update_schedule` | Update schedule configuration | `ScheduleStore` |
| `delete_schedule` | Delete a schedule | `ScheduleStore` |
| `trigger_schedule` | Trigger a schedule immediately | `SchedulerService` |
| `get_schedule_jobs` | List jobs for a schedule | `JobStore` |

Tools are read-only by design. No tool modifies cluster state,
deletes data, or writes to production systems. Evidence collection
runs commands from an explicit allow-list (Section 2, key decisions).

#### Dependency Injection

Tools receive their backing services through the `FastMCP` lifespan
context, not global state. At startup, `sap_lifespan()` initializes
all dependencies into a `SapContext` dataclass. Each tool function
accesses it via `ctx.request_context.lifespan_context`:

```python
@mcp.tool()
async def collect_evidence(
    workspace_id: str,
    definitions: list[str] | None = None,
    timeout_seconds: int = 60,
    ctx: Context[ServerSession, SapContext] | None = None,
) -> dict[str, Any]:
    """Gather cluster evidence from a target SAP system via SSH."""
    assert ctx is not None
    sap: SapContext = ctx.request_context.lifespan_context

    # Load hosts from Ansible inventory
    hosts = _load_workspace_hosts(sap.workspaces_base, workspace_id)

    # Load evidence definitions from knowledge store
    collector_defs = sap.knowledge_store.load_evidence_definitions()

    # Provision SSH credentials
    ssh_credential = sap.ssh_provider.provision(workspace_id, {})

    # Execute collection
    artifacts = await sap.triage_executor.collect(session, evidence_defs)
    ...
```

`SapContext` carries: `job_store`, `knowledge_store`, `analyzer`,
`triage_executor`, `triage_sessions`, `workspaces_base`,
`core_api_url`, `ssh_provider`. All are testable with mocks —
the test fixture creates a `SapContext` with `MagicMock` services.

#### Composability

Tools are designed to be composed in chains (collect → analyze →
report) or used independently. The agent decides the workflow; the
tools don't assume an ordering. A user calling the MCP server directly
(without the agent) can invoke any tool in any sequence.

### 4.3 Schema Design

`FastMCP` auto-generates JSON Schema from Python type annotations and
default values. Each tool parameter includes a docstring description
that the SDK extracts into the MCP `inputSchema`. Parameter validation
happens at two layers: the SDK validates types before the tool function
is called, and the tool function validates domain constraints.

**Clear parameter descriptions.** Descriptions live in the function
docstring and parameter defaults. The SDK generates the `inputSchema`
for tool discovery:

```python
@mcp.tool()
async def collect_evidence(
    workspace_id: str,
    definitions: list[str] | None = None,
    timeout_seconds: int = 60,
    ctx: Context[ServerSession, SapContext] | None = None,
) -> dict[str, Any]:
    """Gather cluster evidence from a target SAP system via SSH.

    :param workspace_id: Workspace identifier for the target SAP system.
    :param definitions: Evidence definition IDs to collect. None means all.
    :param timeout_seconds: Maximum seconds per SSH command (10-300).
    """
```

**Resources and prompts.** In addition to tools, the MCP server
exposes four resource templates (`@mcp.resource()`) for read-only
data the LLM can pull into context, and three prompt templates
(`@mcp.prompt()`) for guided multi-step workflows:

| Resources | URI pattern |
|-----------|-------------|
| Workspace config | `workspace://{workspace_id}/config` |
| Workspace hosts | `workspace://{workspace_id}/hosts` |
| Knowledge base query | `knowledge://{category}/{query}` |
| Job results | `job://{job_id}/results` |

| Prompts | Purpose |
|---------|---------|
| SAP Cluster Triage | Guides: collect → analyze → report |
| Run HA Test Suite | Guides: select test group → run → poll → results |
| Run Config Checks | Guides: list workspaces → run checks → get results |

**Validation constraints.** Pydantic enforces types, ranges, enums,
and required fields. Invalid inputs are rejected before reaching
tool logic:

- String lengths are bounded (`max_length`)
- Numeric fields have ranges (`ge`, `le`)
- Enum fields restrict to known values
- Required fields are explicit

**Consistent return structures.** Every tool returns the same
top-level shape: a typed response model with a `status` field.
Failures return structured error info, not raw exception text:

```python
class ToolResponse(BaseModel):
    status: Literal["success", "error"]
    result: dict | None = None
    error: ToolErrorDetail | None = None

class ToolErrorDetail(BaseModel):
    code: str          # machine-readable: "validation_error", "timeout", "not_found"
    message: str       # human-readable description
    retryable: bool    # whether the caller should retry
```

### 4.4 Security

Security measures are layered. Each layer catches a different class
of problem.

#### Authentication

MCP clients must authenticate before calling any tool. Supported
methods:

| Method | Use case |
|--------|----------|
| **Managed identity** | Azure SRE Agent connecting from within Azure |
| **Bearer token** | External MCP clients, CLI tools |
| **API key** | Simple integrations, development environments |

Authentication is checked once during MCP session initialization
(capability negotiation). The session carries the authenticated
identity for authorization decisions.

#### Tool Permission Control

Not every client should access every tool. Tool permissions are
configured per client:

```yaml
# config/mcp_permissions.yaml
clients:
  azure_sre_agent:
    allowed_tools: ["*"]   # full access
  monitoring_dashboard:
    allowed_tools: ["get_job_status", "get_job_results", "list_workspaces"]
  readonly_viewer:
    allowed_tools: ["query_knowledge", "get_triage_report"]
```

When a client calls a tool it's not authorized for, the server
returns a structured error (`code: "permission_denied"`) without
executing any tool logic.

#### Parameter Validation

All input is validated through Pydantic schemas (Section 4.3) before
reaching tool implementations. Beyond type validation:

- **Path traversal prevention.** Any parameter that references a file
  path is validated against allowed directories. Workspace IDs are
  checked against known workspaces.
- **Command injection prevention.** Evidence collection uses an
  explicit allow-list of commands. Parameters that could influence
  command construction are escaped or rejected.
- **Size limits.** String parameters have maximum lengths. List
  parameters have maximum item counts.

#### Rate Limiting

Per-client rate limiting prevents abuse and ensures fair resource
usage. Limits are configurable per client identity:

```yaml
# config/mcp_rate_limits.yaml
defaults:
  requests_per_minute: 60
  concurrent_evidence_collections: 2
overrides:
  azure_sre_agent:
    requests_per_minute: 120
    concurrent_evidence_collections: 5
```

When a client exceeds its limit, the server returns HTTP 429 with a
`Retry-After` header. The response includes a structured error
(`code: "rate_limit_exceeded"`, `retryable: true`).

#### Sensitive Data Handling

Tool responses may contain system information (hostnames, IPs, config
values). The MCP server:

- Never includes SSH credentials, Azure tokens, or Key Vault secrets
  in tool responses
- Redacts sensitive fields from evidence artifacts when the client's
  permission level doesn't include `sensitive_data` access
- Logs tool calls and responses to the audit trail but redacts
  credential material from log entries

### 4.5 Error Handling

Three levels of error handling, following the structured approach from
the MCP best practices.

#### Graceful Degradation

Tool implementations catch errors at the appropriate level and return
informative messages. Errors are categorized so callers know what
action to take:

| Error category | HTTP code | `code` field | `retryable` | Example |
|---------------|-----------|-------------|-------------|---------|
| Validation | 400 | `validation_error` | No | Missing required parameter |
| Not found | 404 | `not_found` | No | Unknown workspace ID |
| Permission | 403 | `permission_denied` | No | Tool not in client's allow-list |
| Timeout | 408 | `timeout` | Yes | SSH command exceeded timeout |
| Transient | 503 | `service_unavailable` | Yes | Target host unreachable |
| Internal | 500 | `internal_error` | Depends | Unexpected exception |

The agent (or any MCP client) uses the `retryable` flag and error
`code` to decide whether to retry, use a fallback, or report the
failure to the user.

#### Typed Exception Hierarchy

Internal exceptions map to MCP error responses. The mapping is
centralized in the MCP server error handler:

```
ToolError (base)
├── ToolValidationError    → 400, validation_error
├── ToolNotFoundError      → 404, not_found
├── ToolPermissionError    → 403, permission_denied
├── ToolTimeoutError       → 408, timeout
├── ToolTransientError     → 503, service_unavailable
└── ToolExecutionError     → 500, internal_error
```

#### Retry Logic for Transient Failures

Evidence collection involves SSH to remote hosts and Azure API calls,
both of which can fail transiently. The executor handles retries
internally (exponential backoff, max 3 attempts). The MCP tool reports
the final outcome — callers don't need to implement their own retry
logic for evidence collection.

For other transient errors (database locks, temporary file I/O), the
tool returns `retryable: true` and the caller decides whether to
retry. The agent's tool-calling loop includes a configurable retry
policy for retryable tool errors.

### 4.6 Performance

#### Caching

Knowledge lookups are cached. When the agent calls `query_knowledge`
with the same query parameters, the `KnowledgeStore` returns cached
results if the knowledge base hasn't changed since the last query.
Cache key: hash of query parameters + knowledge base modification
timestamp. Cache TTL: configurable, default 15 minutes.

Evidence collection is never cached — it must always reflect current
system state.

#### Asynchronous Processing

Evidence collection and STAF test execution are long-running
operations. The MCP server handles them asynchronously:

1. `collect_evidence` returns immediately with a session ID and
   `status: "collecting"`
2. The executor runs SSH commands in parallel (per-host concurrency)
3. The caller polls via `get_triage_report` or receives progress
   updates via SSE notifications

This follows the process ID + status check pattern from the MCP
best practices — the caller gets an ID immediately and checks status
later, rather than blocking on a long HTTP request.

#### Resource Throttling

Concurrent evidence collections are bounded per workspace (one active
collection per workspace, same locking pattern as existing `JobWorker`)
and globally (configurable max concurrent collections). This prevents
a burst of triage requests from overwhelming target systems with
SSH connections.

### 4.7 Transport and Protocol

#### Streamable HTTP on Port 8001

The MCP server runs as a separate process from FastAPI, using the
`FastMCP` SDK's built-in Streamable HTTP transport. This is a separate
ASGI application exposed via `mcp.streamable_http_app()`:

```python
# src/mcp_server/server.py
mcp = FastMCP(
    "SAP STAF",
    instructions="...",
    lifespan=sap_lifespan,
    stateless_http=True,   # No session persistence between requests
    json_response=True,    # JSON (not SSE) for non-streaming responses
    host="0.0.0.0",
    port=8001,
)

# ASGI app for uvicorn
http_app = mcp.streamable_http_app()
```

The SDK handles JSON-RPC 2.0 framing, tool/resource/prompt
registration, `inputSchema` generation from Python types, and the
`initialize` capability handshake. The `/mcp/` endpoint path is
managed by the SDK.

**Starting the server:**

```bash
# Direct execution
python -m src.mcp_server.server

# Via uvicorn (production)
uvicorn src.mcp_server.server:http_app --host 0.0.0.0 --port 8001

# Both processes (FastAPI + MCP)
uvicorn api.app:app --port 8000 &
uvicorn src.mcp_server.server:http_app --port 8001 &
```

**Configuration via environment variables:**

| Variable | Default | Purpose |
|----------|---------|---------|
| `MCP_PORT` | `8001` | MCP server port |
| `MCP_HOST` | `0.0.0.0` | MCP server bind address |
| `DATA_DIR` | `data` | Shared data directory (SQLite, artifacts) |
| `WORKSPACES_BASE` | `WORKSPACES/SYSTEM` | Workspace root |
| `CORE_API_URL` | `http://localhost:8000` | FastAPI URL (for STAF job submission) |
| `KNOWLEDGE_SEED_DIR` | `src/core/knowledge/seed` | Seed JSONL directory |

#### Capability Negotiation

On connection, the server and client exchange supported features,
protocol versions, and available tools. This follows the MCP spec's
`initialize` handshake:

- Server reports: supported protocol version, available tools with
  schemas, server capabilities (streaming, cancellation)
- Client reports: supported protocol version, client capabilities
- Both sides agree on the protocol version to use

#### Progress Tracking

Long-running operations (evidence collection, STAF test execution)
report progress through the SSE stream. Progress events include:

- Operation ID (session ID or job ID)
- Progress percentage (when estimable)
- Current step description ("Collecting sysctl from node1")
- Elapsed time

This enables responsive UIs and informed agent decisions (e.g., the
agent can tell the user "Evidence collection is 60% complete").

#### Request Cancellation

In-flight tool calls can be cancelled by the client sending a
JSON-RPC cancellation request. The server propagates cancellation
to the underlying operation:

- Evidence collection: signals the SSH executor to stop remaining
  commands, keeps already-collected evidence
- STAF test execution: delegates to existing `Job.cancel()` state
  machine transition
- Analysis: stops processing, returns partial results if available

### 4.8 External Server Discovery

The MCP server acts as both a provider (exposes SAP tools) and a
consumer (discovers tools from external MCP servers). At startup:

1. Read `WORKSPACES/CONFIG/mcp_servers.yaml`
2. Connect to each external server, perform capability negotiation
3. **Filter** tools per server allow-list (Section 4.8.1)
4. **Annotate** tools with per-server safety tier (Section 4.8.2)
5. Merge filtered tools into the unified tool catalog
6. Agent sees one curated list of tools — SAP tools, Azure MCP tools,
   and any custom tools from the external servers

MCP server config lives in `WORKSPACES/CONFIG/` — a shared config
directory separate from per-system workspace data in `WORKSPACES/SYSTEM/`.

Failed connections are logged as warnings. The server starts
successfully even if some external servers are unreachable. External
tool availability is rechecked periodically (configurable interval).

#### 4.8.1 Per-Server Tool Filtering

Exposing all tools from an external MCP server wastes LLM context
window tokens, increases tool selection misrouting, and creates
unnecessary security surface. Each server entry declares an allow-list:

```yaml
# WORKSPACES/CONFIG/mcp_servers.yaml
servers:
  - name: azure
    url: http://localhost:8001
    auth: managed_identity
    safety: confirm_writes
    tools:
      allow:
        - monitor
        - compute
        - network
        - resourcehealth
        - appservice
    preamble_hint: >
      Use Azure tools to check infrastructure health,
      VM status, load balancer config, and resource health.

  - name: custom-monitoring
    url: http://localhost:8002
    auth:
      type: bearer
      token_env: MONITORING_MCP_TOKEN
    safety: read_only
    tools:
      allow: all
    preamble_hint: >
      Use monitoring tools for external metric correlation.
```

When `tools.allow` is a list, only tools whose name contains a listed
prefix are included. When `tools.allow` is `all`, every tool passes.

#### 4.8.2 Per-Server Safety Annotations

External MCP servers have different risk profiles. Our SAP tools are
read-only by design; Azure MCP includes write operations (VM restart,
scale, etc.); a future MCP server is unknown. Each server declares a
safety tier:

| Tier | Meaning | Agent behavior |
|------|---------|----------------|
| `read_only` | All tools are read-only | Call freely during investigation |
| `confirm_writes` | Some tools mutate state | Confirm with user before write operations |
| `confirm_all` | Unknown risk profile | Confirm every call with user |

#### 4.8.3 Layered Preamble Generation

The agent's system prompt is composed from four layers:

1. **Core Identity** (static) — "You are an SAP infrastructure
   operations assistant specializing in HANA HA, SCS, and
   configuration validation on Azure."
2. **Capability Layer** (auto-generated) — enumerates connected MCP
   servers with tool counts and `preamble_hint` text.
3. **Safety Layer** (auto-generated) — per-server safety instructions
   derived from `safety` tier.
4. **Context Layer** (per-conversation) — workspace properties, prior
   triage sessions, system topology.

The core identity never changes. Layers 2-4 adapt to which servers
are connected, their health, and the current conversation context.

#### 4.8.4 Runtime Health Awareness

MCP server health is a runtime property. When an external server
becomes unreachable mid-conversation:

- Its tools are temporarily removed from the catalog
- The agent's preamble is updated to note unavailability
- The agent tells the user which capabilities are degraded
- Periodic reconnection attempts restore tools when the server recovers

### 4.9 Testing Strategy

Testing follows a three-layer pyramid, aligned with the MCP best
practices:

#### Unit Tests

Each tool class is tested in isolation with mocked backing services:

- **Parameter validation:** Invalid inputs return structured 400 errors
- **Happy path:** Valid inputs produce expected outputs
- **Error paths:** Backing service failures map to correct error categories
- **Schema compliance:** Input/output models match declared schemas
- **Permission checks:** Unauthorized tool calls are rejected

#### Integration Tests

The MCP server is tested as a complete unit with `httpx.AsyncClient`:

- **Tool discovery:** `POST /mcp/tools/list` returns all registered tools
- **Tool execution:** `POST /mcp/tools/call` executes tools end-to-end
- **Auth flow:** Unauthenticated requests are rejected
- **Rate limiting:** Requests beyond the limit receive 429 responses
- **SSE streaming:** Progress events arrive on the SSE stream during
  long-running operations
- **Error propagation:** Internal exceptions surface as structured
  MCP error responses

#### End-to-End Tests

Full workflows tested through the MCP protocol:

- **Triage path:** `collect_evidence` → `run_analysis` →
  `get_triage_report` produces a valid report
- **STAF path:** `run_staf_test` → poll `get_job_status` →
  `get_job_results` returns test results
- **Mixed path:** Agent interleaves triage tools, STAF tools, and
  knowledge queries in one session
- **Cancellation:** Cancel a long-running `collect_evidence` call,
  verify partial results are preserved
- **External server:** Connect to a mock external MCP server,
  verify its tools appear in the catalog and are callable

Tests use the same `httpx.AsyncClient` + FastAPI test client pattern
as the existing `tests/api/` suite.

---

## 7. Knowledge Model

Two categories of knowledge:

1. **Seed knowledge** — shipped with the tool, version-controlled in git.
   Rules, playbooks, curated references.
2. **Learned knowledge** — generated at runtime from completed triage
   sessions. Stored in SQLite.

Both use jsonl on disk. One JSON object per
line — easy to diff in PRs, grep from terminal, append without rewriting,
parse in any language.

### 7.1 Seed Knowledge

Lives in `src/core/knowledge/seed/`. The system works with seed knowledge
alone — learned knowledge improves it but is not required.

#### 7.1.1 Rules

A rule describes one thing that should be true. Rules already exist in
this project: config checks in `src/roles/configuration_checks/tasks/files/`
(hundreds of them as YAML), HA cluster constants in
`src/roles/ha_db_hana/tasks/files/constants.yaml` and
`src/roles/ha_scs/tasks/files/constants.yaml`. The knowledge layer
consolidates these into JSONL. Existing YAML files remain for backward
compatibility.

**Schema:**

```jsonl
{
  "id": "DB-HANA-0001",
  "name": "PREFER_SITE_TAKEOVER",
  "description": "Should be true for automatic site takeover during HSR failures",
  "category": "ha_check",
  "severity": "HIGH",
  "applicability": {
    "database_type": "HANA",
    "ha_enabled": true,
    "hana_topology": ["scale_up", "scale_out_hsr"],
    "os_family": ["SUSE", "REDHAT"],
    "hsr_provider": ["SAPHanaSR", "SAPHanaSR-angi"]
  },
  "validator": {
    "type": "exact_match",
    "source": "global_ini",
    "parameter": "PREFER_SITE_TAKEOVER",
    "expected": "true"
  },
  "references": ["SAP Note 2407186", "SAP Note 3398539"],
  "tags": ["hana", "hsr", "ha", "site-takeover"]
}
```

**Applicability filters** — the engine loads only rules matching the
target system:

| Filter | Values | Example |
|--------|--------|---------|
| `database_type` | `HANA`, `DB2`, `ASE`, `Oracle`, `MaxDB`, `SQL` | HANA HSR rule doesn't apply to DB2 |
| `ha_enabled` | `true`, `false` | Pacemaker rules only when HA is configured |
| `hana_topology` | `scale_up`, `scale_out_hsr`, `scale_out_standby` | Scale-out standby has extra nameserver checks |
| `os_family` | `SUSE`, `REDHAT` | SUSE uses `crm`, RHEL uses `pcs` |
| `hsr_provider` | `SAPHanaSR`, `SAPHanaSR-angi` | angi uses different resource ID conventions |
| `storage_type` | `premium_ssd`, `ultra_disk`, `anf` | Kernel tuning differs by storage |
| `scs_type` | `ENSA1`, `ENSA2` | Enqueue replication behavior differs |
| `instance_type` | `app`, `ascs`, `db`, `ers` | Instance-specific checks |

**Validator types:**

| Type | Behavior |
|------|----------|
| `exact_match` | Actual must equal expected |
| `min_value` | Actual ≥ expected (numeric) |
| `range` | Actual within `[min, max]` |
| `regex` | Actual matches pattern |
| `presence` | Value or resource must exist |
| `custom` | Delegates to named Python function |

**Storage-dependent expected values.** Some rules vary by storage type:

```jsonl
{
  "id": "CONFIG-NET-0012",
  "name": "net.core.rmem_max",
  "category": "os_config",
  "severity": "MEDIUM",
  "applicability": { "database_type": "HANA" },
  "validator": {
    "type": "min_value",
    "source": "sysctl",
    "parameter": "net.core.rmem_max",
    "expected_by_storage": {
      "premium_ssd": 2500000,
      "ultra_disk": 2500000,
      "anf": 16777216
    }
  },
  "references": ["SAP Note 2382421"]
}
```

**HA cluster override chains.** Pacemaker properties can be set at
multiple levels. The validator walks the chain, using the first value
found:

```
operation meta → resource meta → resource defaults → CIB bootstrap
```

**Non-HA rules.** Configuration checks for OS parameters, SAP
application settings, and Azure infrastructure. These use `exact_match`,
`min_value`, or `range` validators against sysctl, global.ini, profile
parameters, Azure IMDS metadata, etc.

#### 7.1.2 Playbooks

Investigation procedures for specific failure types. Rules say "what
should be true"; playbooks say "how to investigate when it isn't."

```jsonl
{
  "id": "PB-HANA-HSR-0001",
  "name": "HANA HSR takeover failure",
  "description": "Primary failed but secondary did not take over",
  "category": "ha_failure",
  "symptoms": [
    "Secondary remains in SOK status after primary failure",
    "No takeover entry in nameserver trace",
    "Pacemaker shows primary stopped but no promote action"
  ],
  "investigation": [
    "Check SAPHanaSR sync_state: crm_attribute -G -n hana_<SID>_sync_state",
    "Check PREFER_SITE_TAKEOVER in global.ini",
    "Check location bans: crm_mon -1 | grep -i ban",
    "Check nameserver trace: grep -i takeover /hana/shared/<SID>/HDB<NR>/*/trace/nameserver_*.trc"
  ],
  "root_cause": "PREFER_SITE_TAKEOVER disabled or location constraint blocking takeover",
  "fixes": [
    "Set PREFER_SITE_TAKEOVER = true in global.ini",
    "Remove blocking constraints: crm resource clear <resource_id>",
    "Re-register secondary: hdbnsutil -sr_register ..."
  ],
  "related_patterns": ["DB-HANA-0001", "PB-HANA-CONSTRAINT-0001"],
  "tags": ["hana", "hsr", "takeover", "ha"],
  "source": "seed"
}
```

Symptom matching uses keyword matching + semantic similarity (when
embeddings are available). Investigation steps are ordered and can be
executed automatically by the evidence collection layer.

#### 7.1.3 Curated References

Links to SAP Notes, Azure docs, and known-issue descriptions. Included
in triage output so operators have authoritative sources.

```jsonl
{
  "id": "REF-HANA-HSR-0001",
  "title": "SAP HANA System Replication - Operation Guide",
  "url": "https://help.sap.com/docs/SAP_HANA_PLATFORM/6b94445c94ae495c83a19646e7c3fd56",
  "category": "hana_hsr",
  "failure_classes": ["hsr_takeover_failure", "hsr_sync_failure"],
  "summary": "HSR setup, monitoring, takeover procedures, troubleshooting",
  "tags": ["hana", "hsr", "sap-note"]
}
```

### 7.2 Learned Knowledge — Case-Based Reasoning

The knowledge system follows the **Case-Based Reasoning (CBR)** cycle
— the established methodology for systems that learn from resolved
incidents. Each triage session is a "case"; each stored pattern is a
prior case available for future matching.

```
┌───────────┐    ┌───────────┐    ┌───────────┐    ┌───────────┐
│ 1.RETRIEVE│───▶│ 2.REUSE   │───▶│ 3.REVISE  │───▶│ 4.RETAIN  │
│ Find      │    │ Adapt past│    │ Update    │    │ Store the │
│ similar   │    │ solutions │    │ based on  │    │ new case  │
│ past cases│    │ to current│    │ outcome   │    │ for future│
└───────────┘    └───────────┘    └───────────┘    └───────────┘
      ▲                                                  │
      └──────────────────────────────────────────────────┘
```

| CBR step | Phase delivered | What it does | Implementation |
|----------|----------------|--------------|----------------|
| **Retrieve** | Phase 1 | Find similar past cases by structured filter + vector/keyword similarity | `HybridRetriever` (applicability filter → cosine similarity via `sqlite-vec` → keyword fallback) |
| **Reuse** | Phase 1 + agent | Adapt past playbook steps to the current incident | The multi-agent Triage specialist naturally adapts retrieved playbook steps to incident context during conversation — no programmatic rewriting needed |
| **Revise** | Phase 1 (heuristic) → Phase 5 (LLM) | Update pattern confidence based on session outcome | Phase 1: outcome-weighted confidence update from `ExperienceEntry`. Phase 5: LLM judges semantic equivalence for consolidation |
| **Retain** | Phase 1 | Store the resolved case as a new or reinforced pattern + compute embedding | `LearningPipeline` → `KnowledgeStore` + `EmbeddingStore` + `KnowledgeGraph` |

#### 7.2.1 Pattern Observation Pipeline (CBR: Revise + Retain)

Runs automatically after each completed triage session. In Phase 1 this
is a deterministic heuristic pipeline. In Phase 5 the Extract and
Consolidate steps are upgraded to LLM-powered equivalents.

```
Session ──▶ Consolidate ──▶ Revise ──▶ Store ──┬──▶ Link (graph)
             (de-dup)     (confidence) (SQLite  └──▶ Log (experience)
                                       + vec)
```

1. **Consolidate.** Similarity search against existing patterns:
   - ≥ 0.95 similarity: near-duplicate → reinforce existing pattern.
   - 0.85–0.95: related → store as new with cross-reference.
   - < 0.85: novel → store as new pattern.

   Phase 1 uses keyword token overlap or cosine similarity (when
   embeddings are available). Phase 5 upgrades to LLM-judged semantic
   equivalence ("Do these two patterns describe the same root cause?").

2. **Revise.** Update confidence based on session outcome:
   - `operator_feedback == "correct"` + `resolution_applied`: full boost.
   - `root_cause_found` but no resolution: half boost.
   - `operator_feedback == "incorrect"`: penalty (confidence decreases).
   - Age-based decay: confidence erodes at 0.02/month when pattern is
     not reinforced. Prevents stale patterns from accumulating.

   Confidence model uses outcome-weighted updates, not a flat `+0.05`.

3. **Store.** Persist to `KnowledgeStore` (SQLite) + compute and store
   embedding in `EmbeddingStore` (sqlite-vec).

4. **Link.** Connect to related patterns in knowledge graph (shared
   symptoms, root causes, or co-occurrence).

5. **Log.** Append session outcome to experience log.

> **Phase 5 upgrade — Extract step.** In Phase 5, the `SapAgent` uses
> the LLM to extract a structured `LearnedPattern` from the session
> transcript and evidence. In Phase 1, the caller (or a future
> template-based extractor) constructs the candidate pattern from
> `ExperienceEntry` fields.

#### 7.2.2 Learned Pattern Schema

Same schema as seed playbooks + provenance tracking:

```jsonl
{
  "id": "LP-2024-0042",
  "name": "ANF volume throttling causes HANA backup timeout",
  "description": "ANF performance tier downgrade caused backup write throughput to drop below HANA's minimum",
  "category": "storage_performance",
  "symptoms": [
    "HANA backup failed with timeout",
    "ANF volume metrics show sustained IOPS at tier limit",
    "No network or OS-level errors"
  ],
  "investigation": [
    "Check ANF volume performance tier",
    "Check ANF throughput metrics for backup volume",
    "Check HANA backup log for write throughput numbers"
  ],
  "root_cause": "ANF performance tier insufficient for backup workload",
  "fixes": [
    "Upgrade ANF volume to higher performance tier",
    "Schedule backups during low-activity periods",
    "Split backup across multiple volumes"
  ],
  "tags": ["hana", "anf", "backup", "storage"],
  "source": "learned",
  "confidence": 0.72,
  "occurrence_count": 3,
  "first_seen": "2024-11-15T08:23:00Z",
  "last_seen": "2025-01-10T14:45:00Z",
  "source_sessions": ["session-2024-1115-001", "session-2024-1203-002", "session-2025-0110-001"]
}
```

`confidence` starts low, increases with reinforcement. `source_sessions`
provides traceability back to originating triage sessions.

#### 7.2.3 Experience Log

```jsonl
{
  "session_id": "session-2025-0110-001",
  "timestamp": "2025-01-10T14:45:00Z",
  "system_id": "PRD-HANA-01",
  "trigger": "ha_failover_test",
  "duration_seconds": 342,
  "patterns_matched": ["PB-HANA-HSR-0001", "LP-2024-0042"],
  "rules_fired": 47,
  "rules_failed": 3,
  "root_cause_found": true,
  "resolution_applied": true,
  "operator_feedback": "correct",
  "knowledge_gaps": []
}
```

Used for: (1) confidence updates — successful patterns score higher,
(2) gap detection — sessions with `root_cause_found: false` signal
missing seed knowledge.

### 7.3 Retrieval (CBR: Retrieve)

The Retrieve step of the CBR cycle. Given a new incident, find the most
relevant past cases (rules, playbooks, learned patterns) to reuse.

#### 7.3.1 Hybrid Search

1. **Structured filter.** Narrow by applicability (database type, OS,
   HA, etc.) — direct SQLite query.
2. **Vector similarity.** Rank filtered candidates by cosine similarity
   using `sqlite-vec`. When an `EmbeddingProvider` is configured,
   embeddings are computed for the query and compared against stored
   embeddings. Falls back to keyword matching on `tags`, `symptoms`,
   `description` when embeddings are unavailable for a given item.
3. **Score.**

```
score = 0.45 × relevance + 0.35 × confidence + 0.20 × recency
```

- **Relevance** (45%): cosine similarity from `sqlite-vec` (primary),
  or keyword token overlap (fallback per item).
- **Confidence** (35%): seed starts at 1.0, learned starts at 0.3
  and evolves via outcome-weighted CBR Revise updates.
- **Recency** (20%): exponential decay on `last_seen` (90-day
  half-life).

#### 7.3.2 Prompt Augmentation

Retrieved knowledge injected into LLM prompt: matching rules (expected
vs actual), playbooks (investigation steps), references (URLs),
confidence scores (seed vs learned).

Learned patterns with `confidence < 0.4`: included with warning flag.
Below `0.2`: excluded.

### 7.4 Knowledge Graph

Captures relationships between patterns. Stored in SQLite
(`data/knowledge.db`).

**Relationship types:**

| Type | Meaning | Example |
|------|---------|---------|
| `causes` | A can cause B | Network isolation → HSR sync failure |
| `caused_by` | Inverse of causes | HSR sync failure → network isolation |
| `related_to` | Co-occur or share symptoms | ANF throttling ↔ backup timeout |
| `supersedes` | A is more specific than B | SAPHanaSR-angi failure supersedes generic |
| `prerequisite` | A must be resolved before B | Fencing before takeover |

**Schema:**

```sql
CREATE TABLE knowledge_edges (
    source_id   TEXT NOT NULL,
    target_id   TEXT NOT NULL,
    edge_type   TEXT NOT NULL,
    strength    REAL DEFAULT 0.5,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (source_id, target_id, edge_type)
);
```

`strength` updated via EMA: `new = 0.3 × observed + 0.7 × old`.
Gradual updates — one spurious co-occurrence doesn't shift the score.

**Graph queries:** causal chain detection (walk `causes`/`caused_by`),
related pattern expansion, investigation ordering via `prerequisite`
edges.

### 7.5 Knowledge Gap Tracking

Unmatched failures logged to `data/knowledge/gaps.jsonl`:

```jsonl
{
  "id": "GAP-2025-0015",
  "timestamp": "2025-01-12T09:30:00Z",
  "session_id": "session-2025-0112-001",
  "system_id": "PRD-HANA-01",
  "query": "HANA indexserver crash with signal 11 after kernel upgrade",
  "symptoms_observed": [
    "indexserver terminated with signal 11",
    "Recent kernel upgrade from 5.14 to 5.15",
    "No configuration changes"
  ],
  "nearest_pattern": "PB-HANA-CRASH-0001",
  "nearest_similarity": 0.62,
  "resolved_manually": false
}
```

Each gap signals where seed knowledge needs a new rule or playbook.

### 7.6 Evidence Collection Definitions

Describe how to get data from a running system. Separate from rules —
one definition can serve many rules. All support `cache_ttl_seconds`
to avoid redundant collection.

**Command collectors** (SSH):

```jsonl
{
  "id": "EC-SYSCTL-0001",
  "type": "command",
  "name": "sysctl_all",
  "command": "sysctl -a",
  "os_family": ["SUSE", "REDHAT"],
  "parser": "key_value_equals",
  "cache_ttl_seconds": 300
}
```

**Azure collectors** (ARM API or Azure MCP tools):

```jsonl
{
  "id": "EC-AZURE-LB-0001",
  "type": "azure",
  "name": "load_balancer_config",
  "api": "azure.mgmt.network.load_balancers.list_by_resource_group",
  "auth": "managed_identity",
  "parser": "azure_lb_parser",
  "cache_ttl_seconds": 600
}
```

When Azure MCP Server is available, Azure collectors delegate to it
instead of making direct ARM calls — the MCP server handles auth and
pagination.

**Module collectors** (existing Ansible modules):

```jsonl
{
  "id": "EC-CIB-0001",
  "type": "module",
  "name": "pacemaker_cib",
  "module": "get_pcmk_properties_db",
  "parser": "cib_xml_parser",
  "cache_ttl_seconds": 60
}
```

### 7.7 File Layout

```
src/core/knowledge/
├── seed/                           # Version-controlled, shipped with tool
│   ├── rules/                      # 732 rules across 11 files
│   │   ├── app.jsonl               # Application config rules (12)
│   │   ├── ascs.jsonl              # ASCS config rules (6)
│   │   ├── db2.jsonl               # DB2 config rules (27)
│   │   ├── ha_db_cluster.jsonl     # DB HA Pacemaker constants (355)
│   │   ├── ha_scs_cluster.jsonl    # SCS HA Pacemaker constants (194)
│   │   ├── hana.jsonl              # HANA config rules (52)
│   │   ├── high_availability.jsonl # Cross-cutting HA rules (5)
│   │   ├── network.jsonl           # Network config rules (7)
│   │   ├── package.jsonl           # Package/version rules (15)
│   │   ├── sap.jsonl               # SAP application rules (18)
│   │   └── virtual_machine.jsonl   # Azure VM config rules (41)
│   ├── playbooks/
│   │   └── ha_playbooks.jsonl      # 5 HA failure investigation playbooks
│   ├── references/
│   │   └── azure_sap_references.jsonl  # 7 SAP Notes + Azure docs
│   └── evidence/                   # Implemented — 21 OS-agnostic definitions
│       └── command_collectors.jsonl

data/knowledge/                     # Runtime, gitignored
├── learned_patterns.jsonl
├── experience.jsonl
├── gaps.jsonl
└── knowledge.db                    # SQLite: embeddings + graph edges
```

### 7.8 End-to-End Flow

1. **Load system properties** from evidence or input parameters.
2. **Filter rules** by applicability against system properties.
3. **Match playbooks** — keyword + semantic similarity against symptoms.
   Rank by relevance, confidence, recency.
4. **Collect evidence** per matched rules and playbooks. Cache within TTL.
5. **Evaluate rules** — validators compare evidence vs expected values.
   Failures become findings (rule ID, expected, actual, severity, refs).
6. **Produce report** — structured findings + playbook guidance +
   references. LLM augments with natural language if configured.
7. **CBR Retain** — pattern observation pipeline consolidates findings,\n   updates confidence via outcome-weighted Revise, stores patterns,\n   computes embeddings, updates graph, logs experience.

---

## 8. Development Plan

Strict object-oriented methodology. Each phase produces tested,
reviewable code with clear class boundaries. No phase starts until its
predecessor's tests pass at 85% coverage.

### 8.1 Phases

```
Phase 0 ──▶ Phase 1 ──▶ Phase 2 ──▶ Phase 3 ──▶ Phase 4 ──▶ Phase 5
Domain       Storage     Triage      Analyzer    MCP Server   Agent +
Model        Layer       Executor                + Chat API   Chat UI
```

Chat is not a bolt-on. Conversation models, storage, endpoints, and
frontend components ship inside the phases where their peers live.

### Phase 0: Domain Model (foundation, no behavior)

Define the types that every subsequent phase depends on. No I/O, no side
effects — pure data classes and enums.

**New files:**

| File | Classes | Notes |
|------|---------|-------|
| `src/core/models/triage.py` | `TriageStatus` (enum), `TriageEventType` (enum), `TriageEvent`, `TriageRequest`, `TriageSession`, `TriageFinding`, `TriageReport` | Pydantic v2 models. `TriageSession` has state machine (pending → collecting → analyzing → complete/failed/cancelled) modeled after existing `Job`. `TriageEvent` records timestamped state transitions. |
| `src/core/models/evidence.py` | `EvidenceArtifact`, `EvidenceType` (enum), `CollectorType` (enum), `CollectionStatus` (enum) | Immutable value objects (frozen dataclasses). `EvidenceType`: `command_output`, `azure_metadata`, `cib_xml`, `log_excerpt`, `sap_process_list`. `CollectionStatus`: `success`, `failed`, `timeout`, `unreachable`. Every artifact carries its collection status so the analyzer knows which evidence is trustworthy vs degraded. |
| `src/core/models/knowledge.py` | `ValidatorSpec`, `Rule`, `Playbook`, `Reference`, `LearnedPattern`, `KnowledgeGap`, `ExperienceEntry` | Pydantic models matching the JSONL schemas in Section 7. `ValidatorSpec` embeds in `Rule.validator`. |
| `src/core/models/system.py` | `SystemProperties`, `Applicability` | `SystemProperties` holds the 8 filter dimensions (database_type, ha_enabled, etc.). `Applicability.matches(system: SystemProperties) → bool`. |
| `src/core/models/failure.py` | `FailureClass` (enum), `Severity` (enum) | `FailureClass`: `FENCING_NOT_TRIGGERED`, `WRONG_FS_TYPE`, `HSR_SYNC_FAILURE`, etc. Reuse existing `TestSeverity` where possible. |
| `src/core/models/validators.py` | `ValidatorType` (enum), `ValidatorResult` | `ValidatorType`: `exact_match`, `min_value`, `range`, `regex`, `presence`, `custom`. `ValidatorResult` (frozen dataclass): `passed`, `rule_id`, `expected`, `actual`, `validator_type`, `message`, `to_dict()`. |
| `src/core/models/conversation.py` | `Conversation`, `Message`, `MessageRole` (enum), `ConversationStatus` (enum) | `Conversation` is a state machine (active → archived). `Message` has `role` (user/assistant/system/tool_call/tool_result), `content`, optional `thinking` (LLM reasoning trace, populated only on assistant messages — rendered as a collapsible section in the UI for transparency), `timestamp`, optional `triage_session_id` linking to the underlying triage run. Same state-machine pattern as `Job` and `TriageSession`. |

**Conventions:**
- All models frozen or have controlled mutability via explicit methods
- State transitions via methods (not direct field assignment), same as `Job.start()` / `Job.complete()`
- No imports from `execution`, `storage`, or `observability`

**Tests:** `tests/core/triage_test.py`, `evidence_test.py`, `knowledge_test.py`, `system_test.py`, `failure_test.py`, `validators_test.py`, `conversation_test.py`

**Exit criteria:** All models instantiate, serialize to/from JSON, state transitions reject invalid states. `Conversation` rejects adding messages after archival. 100% coverage on this phase.

---

### Phase 1: Storage Layer

Persistence for knowledge and conversations. Both are SQLite repositories
built on the same pattern as the existing `JobStore` / `ScheduleStore`.
Depends on Phase 0 models.

**Knowledge files:**

| File | Classes | Pattern |
|------|---------|---------|
| `src/core/knowledge/__init__.py` | — | Package init. Re-exports `KnowledgeStore`, `KnowledgeGraph`, `EmbeddingStore`, `EmbeddingProvider`, `JsonlLoader`, `HybridRetriever`, `LearningPipeline`. |
| `src/core/storage/knowledge_store.py` | `KnowledgeStore` | **Repository pattern**, same as `JobStore` / `ScheduleStore`. Core read API: `load_rules(system?) → list[Rule]`, `load_playbooks() → list[Playbook]`, `load_references() → list[Reference]`, `load_learned_patterns(min_confidence?) → list[LearnedPattern]`. Single-item reads: `get_rule(id)`, `get_learned_pattern(id)`, `get_experience(session_id)`, `get_unresolved_gaps()`. Write API: `save_rule()`, `save_rules()` (batch), `save_playbook()`, `save_reference()`, `save_learned_pattern()`, `log_experience()`, `log_gap()`. |
| `src/core/knowledge/loader.py` | `JsonlLoader` | Reads `*.jsonl` files from a directory, deserializes each line into the corresponding Pydantic model. Isolated I/O boundary. |
| `src/core/storage/knowledge_graph.py` | `KnowledgeGraph` | SQLite table `knowledge_edges`. Methods: `add_edge()`, `get_causes()`, `get_effects()`, `get_related()`, `get_prerequisites()`, `get_all_edges()`, `update_strength()`. 5 edge types (`causes`, `caused_by`, `related_to`, `supersedes`, `prerequisite`). EMA formula from Section 7.4. |
| `src/core/knowledge/retrieval.py` | `HybridRetriever` | **Strategy pattern**. CBR Retrieve step. Structured filter + vector similarity via `EmbeddingStore`/`EmbeddingProvider`. Falls back to keyword matching per-item when embeddings are unavailable. Scoring formula from Section 7.3.1. |
| `src/core/knowledge/learning.py` | `LearningPipeline` | CBR Revise + Retain steps. Outcome-weighted confidence updates from `ExperienceEntry`. Depends on `KnowledgeStore`, `KnowledgeGraph`, `HybridRetriever`, optional `EmbeddingStore`/`EmbeddingProvider`. |
| `src/core/models/embedding.py` | `EmbeddingProvider` | **Protocol** (structural typing). Defines `embed(text) → list[float]`, `embed_batch()`, `dimensions`. Implementations: Azure OpenAI (Phase 5), local sentence-transformers (offline), or none (keyword fallback). |
| `src/core/storage/embedding_store.py` | `EmbeddingStore` | **Repository pattern**. SQLite + `sqlite-vec` backed vector storage. Cosine similarity KNN search via `vec0` virtual table. Dimension validation on open, `text_hash` for staleness detection. Methods: `store()`, `search()`, `get()`, `delete()`. |

**Seed data files (JSONL):**
- `src/core/knowledge/seed/rules/*.jsonl` — **732 rules** across 11
  domain JSONL files:
  - **Configuration-check rules** (183 rules, 9 files): `app.jsonl`
    (12), `ascs.jsonl` (6), `db2.jsonl` (27), `hana.jsonl` (52),
    `high_availability.jsonl` (5), `network.jsonl` (7),
    `package.jsonl` (15), `sap.jsonl` (18), `virtual_machine.jsonl`
    (41). Converted from
    `src/roles/configuration_checks/tasks/files/*.yml`.
  - **HA cluster constants** (549 rules, 2 files):
    `ha_db_cluster.jsonl` (355 — CRM config, op/rsc defaults,
    constraints, resource attributes/operations, OS params, global.ini,
    Azure LB) and `ha_scs_cluster.jsonl` (194 — same sections for SCS
    clusters). Converted from
    `src/roles/ha_db_hana/tasks/files/constants.yaml` and
    `src/roles/ha_scs/tasks/files/constants.yaml`.
- `src/core/knowledge/seed/playbooks/ha_playbooks.jsonl` — 5 initial
  HA failure playbooks (HSR sync, fencing, ANF throttling, enqueue
  replication, network isolation).
- `src/core/knowledge/seed/references/azure_sap_references.jsonl` — 7
  SAP Notes and Azure docs.

> **YAML→JSONL converters.** Two scripts convert existing YAML
> knowledge into JSONL format:
>
> 1. `scripts/yaml_to_jsonl.py` — Reads config-check YAML rule files
>    (with anchors and enums), resolves them via PyYAML, maps fields to
>    the `Rule` Pydantic model schema, and writes one JSONL file per
>    source domain. Handles edge cases: boolean applicability values,
>    nested reference dicts, nested list flattening. Run with:
>    `python scripts/yaml_to_jsonl.py [--input-dir DIR] [--output-dir DIR]`.
>
> 2. `scripts/constants_to_jsonl.py` — Reads HA cluster Pacemaker
>    constants (CRM config, operation/resource defaults, constraints,
>    per-OS per-resource attributes+operations, OS parameters,
>    global.ini settings, Azure LB config). Walks the YAML tree,
>    emitting one Rule per leaf value node. Handles storage-dependent
>    values (ANF/AFS), presence checks for required resources, and
>    OS-family-specific variant overrides (REDHAT, AFA, ISCSI, ASD,
>    angi). Run with:
>    `python scripts/constants_to_jsonl.py [--output-dir DIR]`.

> **Implementation note — `sqlite-vec`.** This is a C extension
> distributed as a pip-installable wheel (`pip install sqlite-vec`).
> It provides cosine-similarity KNN search directly inside SQLite via
> the `vec0` virtual table — no external vector database needed. This
> is consistent with our SQLite-everywhere pattern (`JobStore`,
> `ScheduleStore`, `KnowledgeStore`). Vector search is a core feature,
> not an enhancement. The `HybridRetriever` still falls back to keyword
> matching **per item** when embeddings have not yet been computed for
> that item, ensuring the system works during initial deployment before
> embeddings are populated.
>
> **Why not Azure AI Search:** The tool runs on SAP jump boxes in
> restricted VNets, often without outbound internet. Azure AI Search
> would add a network dependency to the retrieval hot path — the exact
> path that must work during Azure region outages (when you most need
> triage). Additionally, our data volume (~700 rules, ~50 playbooks,
> ~100 learned patterns) is orders of magnitude below what justifies a
> managed search service. `sqlite-vec` handles this in microseconds
> locally.

**Conversation files:**

| File | Classes | Pattern |
|------|---------|--------|
| `src/core/storage/conversation_store.py` | `ConversationStore` | **Repository pattern**, same as `JobStore`. SQLite tables `conversations` + `messages`. The `messages` table stores the optional `thinking` column (nullable TEXT) so reasoning traces are persisted alongside responses. Methods: `create()`, `get()`, `add_message()`, `get_history(conversation_id, limit?)`, `list_conversations(workspace_id, include_archived?, limit?)`, `archive()`. Conversations are per-workspace (one SAP system per conversation). |

**Tests:** `tests/core/knowledge/store_test.py`, `loader_test.py`, `graph_test.py`, `retrieval_test.py`, `learning_test.py`, `functional_test.py`, `tests/core/storage/conversation_store_test.py`, `embedding_store_test.py`. Use `tmp_path` fixtures with test JSONL files — no mocks of the filesystem. Test the graph with an in-memory SQLite database. Test conversation store CRUD, archival, thinking column, and message ordering. `functional_test.py` is an end-to-end integration test that loads real seed JSONL (732 rules + 5 playbooks + 7 references) into real SQLite, exercises applicability filtering, keyword/vector retrieval, the full CBR cycle (learn → retrieve → boost/penalize), graph edge creation from learning, and seed+learned coexistence. 21 tests, no mocks of core components.

**Exit criteria:** `KnowledgeStore.load_rules(system)` returns only applicable rules. Graph queries return correct causal chains. CBR Retrieve (`HybridRetriever`) returns relevant results via both keyword and vector paths. CBR Retain (`LearningPipeline`) stores and consolidates patterns with outcome-weighted confidence. CBR Revise updates confidence based on `ExperienceEntry` feedback fields. `EmbeddingStore` stores and searches vector embeddings. `LearningPipeline` computes and persists embeddings when an `EmbeddingProvider` is configured. `ConversationStore` persists and retrieves multi-turn histories correctly.

---

### Phase 2: Triage Executor

SSH-based evidence collection. Depends on Phase 0 models.

**New files:**

| File | Classes | Pattern |
|------|---------|---------|
| `src/core/execution/triage_executor.py` | `TriageExecutor` | New `TriageExecutorProtocol` (see note below). Uses `SshCredentialProvider` (reuse as-is). |
| `src/core/execution/command_allow_list.py` | `AllowedCommand`, `CommandAllowList` | `AllowedCommand` frozen dataclass (pattern, description, source, max_timeout_seconds). `CommandAllowList` loads allowed commands from a bundled YAML file (`allowed_commands.yaml`) with 20 safe SAP diagnostic command patterns. `is_allowed(cmd: str) → bool`. Factory methods: `from_patterns()`, `from_yaml()`, `default()`. Reject everything not on the list. |
| `src/core/execution/evidence_collector.py` | `EvidenceDefinition`, `CollectorStrategy` (Protocol), `EvidenceCollector` | **Strategy pattern** — `CollectorStrategy` Protocol defines `collect(definition) → EvidenceArtifact`. Strategies are registered per `CollectorType` via `register_strategy()`. `EvidenceCollector` orchestrates collection with allow-list enforcement, TTL caching, and partial-failure tolerance (`collect_all()`, `collect_one()`). Concrete strategy implementations (SSH, Azure, module) are wired by callers. |

**Key constraints:**
- `TriageExecutor` only calls commands that `CommandAllowList.is_allowed()` returns `True` for
- All output written as `EvidenceArtifact` files (JSON) to the job's artifact directory
- Reuses existing `SshCredentialProvider` and workspace locking from `JobWorker`

> **Implementation note — interface mismatch.** The existing
> `ExecutorProtocol.run_test()` takes Ansible-specific arguments
> (`test_group`, `test_id`, `inventory_path`). `TriageExecutor` needs a
> different signature: `collect(session: TriageSession, evidence_defs:
> list) → list[EvidenceArtifact]`. Solution: define a new
> `TriageExecutorProtocol`. Do not force-fit the Ansible interface.
> Similarly, the existing `Collector` ABC requires an Ansible module
> parent (`SapAutomationQA`). Evidence collectors need a context-free
> base — define `EvidenceCollectorProtocol` instead of extending
> `Collector`.
>
> The existing `JobWorker` and `CreateJobRequest` are also
> Ansible-shaped (`test_group`, `test_ids`). Add a `job_type`
> discriminator or create a parallel `TriageJobRequest` +
> `TriageJobWorker` that shares workspace locking logic via a common
> mixin / base, not by cramming both shapes into one class.

> **Implementation note — partial failure.** SSH to production SAP
> clusters will fail partially (node unreachable, command timeout, ARM
> throttled). This is the normal case. Every `EvidenceArtifact` carries
> `CollectionStatus` (Phase 0). The collector must continue collecting
> remaining evidence after individual failures. The analyzer must handle
> missing evidence gracefully: skip rules whose evidence is unavailable,
> and report "could not evaluate — evidence unavailable" as a distinct
> finding severity, not a crash.

**Tests:** `tests/core/command_allow_list_test.py`, `evidence_collector_test.py`, `triage_executor_test.py`. Test allow-list rejects unlisted commands. Test caching honors TTL. Test artifact serialization. Test state transitions (PENDING → COLLECTING → ANALYZING).

**Exit criteria:** Executor runs a set of commands against mock SSH, writes artifacts, rejects disallowed commands.

---

### Phase 3: Analyzer

Reads artifacts, evaluates rules, produces findings. Depends on Phase 0 + Phase 1 + Phase 2 artifacts.

**New files:**

| File | Classes | Pattern |
|------|---------|---------|
| `src/core/analyzer/__init__.py` | — | Re-exports: `Normalizer`, `NormalizedData`, `SysctlNormalizer`, `CibXmlNormalizer`, `CibSectionNormalizer`, `CIB_SOURCES`, `KeyValueNormalizer`, `LogNormalizer`, `NormalizerRegistry`, `RuleValidator`, `ReportBuilder`, `Analyzer`. |
| `src/core/analyzer/normalizers.py` | `NormalizedData`, `Normalizer` (Protocol), `SysctlNormalizer`, `CibXmlNormalizer`, `CibSectionNormalizer`, `KeyValueNormalizer`, `LogNormalizer`, `NormalizerRegistry`, `CIB_SOURCES` | `NormalizedData` (dataclass): `source`, `values` dict, `evidence_id`, `host`, `get()`, `has()`. `Normalizer` Protocol: `normalize(artifact) → NormalizedData`. `SysctlNormalizer`: parses `key = value` lines. `CibXmlNormalizer`: full Pacemaker CIB XML parsing into prefixed keys (crm_config.X, resource.X.Y, op_defaults.X, rsc_defaults.X, constraint.X). `CibSectionNormalizer`: wraps `CibXmlNormalizer`, filters by section and strips prefixes so keys match rule parameters directly — normalizer layer owns all CIB format knowledge. `KeyValueNormalizer`: configurable separator and source name. `LogNormalizer`: line indexing + pattern extraction. `NormalizerRegistry`: maps source names to normalizer instances, supports **source groups** (`register_group()`, `get_peer_sources()`) for CIB fan-out. `CIB_SOURCES` frozenset: `{crm_config, op_defaults, rsc_defaults, constraints, cib_resource}`. |
| `src/core/analyzer/validators.py` | `RuleValidator` | **Strategy pattern**. 6 strategy functions (`_exact_match`, `_min_value`, `_range_check`, `_regex_match`, `_presence_check`, `_custom_check`) dispatched via `_STRATEGIES` dict by `ValidatorType`. `RuleValidator.validate()` does direct `data.get(spec.parameter)` lookup — no CIB-specific logic. `validate_many()` for batch evaluation. Returns `ValidatorResult`. |
| `src/core/analyzer/report.py` | `ReportBuilder` | `ReportBuilder(playbooks, references)`. Assembles `TriageFinding` list from failed `ValidatorResult`s. Uses `_classify_failure()` (tag/category heuristics for 8 tag→FailureClass + 5 category→FailureClass mappings) and `_map_severity()`. Matches playbooks and references by tag/category overlap. `_build_summary()` generates report summary with finding counts by severity. |
| `src/core/analyzer/analyzer.py` | `Analyzer` | **Facade**. `analyze(session: TriageSession, artifacts: list[EvidenceArtifact], rules: list[Rule]) → TriageReport` — full pipeline with session state transitions (ANALYZING → COMPLETE). `analyze_artifacts(artifacts, rules) → list[ValidatorResult]` — stateless variant. Pipeline: `_filter_usable()` → `_normalize_all()` (with **peer source fan-out**: one CIB artifact auto-populates all 5 CIB sources) → `_filter_rules_with_evidence()` → `validate_many()` → `build()`. `_infer_source()` uses evidence type only (CIB_XML→cib_resource, LOG_EXCERPT→log), no command-string parsing. |

**Import constraint enforced:** `src/core/analyzer/` does NOT import from `src/core/execution/`. Analyzer receives `EvidenceArtifact` objects directly (in memory, not from disk).

**Tests:** `tests/core/normalizers_test.py`, `rule_validator_test.py`, `report_builder_test.py`, `analyzer_test.py`. All tests use in-memory fixtures. No SSH mocks, no execution mocks. Test each normalizer and validator independently, then test `Analyzer.analyze()` end-to-end with fixture sessions. 174 tests covering CibSectionNormalizer, source group fan-out, all 6 validator strategies, report assembly, and 3 integration scenarios.

**Exit criteria:** Given a set of `EvidenceArtifact` objects and rules, the analyzer produces correct findings. Tested with: (1) HANA HA cluster with fencing disabled, (2) OS config with wrong kernel params, (3) clean system with no findings.

---

### Phase 4: MCP Server + Chat API

Exposes triage capabilities as MCP tools and the conversational endpoint.
Depends on Phases 0–3. Design principles, security model, error handling,
and testing strategy are defined in **Section 4 (MCP Server Design)** —
this phase implements them.

> **Implementation status.** The MCP server is implemented and tested.
> The chat endpoint is planned for Phase 5 wiring.

**MCP files (implemented):**

| File | What it provides | Pattern |
|------|-----------------|---------|
| `src/mcp_server/__init__.py` | Package init | — |
| `src/mcp_server/server.py` | `SapContext` dataclass, `sap_lifespan()` async context manager, `FastMCP` instance (`mcp`), `http_app` ASGI app. Initializes: `JobStore`, `KnowledgeStore`, `ScheduleStore`, `Analyzer`, `TriageExecutor`, `SshCredentialProvider`, `EmbeddingAdapter`, `HybridRetriever`, `LearningPipeline`, `ReportFormatter`. Pre-embeds seed rules and playbooks at startup. | Lifespan DI |
| `src/mcp_server/tools/__init__.py` | Package init — imports `triage`, `staf`, `ops` submodules | — |
| `src/mcp_server/tools/triage.py` | 6 triage tools: `collect_evidence`, `run_analysis`, `query_knowledge`, `get_triage_report`, `list_workspaces`, `get_workspace`. Wired to `HybridRetriever`, `ReportFormatter`, `CbrExtract`, `LearningPipeline`. | Decorator registration |
| `src/mcp_server/tools/staf.py` | 7 STAF tools: `run_staf_test`, `get_job_status`, `get_job_results`, `get_job_events`, `get_job_log`, `list_jobs`, `cancel_job`. | Decorator registration |
| `src/mcp_server/tools/ops.py` | 7 ops tools: `create_schedule`, `list_schedules`, `get_schedule`, `update_schedule`, `delete_schedule`, `trigger_schedule`, `get_schedule_jobs`. | Decorator registration |
| `src/mcp_server/resources.py` | 4 resource templates via `@mcp.resource()`: workspace config, hosts, knowledge query, job results. | URI-template resources |
| `src/mcp_server/prompts.py` | 3 prompt templates via `@mcp.prompt()`: SAP cluster triage, HA test suite, config checks. | Guided workflows |

**Key implementation decisions:**

- **Official MCP Python SDK** (`mcp` v1.26.0) — no hand-rolled JSON-RPC.
  `FastMCP` handles protocol framing, capability negotiation, tool
  discovery, and `inputSchema` generation from Python type annotations.
- **Separate process on port 8001** — decoupled from FastAPI (:8000).
  `stateless_http=True` for production scalability (no session state
  between requests). `json_response=True` for non-streaming responses.
- **Lifespan DI via `SapContext`** — all dependencies initialized in
  `sap_lifespan()`, accessible in tools via
  `ctx.request_context.lifespan_context`. Same pattern as FastAPI's
  lifespan but using the SDK's context propagation.
- **Evidence definitions from KnowledgeStore** — 21 OS-agnostic seed
  definitions in `command_collectors.jsonl`, loaded into SQLite at
  startup, queried by `collect_evidence`. No hardcoded command lists.
- **SSH credential provisioning** — `SshCredentialProvider` (Key Vault
  MSI or local `ssh_key.ppk`) integrated into `collect_evidence`.
  Workspace host resolution from Ansible inventory (`hosts.yaml`).

**Preamble strategy:**

Tool descriptions serve as the preamble for external consumers.
Rich MCP tool `description` fields explain what each tool does,
when to use it, and what to call next. The multi-agent GroupChat
orchestrator (SAP-Router) uses specialist agent instructions to
route turns. No separate preamble builder is needed.

**Not yet implemented (planned):**

| File | Classes | Notes |
|------|---------|-------|
| `src/mcp_server/errors.py` | `ToolError` hierarchy | Typed exceptions → structured MCP errors. Section 4.5. |

**Implemented (moved to Phase 5 — agent wiring):**

| File | Classes | Status |
|------|---------|--------|
| `src/mcp_server/auth.py` | `SapTokenVerifier` | **Implemented** — bearer token validation with configurable issuer/audience |
| `src/mcp_server/rate_limit.py` | `McpRateLimiter` | **Implemented** — per-client token bucket rate limiting |
| `src/mcp_server/validation.py` | `InputValidator` | **Implemented** — Pydantic-based parameter validation with path traversal prevention |
| `src/api/routes/chat.py` | `chat_router` | **Implemented** — 6 REST + SSE endpoints (Phase 5). Module-level DI via `set_chat_service()`. |

**Chat endpoint files:**

| File | Classes | Pattern |
|------|---------|--------|
| `src/api/routes/chat.py` | `chat_router` | REST + SSE endpoints. `POST /api/v1/chat/{id}/messages` (send message), `GET /api/v1/chat/{id}/stream` (SSE streaming), `GET /api/v1/chat/{id}/messages` (history), `GET /api/v1/chat` (list conversations), `POST /api/v1/chat/{id}/archive` (archive). Module-level DI, same pattern as `jobs.py`. |
| `src/core/services/chat.py` | `ChatService` | Bridges REST endpoints with Agent Framework execution. `send_message()` for non-streaming, `stream_response()` for SSE. Converts messages, manages conversation persistence. Full agent wiring implemented in Phase 5. |

Both MCP server and chat router are registered during their respective
process startups — MCP in `sap_lifespan()`, chat in FastAPI's lifespan
(`app.py`).

> **Implementation note — MCP SDK.** Implemented using the official
> `mcp` Python SDK v1.26.0 (`FastMCP` class). The SDK provides:
> JSON-RPC 2.0 framing, Streamable HTTP transport, automatic
> `inputSchema` generation from Python type annotations, capability
> negotiation, and tool/resource/prompt registration via decorators.
> Added to `requirements.txt` as `mcp[cli]>=1.26.0`.

> **Implementation note — SSE.** The existing `GET /api/v1/jobs/{id}/events`
> returns a JSON snapshot, not an SSE stream. True SSE (`text/event-stream`
> with `StreamingResponse`) needs to be built. The `JobWorker.get_job_events()`
> `AsyncGenerator` is a starting point but needs an SSE adapter. Build
> this adapter once and reuse it for both job events and chat streaming.

**Ease of use — connecting external MCP servers:**

A non-developer should be able to connect any MCP server (their
monitoring tool, their CMDB, etc.) by editing a config file:

```yaml
# WORKSPACES/CONFIG/mcp_servers.yaml
servers:
  - name: azure
    url: https://azure-mcp.example.com
    auth: managed_identity
  - name: custom-monitoring
    url: http://monitoring-server:9000/mcp
    auth:
      type: bearer
      token_env: MONITORING_MCP_TOKEN
```

The config lives in `WORKSPACES/CONFIG/` alongside other shared
configuration. No Python code changes required to add a new MCP source.

At startup, the agent discovers tools from all configured external
servers and merges them into a single tool catalog alongside our
built-in SAP tools. No Python code changes required to add a new
MCP source. The config file is documented with examples in the
setup guide.

**Integration with Azure SRE Agent:**
- Tool names follow MCP conventions so Azure SRE Agent auto-discovers them
- Authentication via managed identity (existing `SshCredentialProvider` handles this)
- ReadOnly mode: all tools are read-only by design (no write commands)

**Integration with Azure MCP Server:**
- Azure collectors in evidence definitions delegate to Azure MCP Server tools when available
- Agent layer discovers both our SAP tools and Azure MCP tools in a unified catalog

**Tests:** `tests/mcp_server/server_test.py` + `tools_test.py` — 128
tests covering all 20 tools, workspace listing, job lifecycle,
knowledge query, triage report, evidence collection, analysis, auth,
validation, and rate limiting. All tests use `MagicMock` services in
`SapContext`, `tmp_path` fixtures for workspace files, and direct async
function calls.

**Exit criteria:** MCP server starts on port 8001, all 20 tools are
discoverable via protocol. `collect_evidence` loads definitions from
`KnowledgeStore`, resolves hosts from workspace inventory, provisions SSH
credentials, and delegates to `TriageExecutor`. A test client can call
`collect_evidence` → `run_analysis` → `get_triage_report` (triage path)
and `run_staf_test` → `get_job_status` → `get_job_results` (STAF path)
and `create_schedule` → `trigger_schedule` → `get_schedule_jobs` (ops path).

---

### Phase 5: Agent + Chat UI

LLM-driven orchestration and the conversational frontend. This phase
wires the agent into the chat endpoint (built in Phase 4) and ships the
React components. Depends on Phase 4 (MCP tools + chat API).

**Agent files:**

| File | Classes | Status | Pattern |
|------|---------|--------|---------|
| `src/agents/agent.py` | `SapAgentFactory` | **Implemented** | Multi-agent GroupChat via `GroupChatBuilder` (from `agent-framework-orchestrations`). Creates 3 specialist agents (Triage, STAF, Ops), each with its own `MCPStreamableHTTPTool` scoped to allowed tools, plus an orchestrator agent (SAP-Router) that routes turns. Provides `create_workflow()` and `close()`. |
| `src/agents/cbr.py` | `CbrExtract` | **Wired** | Deterministic pattern extraction from triage findings. `CbrExtract.extract()` is called in `run_analysis` to feed the `LearningPipeline`. `CbrReuse` and `CbrConsolidator` (LLM-powered) were removed — the multi-agent Triage specialist handles playbook adaptation naturally, and the existing keyword/cosine consolidation in `LearningPipeline._consolidate()` is sufficient. |
| `src/agents/context.py` | `ContextManager` | **Implemented** | Token-budget tracking, message summarization, tool-result compaction to prevent context window overflow. Wired into `ChatService`. |
| `src/agents/formatter.py` | `ReportFormatter` | **Implemented** | Deterministic template-based Markdown formatting with optional LLM-enhanced prose. Wired into `get_triage_report` tool. |
| `src/agents/providers/embedding_adapter.py` | `EmbeddingAdapter` | **Implemented** | Sync adapter wrapping Agent Framework's async `BaseEmbeddingClient` to satisfy our `EmbeddingProvider` protocol. Azure OpenAI in production, Ollama for local dev. |
| `src/core/services/chat.py` | `ChatService`, `ChatEvent` | **Implemented** | Bridges REST ↔ agent execution via `Workflow`. `send_message()` for non-streaming, `stream_response()` for SSE. Uses `ContextManager` for token budget. |
| `src/core/services/health.py` | `HealthService` | **Implemented** | Probes MCP servers (HTTP) and LLM endpoint (`max_tokens=1` completions) for deep health checks. Returns `ComponentHealth` + `HealthResponse` models. |
| `src/core/services/mcp_config_loader.py` | `load_mcp_servers_config` | **Wired** | Loads `mcp_servers.yaml` for external MCP server discovery. Called in `app.py` lifespan and passed to `SapAgentFactory.create()`. |
| `src/core/models/mcp_config.py` | `McpServersConfig`, `McpServerEntry`, `SafetyTier` | **Implemented** | Pydantic models for external server configuration. |

> **Architecture change — multi-agent GroupChat.** The original design
> called for a single agent with a `ToolRegistry` bridging MCP tools
> to Agent Framework `FunctionTool`, and a `PreambleBuilder` composing
> 4-layer system prompts. This was replaced with a multi-agent
> GroupChat architecture using `MCPStreamableHTTPTool` (native MCP
> support in Agent Framework). Each specialist agent connects to the
> same MCP server with `allowed_tools` filtering, and an orchestrator
> agent routes user turns. `ToolRegistry` and `PreambleBuilder` were
> dropped — the framework handles tool discovery and routing natively.

**Chat wiring (implemented):**

`ChatService` (`src/core/services/chat.py`) bridges REST endpoints
with `SapAgentFactory`:

1. User sends `POST /api/v1/chat/{conversation_id}/messages` with
   `{"content": "Why is HANA SR not syncing?"}`
2. `ChatService.send_message()` persists the user message, loads
   conversation history from `ConversationStore`, converts `Message`
   objects to Agent Framework messages (filtering out TOOL_CALL /
   TOOL_RESULT), and calls `agent.run(messages)`
3. Agent Framework handles tool-calling internally — plans, calls MCP
   tools, receives results, and produces a final response
4. For streaming: `ChatService.stream_response()` calls
   `agent.run(messages, stream=True)` and yields `ChatEvent` objects
   (type: token/done/error) with `to_sse()` for SSE serialization
5. On completion, the full assistant message is persisted to
   `ConversationStore`

**Chat API endpoints (6 routes in `src/api/routes/chat.py`):**

| Method | Endpoint | Purpose |
|--------|----------|---------|
| `POST` | `/api/v1/chat` | Create conversation |
| `GET` | `/api/v1/chat` | List conversations |
| `GET` | `/api/v1/chat/{id}` | Get conversation |
| `GET` | `/api/v1/chat/{id}/messages` | Get messages |
| `POST` | `/api/v1/chat/{id}/messages` | Send message (non-streaming) |
| `GET` | `/api/v1/chat/{id}/stream` | SSE streaming response |
| `POST` | `/api/v1/chat/{id}/archive` | Archive conversation |

DI wiring in `app.py` lifespan: `SapAgentFactory.create_with_remote()`
is called when `AZURE_OPENAI_ENDPOINT` is set, then injected into
`ChatService`, which is injected into the chat route module via
`set_chat_service()`.

**Frontend (React):**

| File | Component | Notes |
|------|-----------|-------|
| `client/src/components/Chat/ChatWindow.tsx` | `ChatWindow` | Main container. Message list + input box. Subscribes to SSE stream for real-time token display. |
| `client/src/components/Chat/MessageBubble.tsx` | `MessageBubble` | Renders a single message. User messages right-aligned, assistant left-aligned. Tool calls shown as collapsible cards (evidence collected, rules matched). |
| `client/src/components/Chat/TriageCard.tsx` | `TriageCard` | Inline card showing triage findings: severity badge, failure class, matched rule, remediation steps. Expandable to show raw evidence. |
| `client/src/components/Chat/ChatInput.tsx` | `ChatInput` | Text input with send button. Disabled while agent is streaming. Supports workspace selector (which system to triage). |
| `client/src/services/chatApi.ts` | `ChatApiClient` | Fetch wrapper for chat endpoints. `sendMessage()` returns an `EventSource` for SSE streaming. `getHistory()`, `listConversations()`, `archiveConversation()`. |

**Key design:**
- Agent is optional. `Analyzer` + `TriageExecutor` work without it (CLI, Azure SRE Agent, direct API).
- `SapAgentFactory` calls MCP tools (same ones Azure SRE Agent would call). This means the built-in agent is a reference implementation.
- Agent Framework owns the LLM client — no custom `LlmProvider` hierarchy needed.
- No WebSocket — SSE only, reusing the same streaming pattern as `GET /api/v1/jobs/{id}/events`.
- Conversation history is per-workspace (one SAP system per conversation).
- `HealthService` provides deep health probes for MCP servers + LLM endpoint, surfaced via `/healthz`.

**Multi-agent GroupChat (implemented):**

With 20 tools across 3 domains, a single agent degrades tool selection
accuracy. The solution: `SapAgentFactory` builds a GroupChat with 3
specialist agents + 1 orchestrator via `GroupChatBuilder`:

- **Triage-Agent** (6 tools): `collect_evidence`, `run_analysis`,
  `query_knowledge`, `get_triage_report`, `list_workspaces`, `get_workspace`
- **STAF-Agent** (7 tools): `run_staf_test`, `get_job_status`,
  `get_job_results`, `get_job_events`, `get_job_log`, `list_jobs`, `cancel_job`
- **Ops-Agent** (7 tools): `create_schedule`, `list_schedules`,
  `get_schedule`, `update_schedule`, `delete_schedule`, `trigger_schedule`,
  `get_schedule_jobs`
- **SAP-Router** (orchestrator): routes user turns to the right specialist

Each specialist has its own `MCPStreamableHTTPTool` scoped to its allowed
tools. `ChatService` creates a `Workflow` per turn via
`factory.create_workflow()`. Azure SRE Agent already supports subagents
natively — our specialists map 1:1 to SRE Agent subagents.

**Preventing amnesia:**

Three failure modes and their fixes:

1. **Context window overflow.** Long triage conversations with embedded
   tool results can hit 50K+ tokens. Fix: track token count before
   each LLM call. When approaching the limit, summarize older turns
   into a `system` message ("Previous conversation summary: ...") and
   drop the raw messages. The summary preserves what was investigated,
   what was found, and what's still open.

2. **Tool results lost from history.** `tool_call` and `tool_result`
   messages are verbose (full artifact content). Fix: persist them in
   `ConversationStore` for full audit trail, but in the LLM context
   window replace them with compact summaries ("Collected sysctl from
   node1: 47 rules evaluated, 3 failed"). The full data is always
   retrievable via `get_triage_report` MCP tool.

3. **Cross-conversation memory.** A user triages the same system next
   week. Fix: `Conversation` links to `TriageSession` IDs.
   `TriageSession` persists findings and evidence in the database.
   On new conversation start, the agent's system prompt includes:
   "Last triage of this workspace: [date], [N] findings, top issue:
   [X]." The agent can query past sessions via `query_knowledge` to
   recall prior context without replaying old conversations.

Token budget per turn: configurable, default 80% of model context
window. Summarization trigger: when accumulated messages exceed 60%
of budget, compress oldest third.

> **Implementation note — React client.** The `client/` directory has
> `node_modules/` but no source code. Phase 5 frontend work is
> greenfield. Include project scaffolding (Vite + TypeScript + React)
> as the first frontend deliverable before building components.

> **Implementation note — embedding provider.** `EmbeddingProvider`
> (Protocol) and `EmbeddingStore` (sqlite-vec backed) are implemented
> in Phase 1. The `LearningPipeline` accepts an optional
> `EmbeddingStore` + `EmbeddingProvider` and computes embeddings on
> Retain (pattern store). The `HybridRetriever` uses them on Retrieve
> (query time). Phase 5 delivers the `EmbeddingAdapter` — a sync
> wrapper over Agent Framework’s async `BaseEmbeddingClient`. In
> production, `AzureOpenAIEmbeddingClient` is used; for local dev,
> `OpenAIEmbeddingClient` points to Ollama (`base_url=localhost:11434/v1`).
> Seed rules and playbooks are pre-embedded at MCP server startup.
> When no provider is configured, keyword fallback is used — no
> degradation in functionality, only in semantic precision.
>
> **Phase 5 update — CBR Extract (deterministic).** `CbrExtract.extract()`
> builds a `LearnedPattern` from structured triage findings and feeds it
> to `LearningPipeline.process_session()` inside `run_analysis`.
> `CbrReuse` and `CbrConsolidator` (LLM-powered) were removed — the
> multi-agent Triage specialist handles playbook adaptation naturally
> during conversation, and the existing keyword/cosine consolidation in
> `LearningPipeline._consolidate()` is sufficient. The deterministic
> pipeline is the production path; no LLM dependency in the extract
> or consolidation steps.

**Tests:**
- Agent: 110 tests in `tests/agents/` — `SapAgentFactory` creation, `MCPStreamableHTTPTool` wiring, GroupChat workflow construction, CBR classes, `ContextManager` token budgets, `ReportFormatter`, `EmbeddingAdapter` protocol compliance, `ChatService` message persistence and streaming.
- MCP server: 128 tests in `tests/mcp_server/` — all 20 tools, auth, validation, rate limiting, evidence collection, resources.
- Health: included in agent tests — MCP probes, LLM probes, healthy/degraded/unconfigured states.
- Frontend: Component tests for `ChatWindow`, `MessageBubble`, `TriageCard` using React Testing Library. (**Deferred** — frontend not yet built.)

**Exit criteria:** User sends "Why is HANA down?" in the chat → sees streaming response with findings, severity, and remediation → sends follow-up "show me the CIB XML" → agent retrieves and displays the relevant evidence from the existing session.
---

### 8.2 Class Diagram (Key Relationships)

```
    ┌──────────────────┐       ┌──────────────────┐
    │  React Chat UI   │──SSE──│  Chat Routes     │
    │  (port 3000)     │       │  (FastAPI)       │
    └──────────────────┘       └────────┬─────────┘
                                        │ calls
                      ┌─────────────────▼──────────────────┐
                      │  ChatService                       │
                      │  (src/core/services/chat.py)       │
                      │  + ContextManager (token budget)   │
                      └────────┬───────────────────────────┘
                               │ calls
                      ┌────────▼─────────────────────────────┐
                      │  SapAgentFactory → GroupChat Workflow │
                      │  (Agent Framework 1.0.0rc5)           │
                      │  MCPStreamableHTTPTool (3 instances)  │
                      │  SAP-Router → Triage/STAF/Ops agents │
                      └────────┬─────────────────────────────┘
                               │ calls tools via MCP protocol
                      ┌────────▼─────────┐
                      │  MCP Tools (20)  │
                      │  (HTTP on :8001) │
                      └────────┬─────────┘
                               │ delegates to
               ┌───────────────┼───────────────┐
               ▼               ▼               ▼
    ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
    │ TriageExecutor│ │  Analyzer    │ │KnowledgeStore│
    │ (SSH)        │ │ (rules)      │ │ (JSONL+SQL)  │
    └──────┬───────┘ └──────┬───────┘ └──────┬───────┘
           │                │                │
           ▼                ▼                ▼
    ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
    │CommandAllow  │ │RuleValidator │ │HybridRetriever│
    │List          │ │(Strategy)    │ │(Strategy)    │
    └──────────────┘ └──────────────┘ └──────────────┘
           │                │                │
           ▼                ▼                ▼
    ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
    │Evidence      │ │Normalizer    │ │EmbeddingStore│
    │Collector     │ │Registry +    │ │(sqlite-vec)  │
    │(Strategy)    │ │CibSection    │ │+ KnowledgeGraph│
    └──────────────┘ └──────────────┘ └──────────────┘

    Domain services wired into tools:
    ReportFormatter, CbrExtract, LearningPipeline,
    EmbeddingAdapter, SchedulerService

    Support services:
    HealthService (MCP + LLM probes), SchedulerService

    All depend on Phase 0 models:
    TriageSession, EvidenceArtifact, Rule, Playbook,
    SystemProperties, FailureClass, ValidatorResult,
    Conversation, Message
```

### 8.3 What We Reuse (not rebuild)

| Existing class | How it's reused |
|---------------|----------------|
| `ExecutorProtocol` | `TriageExecutor` defines its own `TriageExecutorProtocol` (separate interface) |
| `JobWorker` | Submits triage jobs, enforces workspace locking |
| `JobStore` + `ScheduleStore` | Triage jobs stored alongside existing STAF jobs |
| `SshCredentialProvider` | Same credentials for triage and STAF |
| `Job` model + `JobStatus` enum | Extended with `triage` metadata |
| `StructuredLogger` | All new classes log through it |
| `ObservabilityMiddleware` | Correlation IDs propagate through triage |
| `DANGEROUS_COMMANDS` | Inverted into allow-list for triage |
| `BaseClusterStatusChecker` | CIB XML parsing patterns informed `CibXmlNormalizer` design |
| `log_parser.py` | Log parsing patterns informed `LogNormalizer` design |
| `CollectorStrategy` Protocol | Evidence collectors implement this (context-free, not extending `Collector` ABC) |
| Exception hierarchy | Extended incrementally as phases evolve |
| SSE event streaming (`jobs/{id}/events`) | Same pattern reused for chat token streaming |
| `ConversationStore` | Follows `JobStore` / `ScheduleStore` SQLite pattern |

### 8.4 New Exception Classes

Planned exception hierarchy, delivered incrementally as phases evolve:

```
ExecutionError (existing)
├── TriageError
│   ├── EvidenceCollectionError
│   └── CommandNotAllowedError
├── KnowledgeLoadError
└── AnalysisError
```

### 8.5 Dependency Rules

Enforced by import structure (no runtime checks needed — CI lint catches violations):

```
models/          ← depends on nothing
knowledge/       ← depends on models/
execution/       ← depends on models/ (NOT knowledge/, NOT analyzer/)
analyzer/        ← depends on models/ (NOT execution/, NOT knowledge/)
api/mcp/         ← depends on models/, knowledge/, execution/, analyzer/
agents/          ← depends on api/mcp/ (calls tools, not direct classes)
api/routes/chat  ← depends on models/, agents/, storage/ (NOT analyzer/ directly)
client/          ← depends on api/routes/chat (HTTP+SSE only)
```

The analyzer never imports from execution. The agent calls MCP tools,
not Python classes directly — this keeps it interchangeable with Azure
SRE Agent. The chat layer never calls the analyzer or executor directly —
it goes through the agent, which goes through MCP tools.

---

*Sections 3–6 and 9–12 will be drafted iteratively.*
