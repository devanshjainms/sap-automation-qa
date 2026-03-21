# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""STAF tools — test execution, job management, log retrieval.

Tools registered here:
    - ``run_staf_test``
    - ``get_job_status``
    - ``get_job_results``
    - ``list_jobs``
    - ``cancel_job``
    - ``get_job_events``
    - ``get_job_log``
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import httpx
from mcp.server.fastmcp import Context
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.session import ServerSession

from src.mcp_server.server import SapContext, mcp

logger = logging.getLogger(__name__)


@mcp.tool()
async def run_staf_test(
    workspace_id: str,
    test_group: str,
    test_ids: list[str] | None = None,
    ctx: Context[ServerSession, SapContext] | None = None,
) -> dict[str, Any]:
    """Trigger a STAF test — configuration check or HA functional test.

    Valid ``test_group`` values:
    - ``ConfigurationChecks``
    - ``DatabaseHighAvailability``
    - ``SCSHighAvailability``

    Returns a ``job_id``. Poll with ``get_job_status`` until complete,
    then call ``get_job_results`` for artifacts.
    """
    assert ctx is not None
    sap: SapContext = ctx.request_context.lifespan_context

    await ctx.info(f"Submitting STAF test: {test_group} on {workspace_id}")

    payload: dict[str, Any] = {
        "workspace_id": workspace_id,
        "test_group": test_group,
    }
    if test_ids:
        payload["test_ids"] = test_ids

    async with httpx.AsyncClient(base_url=sap.core_api_url, timeout=30.0) as client:
        resp = await client.post("/api/v1/jobs", json=payload)
        resp.raise_for_status()
        job_data = resp.json()

    return {
        "job_id": job_data.get("id", job_data.get("job_id", "")),
        "workspace_id": workspace_id,
        "test_group": test_group,
        "status": job_data.get("status", "submitted"),
    }


@mcp.tool()
async def get_job_status(
    job_id: str,
    ctx: Context[ServerSession, SapContext] | None = None,
) -> dict[str, Any]:
    """Poll a running STAF job's status.

    Returns current status, timing, and workspace info. Use after
    ``run_staf_test`` to check when a job completes.
    """
    assert ctx is not None
    sap: SapContext = ctx.request_context.lifespan_context

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


@mcp.tool()
async def get_job_results(
    job_id: str,
    ctx: Context[ServerSession, SapContext] | None = None,
) -> dict[str, Any]:
    """Retrieve results for a completed STAF job.

    Returns exit code, result data, and event log. Only available after
    the job reaches a terminal state.
    """
    assert ctx is not None
    sap: SapContext = ctx.request_context.lifespan_context

    job = sap.validator.job_id(job_id)

    return {
        "job_id": str(job.id),
        "status": job.status,
        "is_terminal": job.is_terminal,
        "exit_code": (job.result or {}).get("exit_code"),
        "result": job.result,
        "events": [e.model_dump(mode="json") for e in job.events],
    }


@mcp.tool()
async def list_jobs(
    workspace_id: str = "",
    status: str = "",
    active_only: bool = False,
    limit: int = 50,
    ctx: Context[ServerSession, SapContext] | None = None,
) -> dict[str, Any]:
    """List STAF jobs with optional filters.

    Filter by ``workspace_id``, ``status``, or ``active_only``.
    Returns up to ``limit`` jobs (default 50).
    """
    assert ctx is not None
    sap: SapContext = ctx.request_context.lifespan_context
    store = sap.job_store
    limit = max(1, min(limit, 200))

    if active_only:
        jobs = store.get_active(workspace_id=workspace_id or None)
    else:
        status_filter = None
        if status:
            from src.core.models.job import JobStatus

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


@mcp.tool()
async def cancel_job(
    job_id: str,
    reason: str = "",
    ctx: Context[ServerSession, SapContext] | None = None,
) -> dict[str, Any]:
    """Cancel a running STAF job.

    Sends a cancellation signal. Only works on jobs that are not
    yet in a terminal state.
    """
    assert ctx is not None
    sap: SapContext = ctx.request_context.lifespan_context

    async with httpx.AsyncClient(
        base_url=sap.core_api_url, timeout=30.0
    ) as client:
        resp = await client.post(
            f"/api/v1/jobs/{job_id}/cancel",
            json={"reason": reason},
        )
        if resp.status_code == 404:
            raise ToolError(f"Job {job_id} not found or not running")
        resp.raise_for_status()

    return {"status": "cancelled", "job_id": job_id}


@mcp.tool()
async def get_job_events(
    job_id: str,
    ctx: Context[ServerSession, SapContext] | None = None,
) -> dict[str, Any]:
    """Get execution events for a STAF job.

    Returns the ordered event log (state transitions, progress
    updates) for the specified job.
    """
    assert ctx is not None
    sap: SapContext = ctx.request_context.lifespan_context
    job = sap.validator.job_id(job_id)

    return {
        "job_id": str(job.id),
        "events": [e.model_dump(mode="json") for e in job.events],
        "total": len(job.events),
    }


@mcp.tool()
async def get_job_log(
    job_id: str,
    tail: int = 0,
    ctx: Context[ServerSession, SapContext] | None = None,
) -> dict[str, Any]:
    """Retrieve the Ansible process log for a STAF job.

    Set ``tail`` > 0 to return only the last N lines. Returns the
    full log by default.
    """
    assert ctx is not None
    sap: SapContext = ctx.request_context.lifespan_context
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
