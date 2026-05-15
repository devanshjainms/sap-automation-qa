# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Job ops — STAF job status, results, listing, cancellation, events, logs."""

from __future__ import annotations
import logging
from pathlib import Path
from typing import Any
from mcp.server.fastmcp import Context
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.session import ServerSession
from mcp.types import ToolAnnotations
from src.core.models.job import JobStatus
from src.mcp_server.server import SapContext, mcp
from src.mcp_server.tools._helpers import get_sap_context

logger = logging.getLogger(__name__)


@staticmethod
@mcp.tool(
    name="get_job_status",
    title="Get Job Status",
    description=(
        "Poll a STAF job's status. Returns current status (pending, running, "
        "completed, failed, cancelled), timing, and workspace info. "
        "After run_staf_test, poll this until is_terminal=true. "
        "HA tests typically take 8-15 minutes — do not poll more than once "
        "per 30 seconds. Once completed, call get_job_log to read the "
        "detailed per-check findings and report them to the user."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
    structured_output=False,
)
async def get_job_status(
    job_id: str,
    ctx: Context[ServerSession, SapContext] | None = None,
) -> dict[str, Any]:
    """Poll a running STAF job's current status and timing."""
    sap = get_sap_context(ctx)

    job = sap.validator.job_id(job_id)

    return {
        "job_id": str(job.id),
        "status": job.status,
        "workspace_id": job.workspace_id,
        "test_group": job.test_group,
        "is_terminal": job.is_terminal,
        "created_at": (job.created_at.isoformat() if job.created_at else None),
        "started_at": (job.started_at.isoformat() if job.started_at else None),
        "completed_at": (job.completed_at.isoformat() if job.completed_at else None),
    }


@staticmethod
@mcp.tool(
    name="get_job_results",
    title="Get Job Results",
    description=(
        "Retrieve the summary result for a completed STAF job. Returns pass/fail "
        "counts, exit code, and event timeline. Use this to check whether the test "
        "passed or failed. For the detailed per-check findings (which specific HA "
        "properties were validated and their values), call get_job_log instead."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
    structured_output=False,
)
async def get_job_results(
    job_id: str,
    ctx: Context[ServerSession, SapContext] | None = None,
) -> dict[str, Any]:
    """Retrieve results and event log for a completed STAF job."""
    sap = get_sap_context(ctx)

    job = sap.validator.job_id(job_id)

    return {
        "job_id": str(job.id),
        "status": job.status,
        "is_terminal": job.is_terminal,
        "exit_code": (job.result or {}).get("exit_code"),
        "result": job.result,
        "events": [e.model_dump(mode="json") for e in job.events],
    }


@staticmethod
@mcp.tool(
    name="list_jobs",
    title="List Jobs",
    description=(
        "List STAF jobs with optional filters. Filter by workspace_id, "
        "status, or active_only. Returns up to limit jobs (default 50)."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
    structured_output=False,
)
async def list_jobs(
    workspace_id: str = "",
    status: str = "",
    active_only: bool = False,
    limit: int = 50,
    ctx: Context[ServerSession, SapContext] | None = None,
) -> dict[str, Any]:
    """List STAF jobs with optional workspace/status filters."""
    sap = get_sap_context(ctx)
    store = sap.job_store
    limit = max(1, min(limit, 200))

    if active_only:
        jobs = store.get_active(workspace_id=workspace_id or None)
    else:
        status_filter = None
        if status:
            try:
                status_filter = JobStatus(status)
            except ValueError:
                raise ToolError(f"Invalid status '{status}'")
        jobs = store.get_history(
            workspace_id=workspace_id or None,
            status=status_filter,
            limit=limit,
        )
        active = store.get_active(workspace_id=workspace_id or None)
        jobs = active + jobs

    jobs = jobs[:limit]
    return {
        "jobs": [
            {
                "job_id": str(j.id),
                "status": j.status,
                "workspace_id": j.workspace_id,
                "test_group": j.test_group,
                "is_terminal": j.is_terminal,
            }
            for j in jobs
        ],
        "total": len(jobs),
    }


@staticmethod
@mcp.tool(
    name="cancel_job",
    title="Cancel Job",
    description=(
        "Cancel a running STAF job. Sends a cancellation signal. "
        "Only works on jobs not yet in a terminal state."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=True,
        openWorldHint=False,
    ),
    structured_output=False,
)
async def cancel_job(
    job_id: str,
    reason: str = "",
    ctx: Context[ServerSession, SapContext] | None = None,
) -> dict[str, Any]:
    """Cancel a running STAF job via cancellation signal."""
    sap = get_sap_context(ctx)

    success = await sap.job_worker.cancel_job(job_id, reason or "Cancelled by user")
    if not success:
        raise ToolError(f"Job {job_id} not found or not running")

    return {"status": "cancelled", "job_id": job_id}


@staticmethod
@mcp.tool(
    name="get_job_events",
    title="Get Job Events",
    description=(
        "Get execution events for a STAF job. Returns the ordered event "
        "log (state transitions, progress updates) for the specified job."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
    structured_output=False,
)
async def get_job_events(
    job_id: str,
    ctx: Context[ServerSession, SapContext] | None = None,
) -> dict[str, Any]:
    """Get the ordered event log for a STAF job."""
    sap = get_sap_context(ctx)
    job = sap.validator.job_id(job_id)

    return {
        "job_id": str(job.id),
        "events": [e.model_dump(mode="json") for e in job.events],
        "total": len(job.events),
    }


@staticmethod
@mcp.tool(
    name="get_job_log",
    title="Get Job Log",
    description=(
        "Retrieve the detailed structured test log for a STAF job. "
        "The log contains JSON-lines with per-check results: each line has "
        "test_case_name, status (PASSED/FAILED/WARNING), parameter name, "
        "actual value, expected value, and severity. Use this to report "
        "the specific HA configuration findings to the user — not just "
        "pass/fail but WHAT was checked and WHAT the values were. "
        "Set tail > 0 to return only the last N lines."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
    structured_output=False,
)
async def get_job_log(
    job_id: str,
    tail: int = 0,
    ctx: Context[ServerSession, SapContext] | None = None,
) -> dict[str, Any]:
    """Retrieve the Ansible process log for a STAF job."""
    sap = get_sap_context(ctx)
    job = sap.validator.job_id(job_id)

    if not job.log_file:
        raise ToolError(f"No log file recorded for job {job_id}")

    log_path = Path(job.log_file)
    if not log_path.exists():
        raise ToolError(f"Log file not found on disk: {log_path}")

    content = log_path.read_text(encoding="utf-8")
    if tail > 0:
        lines = content.splitlines()
        content = "\n".join(lines[-tail:])

    return {
        "job_id": str(job.id),
        "log": content,
        "line_count": len(content.splitlines()),
    }
