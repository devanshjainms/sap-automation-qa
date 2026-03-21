# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Ops tools — schedule CRUD, triggering, and schedule-job listing.

Tools registered here:
    - ``create_schedule``
    - ``list_schedules``
    - ``get_schedule``
    - ``update_schedule``
    - ``delete_schedule``
    - ``trigger_schedule``
    - ``get_schedule_jobs``
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from apscheduler.triggers.cron import CronTrigger
from mcp.server.fastmcp import Context
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.session import ServerSession

from src.core.models.schedule import Schedule
from src.core.services.scheduler import SchedulerService
from src.mcp_server.server import SapContext, mcp

logger = logging.getLogger(__name__)


@mcp.tool()
async def create_schedule(
    name: str,
    cron_expression: str,
    workspace_ids: list[str],
    test_group: str = "",
    description: str = "",
    timezone_name: str = "UTC",
    enabled: bool = True,
    ctx: Context[ServerSession, SapContext] | None = None,
) -> dict[str, Any]:
    """Create a cron schedule for recurring STAF tests.

    The ``cron_expression`` must be a valid 5-field cron string
    (e.g. ``0 2 * * *`` for daily at 02:00).
    """
    assert ctx is not None
    sap: SapContext = ctx.request_context.lifespan_context

    try:
        CronTrigger.from_crontab(cron_expression)
    except Exception as exc:
        raise ToolError(f"Invalid cron expression: {exc}") from exc

    if not workspace_ids:
        raise ToolError("At least one workspace_id is required")

    schedule = Schedule(
        name=name,
        description=description,
        cron_expression=cron_expression,
        timezone=timezone_name,
        workspace_ids=workspace_ids,
        test_group=test_group or None,
        enabled=enabled,
    )
    schedule.next_run_time = SchedulerService.compute_next_run(schedule)
    created = sap.schedule_store.create(schedule)

    return {
        "schedule_id": created.id,
        "name": created.name,
        "cron_expression": created.cron_expression,
        "enabled": created.enabled,
        "next_run_time": (
            created.next_run_time.isoformat()
            if created.next_run_time
            else None
        ),
    }


@mcp.tool()
async def list_schedules(
    enabled_only: bool = False,
    ctx: Context[ServerSession, SapContext] | None = None,
) -> dict[str, Any]:
    """List all STAF schedules.

    Set ``enabled_only`` to filter out disabled schedules.
    """
    assert ctx is not None
    sap: SapContext = ctx.request_context.lifespan_context

    schedules = sap.schedule_store.list(enabled_only=enabled_only)
    return {
        "schedules": [
            {
                "schedule_id": s.id,
                "name": s.name,
                "cron_expression": s.cron_expression,
                "workspace_ids": s.workspace_ids,
                "test_group": s.test_group,
                "enabled": s.enabled,
                "next_run_time": (
                    s.next_run_time.isoformat()
                    if s.next_run_time
                    else None
                ),
            }
            for s in schedules
        ],
        "total": len(schedules),
    }


@mcp.tool()
async def get_schedule(
    schedule_id: str,
    ctx: Context[ServerSession, SapContext] | None = None,
) -> dict[str, Any]:
    """Get details of a specific schedule."""
    assert ctx is not None
    sap: SapContext = ctx.request_context.lifespan_context

    schedule = sap.schedule_store.get(schedule_id)
    if not schedule:
        raise ToolError(f"Schedule {schedule_id} not found")

    return schedule.model_dump(mode="json")


@mcp.tool()
async def update_schedule(
    schedule_id: str,
    name: str = "",
    cron_expression: str = "",
    timezone_name: str = "",
    enabled: bool | None = None,
    workspace_ids: list[str] | None = None,
    test_group: str = "",
    ctx: Context[ServerSession, SapContext] | None = None,
) -> dict[str, Any]:
    """Update an existing schedule.

    Only pass the fields you want to change. Unchanged fields
    keep their current values.
    """
    assert ctx is not None
    sap: SapContext = ctx.request_context.lifespan_context

    schedule = sap.schedule_store.get(schedule_id)
    if not schedule:
        raise ToolError(f"Schedule {schedule_id} not found")

    if cron_expression:
        try:
            CronTrigger.from_crontab(cron_expression)
        except Exception as exc:
            raise ToolError(f"Invalid cron expression: {exc}") from exc
        schedule.cron_expression = cron_expression

    if name:
        schedule.name = name
    if timezone_name:
        schedule.timezone = timezone_name
    if enabled is not None:
        schedule.enabled = enabled
    if workspace_ids is not None:
        schedule.workspace_ids = workspace_ids
    if test_group:
        schedule.test_group = test_group

    schedule.updated_at = datetime.now(timezone.utc)
    schedule.next_run_time = SchedulerService.compute_next_run(schedule)
    updated = sap.schedule_store.update(schedule)

    return {
        "schedule_id": updated.id,
        "name": updated.name,
        "enabled": updated.enabled,
        "next_run_time": (
            updated.next_run_time.isoformat()
            if updated.next_run_time
            else None
        ),
    }


@mcp.tool()
async def delete_schedule(
    schedule_id: str,
    ctx: Context[ServerSession, SapContext] | None = None,
) -> dict[str, Any]:
    """Delete a schedule.

    Removes the schedule permanently. Running jobs spawned by this
    schedule are not affected.
    """
    assert ctx is not None
    sap: SapContext = ctx.request_context.lifespan_context

    if not sap.schedule_store.delete(schedule_id):
        raise ToolError(f"Schedule {schedule_id} not found")

    return {"status": "deleted", "schedule_id": schedule_id}


@mcp.tool()
async def trigger_schedule(
    schedule_id: str,
    ctx: Context[ServerSession, SapContext] | None = None,
) -> dict[str, Any]:
    """Trigger a schedule immediately.

    Creates jobs for all workspaces in the schedule, bypassing
    the cron timer.
    """
    assert ctx is not None
    sap: SapContext = ctx.request_context.lifespan_context

    if sap.scheduler_service is None:
        raise ToolError("Scheduler service is not available")

    try:
        job_ids = await sap.scheduler_service.trigger_now(schedule_id)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
    except PermissionError as exc:
        raise ToolError(str(exc)) from exc

    return {
        "status": "triggered",
        "schedule_id": schedule_id,
        "job_ids": job_ids,
    }


@mcp.tool()
async def get_schedule_jobs(
    schedule_id: str,
    limit: int = 50,
    ctx: Context[ServerSession, SapContext] | None = None,
) -> dict[str, Any]:
    """Get jobs triggered by a specific schedule.

    Returns the most recent jobs (up to ``limit``) that were
    created by this schedule.
    """
    assert ctx is not None
    sap: SapContext = ctx.request_context.lifespan_context

    schedule = sap.schedule_store.get(schedule_id)
    if not schedule:
        raise ToolError(f"Schedule {schedule_id} not found")

    limit = max(1, min(limit, 200))
    jobs = sap.job_store.get_jobs_for_schedule(schedule_id, limit=limit)

    return {
        "schedule_id": schedule_id,
        "jobs": [
            {
                "job_id": str(j.id),
                "status": j.status,
                "workspace_id": j.workspace_id,
            }
            for j in jobs
        ],
        "total": len(jobs),
    }
