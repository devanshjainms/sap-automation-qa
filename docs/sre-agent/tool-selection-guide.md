# Tool Selection Guide — STAF MCP for Azure SRE Agent

> **Applies to:** Azure SRE Agent Plugin Marketplace / custom MCP integrations
>
> Azure SRE Agent enforces an **80-tool budget** across all connected MCP
> servers and built-in connectors.  This guide helps you choose the right set
> of STAF tools based on your operational needs.

---

## Understanding the 80-Tool Budget

Azure SRE Agent exposes tools to the underlying LLM through a single unified
tool list.  The total number of tools across **all** sources cannot exceed 80:

| Source | Typical count | Notes |
|--------|---------------|-------|
| Built-in tools | ~25 | Alert context, Azure Resource Graph, Kusto, etc. |
| GitHub connector | ~10 | Repo search, issue/PR operations |
| Other connectors | varies | ServiceNow, PagerDuty, Datadog, etc. |
| **STAF MCP tools** | **12–26** | Depends on your tier (see below) |

> **Budget math:** If you use built-in (25) + GitHub (10) + STAF Tier 1 (12),
> you consume **47 of 80** slots, leaving 33 for other connectors.

Plan your tool selection carefully.  Every tool added to the agent's context
consumes prompt tokens and competes for the model's attention.  Fewer, more
focused tools lead to more reliable agent behavior.

---

## Tier 1: Essential — 12 tools

> **Full triage + testing capability.**  Sufficient for most production
> operations teams.  Covers the complete investigate → test → report workflow.

| # | Tool | Description | Why essential |
|---|------|-------------|---------------|
| 1 | `list_workspaces` | List all configured SAP workspaces | Entry point for every workflow — agent must discover workspaces |
| 2 | `get_workspace` | Get detailed configuration for a single workspace | Needed to read SID, topology, OS family, and node details |
| 3 | `collect_evidence` | Run evidence collection on a workspace | Gathers cluster status, resource states, and system metrics |
| 4 | `list_evidence_catalog` | List available evidence collectors | Lets the agent discover what evidence types are available |
| 5 | `run_analysis` | Analyze collected evidence and produce findings | Core triage step — turns raw evidence into severity-ranked findings |
| 6 | `get_triage_report` | Retrieve the full triage report for an investigation | Final output of the triage workflow |
| 7 | `query_knowledge` | Search the SAP knowledge base | Provides context on SAP best practices, known issues, and resolution steps |
| 8 | `search_logs` | Search Ansible and system logs with filters | Essential for root-cause investigation of failures |
| 9 | `run_staf_test` | Execute a STAF test (config check or HA test) | Runs validation or failover tests on demand |
| 10 | `get_job_status` | Check the status of a running or completed job | Required to poll async test execution |
| 11 | `get_job_results` | Retrieve test results and findings | Needed to interpret test outcomes |
| 12 | `list_jobs` | List jobs with optional workspace/status filters | Provides job history and lets the agent find related past runs |

---

## Tier 2: Standard — +8 tools (20 total)

> **Adds debugging and feedback capability.**  Recommended for teams that want
> the agent to dig deeper into failures and record investigation outcomes.

| # | Tool | Description | Why useful |
|---|------|-------------|------------|
| 13 | `get_job_log` | Retrieve raw Ansible log output for a job | Deep debugging — lets the agent read exact command output |
| 14 | `get_job_events` | Stream or retrieve job execution events (SSE) | Real-time monitoring of long-running tests |
| 15 | `cancel_job` | Cancel a running job | Safety valve — lets the agent abort a stuck or misbehaving test |
| 16 | `get_evidence_output` | Retrieve raw output from a specific evidence collector | Detailed inspection of individual evidence artifacts |
| 17 | `run_evidence_collector` | Run a single evidence collector on demand | Targeted evidence collection without running the full catalog |
| 18 | `record_investigation_outcome` | Record the outcome and resolution of an investigation | Closes the feedback loop — builds institutional knowledge |
| 19 | `trigger_schedule` | Immediately trigger an existing STAF schedule | On-demand execution of pre-configured recurring tests |
| 20 | `list_schedules` | List all STAF schedules | Lets the agent check what recurring tasks are already configured |

---

## Tier 3: Full — +6 tools (26 total)

> **Adds schedule management and investigation feedback.**  For platform
> engineering teams that want the agent to manage the full STAF lifecycle.

| # | Tool | Description | Why useful |
|---|------|-------------|------------|
| 21 | `create_schedule` | Create a new STAF cron schedule | Agent can set up recurring tests autonomously |
| 22 | `get_schedule` | Get details of a specific schedule | Inspect schedule configuration and next-run time |
| 23 | `update_schedule` | Update an existing schedule (cron, parameters) | Agent can adjust schedules based on findings |
| 24 | `delete_schedule` | Delete a schedule | Clean up obsolete schedules |
| 25 | `get_schedule_jobs` | List jobs spawned by a specific schedule | Correlate scheduled runs with their outcomes |
| 26 | `add_investigation_feedback` | Add follow-up feedback to a completed investigation | Refine triage quality over time with human corrections |

---

## Recommendation

| Team profile | Tier | Tools | Budget used |
|-------------|------|-------|-------------|
| **Most users** — ops teams responding to incidents | Tier 1 | 12 | 12 |
| **Power users** — teams debugging failures and tracking outcomes | Tier 2 | 20 | 20 |
| **Full admin** — platform engineers managing the full lifecycle | Tier 3 | 26 | 26 |

**Start with Tier 1.**  The 12 essential tools cover the complete
investigate → test → report workflow.  Add Tier 2 tools only if you find the
agent needs deeper debugging or feedback capabilities during real incidents.

> **Note on scheduling:** Azure SRE Agent has its own native scheduling
> (Builder → Scheduled Tasks).  For **new** recurring workflows, prefer the
> SRE Agent's native scheduler over STAF's `schedule_ops` tools.  Use STAF
> schedules only for backward compatibility with existing cron configurations
> or when you need STAF-specific scheduling features (e.g., workspace-scoped
> cron with parameter overrides).

---

## Configuring Tools in the SRE Agent Portal

1. Go to **Builder** → **MCP Servers** → select the **staf-mcp** server.
2. Under **Exposed Tools**, toggle on the tools for your chosen tier.
3. Click **Save**.  The tool budget counter at the top updates in real time.
4. If you exceed 80 tools total, the portal will warn you.  Disable
   lower-priority tools from other connectors to make room.

> **Tip:** You can change the exposed tool set at any time without
> redeploying the MCP server.  The change takes effect on the agent's next
> invocation.
