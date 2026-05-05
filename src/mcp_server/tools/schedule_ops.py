# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Schedule ops — schedule CRUD, triggering, and schedule-job listing."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from apscheduler.triggers.cron import CronTrigger
from mcp.server.fastmcp import Context
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.session import ServerSession
from mcp.types import ToolAnnotations

from src.core.models.schedule import Schedule
from src.core.services.scheduler import SchedulerService
from src.mcp_server.server import SapContext, mcp
from src.mcp_server.tools._helpers import (
    get_sap_context,
    ICON_CALENDAR,
    ICON_CLIPBOARD,
    ICON_EDIT,
    ICON_LIST,
    ICON_PLAY,
    ICON_TRASH,
)

logger = logging.getLogger(__name__)


@staticmethod
@mcp.tool(
    name="create_schedule",
    title="Create Schedule",
    description=(
        "Create a cron schedule for recurring STAF tests. "
        "The cron_expression must be a valid 5-field cron string "
        "(e.g. '0 2 * * *' for daily at 02:00)."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=False,
    ),
    icons=[ICON_CALENDAR],
    structured_output=False,
)
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
    """Create a cron schedule for recurring STAF tests."""
    sap = get_sap_context(ctx)

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
        "next_run_time": (created.next_run_time.isoformat() if created.next_run_time else None),
    }


@staticmethod
@mcp.tool(
    name="list_schedules",
    title="List Schedules",
    description=("List all STAF schedules. Set enabled_only to filter " "out disabled schedules."),
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
    icons=[ICON_LIST],
    structured_output=False,
)
async def list_schedules(
    enabled_only: bool = False,
    ctx: Context[ServerSession, SapContext] | None = None,
) -> dict[str, Any]:
    """List all STAF schedules with optional enabled filter."""
    sap = get_sap_context(ctx)

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
                "next_run_time": (s.next_run_time.isoformat() if s.next_run_time else None),
            }
            for s in schedules
        ],
        "total": len(schedules),
    }


@staticmethod
@mcp.tool(
    name="get_schedule",
    title="Get Schedule",
    description="Get details of a specific schedule.",
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
    icons=[ICON_CALENDAR],
    structured_output=False,
)
async def get_schedule(
    schedule_id: str,
    ctx: Context[ServerSession, SapContext] | None = None,
) -> dict[str, Any]:
    """Get details of a specific schedule."""
    sap = get_sap_context(ctx)

    schedule = sap.schedule_store.get(schedule_id)
    if not schedule:
        raise ToolError(f"Schedule {schedule_id} not found")

    return schedule.model_dump(mode="json")


@staticmethod
@mcp.tool(
    name="update_schedule",
    title="Update Schedule",
    description=(
        "Update an existing schedule. Only pass the fields you want to "
        "change. Unchanged fields keep their current values."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
    icons=[ICON_EDIT],
    structured_output=False,
)
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
    """Update fields on an existing schedule."""
    sap = get_sap_context(ctx)

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
        "next_run_time": (updated.next_run_time.isoformat() if updated.next_run_time else None),
    }


@staticmethod
@mcp.tool(
    name="delete_schedule",
    title="Delete Schedule",
    description=(
        "Delete a schedule permanently. Running jobs spawned by this " "schedule are not affected."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=True,
        openWorldHint=False,
    ),
    icons=[ICON_TRASH],
    structured_output=False,
)
async def delete_schedule(
    schedule_id: str,
    ctx: Context[ServerSession, SapContext] | None = None,
) -> dict[str, Any]:
    """Delete a schedule permanently."""
    sap = get_sap_context(ctx)

    if not sap.schedule_store.delete(schedule_id):
        raise ToolError(f"Schedule {schedule_id} not found")

    return {"status": "deleted", "schedule_id": schedule_id}


@staticmethod
@mcp.tool(
    name="trigger_schedule",
    title="Trigger Schedule",
    description=(
        "Trigger a schedule immediately. Creates jobs for all workspaces "
        "in the schedule, bypassing the cron timer."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=False,
    ),
    icons=[ICON_PLAY],
    structured_output=False,
)
async def trigger_schedule(
    schedule_id: str,
    ctx: Context[ServerSession, SapContext] | None = None,
) -> dict[str, Any]:
    """Trigger a schedule immediately, bypassing the cron timer."""
    sap = get_sap_context(ctx)

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


@staticmethod
@mcp.tool(
    name="get_schedule_jobs",
    title="Get Schedule Jobs",
    description=(
        "Get jobs triggered by a specific schedule. Returns the most "
        "recent jobs (up to limit) created by this schedule."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
    icons=[ICON_CLIPBOARD],
    structured_output=False,
)
async def get_schedule_jobs(
    schedule_id: str,
    limit: int = 50,
    ctx: Context[ServerSession, SapContext] | None = None,
) -> dict[str, Any]:
    """Get recent jobs triggered by a specific schedule."""
    sap = get_sap_context(ctx)

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
