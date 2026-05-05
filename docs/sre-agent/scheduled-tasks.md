# Scheduled Task Templates for Azure SRE Agent

> **Applies to:** Azure SRE Agent with STAF MCP integration
>
> These templates define recurring proactive tasks that the SRE Agent runs on a
> schedule.  Each section includes the natural-language prompt to paste into the
> agent, the recommended schedule, and portal setup instructions.

---

## Setup (common to all tasks)

1. Open the **Azure SRE Agent** portal → **Builder** → **Scheduled Tasks**.
2. Click **+ New Task**.
3. Fill in the **Name**, **Schedule** (cron expression or human-readable), and
   **Prompt** fields as shown below.
4. Under **Agent**, select the **sap_expert** custom agent (or whichever agent
   has the STAF MCP tools attached).
5. Under **Notification**, optionally link a Teams channel or email group to
   receive the task report.
6. Click **Save & Enable**.

> **Tip:** All prompts assume the STAF MCP server is connected and the
> `list_workspaces`, `collect_evidence`, `run_analysis`, and `run_staf_test`
> tools are available.  See [tool-selection-guide.md](tool-selection-guide.md)
> for the minimum tool set.

---

## 1. Daily SAP Health Check

| Field    | Value |
|----------|-------|
| **Name** | Daily SAP Health Check |
| **Schedule** | Every day at 08:00 local time (`0 8 * * *`) |
| **Autonomy** | Review (agent reports findings; no remediation) |

### Prompt

```text
Perform a daily health check across all SAP workspaces.

1. Call list_workspaces to enumerate every configured SAP workspace.
2. For each workspace:
   a. Call collect_evidence with the default evidence catalog to gather
      current cluster status, resource states, and system metrics.
   b. Call run_analysis on the collected evidence to identify any
      critical or high-severity findings.
3. Compile a summary report that includes:
   - Workspace name and SID.
   - Number of critical, high, medium, and low findings.
   - A one-line summary for every critical or high finding.
4. If previous-day results are available (check the most recent
   investigation outcome for each workspace), compare today's findings
   with yesterday's and highlight any NEW issues or RESOLVED issues.
5. If all workspaces are healthy, confirm "All SAP systems healthy —
   no critical or high findings."
```

### Portal setup notes

- **Where:** Builder → Scheduled Tasks → + New Task.
- **Recommended time:** 08:00 local, before the operations team's daily
  standup so results are ready for review.
- **Notification:** Link to the SAP operations Teams channel or email
  distribution list for immediate visibility.

---

## 2. Weekly HA Configuration Validation

| Field    | Value |
|----------|-------|
| **Name** | Weekly HA Configuration Validation |
| **Schedule** | Every Sunday at 02:00 local time (`0 2 * * 0`) |
| **Autonomy** | Review |

### Prompt

```text
Run non-destructive HA configuration validation across all SAP workspaces.

1. Call list_workspaces to enumerate every configured SAP workspace.
2. For each workspace:
   a. Call run_staf_test with test_type="configuration_check" and
      test_cases=["ha-config"] to validate the current HA configuration
      against best practices.
   b. Wait for the job to complete (poll get_job_status every 30 seconds).
   c. Call get_job_results to retrieve the validation report.
3. Compile a drift report:
   - For each workspace, list any configuration parameters that deviate
     from the recommended values.
   - Flag any NEW drift since the previous weekly run (if available in
     the investigation history).
   - Severity-rank findings: critical drift (affects failover), high
     drift (affects performance or monitoring), medium/low (cosmetic or
     informational).
4. If no drift is detected in any workspace, confirm "All HA
   configurations are compliant — no drift detected."

IMPORTANT: This is a READ-ONLY validation. Do NOT execute any failover
tests, resource migrations, or cluster modifications.
```

### Portal setup notes

- **Where:** Builder → Scheduled Tasks → + New Task.
- **Recommended time:** Sunday 02:00 local during low-traffic hours.
  Configuration checks are non-destructive but can generate additional
  load on cluster nodes.
- **Notification:** Link to the SAP Basis / HA engineering team channel.

---

## 3. Monthly HA Functional Test

| Field    | Value |
|----------|-------|
| **Name** | Monthly HA Functional Test |
| **Schedule** | First Sunday of every month at 02:00 local time (`0 2 1-7 * 0`) |
| **Autonomy** | Review (**mandatory** — human approval required before failover) |

### Prompt

```text
Execute controlled HA functional tests during the approved maintenance
window.

1. Call list_workspaces to enumerate every configured SAP workspace.
2. For each workspace:
   a. Call run_staf_test with test_type="ha_test" and
      test_cases=["resource-migration"] to perform a controlled
      resource migration (failover and failback).
   b. Monitor the test by polling get_job_status every 60 seconds
      until the job completes or times out (max 45 minutes per
      workspace).
   c. Call get_job_results to retrieve the full test report.
3. Compile a results summary:
   - Workspace name and SID.
   - Test outcome: PASSED, FAILED, or TIMED_OUT.
   - For any FAILED or TIMED_OUT test, include:
     • The specific step that failed.
     • Relevant error messages or log excerpts.
     • Recommended next steps for investigation.
4. Flag any test failures for immediate human investigation. Include
   a direct link to the STAF job log (get_job_log) for each failure.

IMPORTANT:
- This test performs actual resource failovers. Run ONLY during an
  approved maintenance window.
- The autonomy level MUST remain "review" — do not switch to
  "autonomous" for failover tests.
- If any prerequisite check fails (e.g., cluster not healthy before
  test), SKIP that workspace and report the reason.
```

### Portal setup notes

- **Where:** Builder → Scheduled Tasks → + New Task.
- **Recommended time:** First Sunday of the month at 02:00 local,
  aligned with your organization's maintenance window.  Adjust the cron
  expression if your window differs.
- **Autonomy:** Must be set to **Review**.  The agent proposes the test
  execution; a human must approve before any failover runs.
- **Notification:** Link to both the SAP Basis team channel and the
  on-call engineer's pager/email for immediate awareness.
- **Pre-requisite:** Ensure a valid maintenance window is approved in
  your change management system before enabling this task.
