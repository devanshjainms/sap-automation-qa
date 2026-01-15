# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Schedules API routes."""

from datetime import datetime
from pathlib import Path
from typing import Optional

from apscheduler.triggers.cron import CronTrigger
from fastapi import APIRouter, HTTPException, Query

from src.agents.execution.schedule_store import ScheduleStore
from src.agents.models.schedule import (
    Schedule,
    ScheduleListResponse,
    CreateScheduleRequest,
    UpdateScheduleRequest,
)
from src.agents.observability import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/schedules", tags=["schedules"])

_schedule_store: Optional[ScheduleStore] = None


def get_schedule_store() -> ScheduleStore:
    """Get or create schedule store singleton.

    :returns: ScheduleStore instance
    :rtype: ScheduleStore
    """
    global _schedule_store
    if _schedule_store is None:
        storage_path = Path("data/schedules.json")
        _schedule_store = ScheduleStore(storage_path=storage_path)
        logger.info(f"ScheduleStore initialized at {storage_path}")
    return _schedule_store


def set_schedule_store(store: ScheduleStore) -> None:
    """Set the schedule store instance.

    :param store: ScheduleStore instance to use
    :type store: ScheduleStore

    """
    global _schedule_store
    _schedule_store = store
    logger.info("ScheduleStore injected via set_schedule_store")


@router.post("", response_model=Schedule, status_code=201)
async def create_schedule(request: CreateScheduleRequest) -> Schedule:
    """Create a new schedule.

    :param request: Schedule creation request
    :type request: CreateScheduleRequest
    :returns: Created schedule
    :rtype: Schedule
    :raises HTTPException: If validation fails
    """
    store = get_schedule_store()

    try:
        try:
            CronTrigger.from_crontab(request.cron_expression)
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid cron expression '{request.cron_expression}': {str(e)}",
            )
        if not request.workspace_ids:
            raise HTTPException(status_code=400, detail="At least one workspace_id is required")
        schedule = Schedule(
            name=request.name,
            description=request.description,
            cron_expression=request.cron_expression,
            timezone=request.timezone,
            workspace_ids=request.workspace_ids,
            test_group=request.test_group,
            test_ids=request.test_ids,
            enabled=request.enabled,
        )
        if schedule.enabled:
            trigger = CronTrigger.from_crontab(schedule.cron_expression)
            next_run = trigger.get_next_fire_time(None, datetime.utcnow())
            schedule.next_run_time = next_run
        created_schedule = store.create(schedule)

        logger.info(
            f"Created schedule '{created_schedule.name}' (ID: {created_schedule.id}) "
            f"for {len(created_schedule.workspace_ids)} workspace(s)"
        )

        return created_schedule

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to create schedule: {e}", exc_info=e)
        raise HTTPException(status_code=500, detail=f"Failed to create schedule: {e}")


@router.get("", response_model=ScheduleListResponse)
async def list_schedules(
    enabled: Optional[bool] = Query(None, description="Filter by enabled status")
) -> ScheduleListResponse:
    """List all schedules.

    :param enabled: Optional filter for enabled/disabled schedules
    :type enabled: Optional[bool]
    :returns: List of schedules
    :rtype: ScheduleListResponse
    """
    store = get_schedule_store()

    try:
        schedules = store.list(enabled_only=enabled if enabled is not None else False)

        logger.info(f"Listed {len(schedules)} schedules (enabled={enabled})")

        return ScheduleListResponse(schedules=schedules, count=len(schedules))

    except Exception as e:
        logger.error(f"Failed to list schedules: {e}", exc_info=e)
        raise HTTPException(status_code=500, detail=f"Failed to list schedules: {e}")


@router.get("/{schedule_id}", response_model=Schedule)
async def get_schedule(schedule_id: str) -> Schedule:
    """Get a specific schedule by ID.

    :param schedule_id: Schedule ID
    :type schedule_id: str
    :returns: Schedule
    :rtype: Schedule
    :raises HTTPException: If schedule not found
    """
    store = get_schedule_store()

    try:
        schedule = store.get(schedule_id)

        if not schedule:
            raise HTTPException(status_code=404, detail=f"Schedule {schedule_id} not found")

        logger.info(f"Retrieved schedule {schedule_id}")

        return schedule

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get schedule {schedule_id}: {e}", exc_info=e)
        raise HTTPException(status_code=500, detail=f"Failed to get schedule: {e}")


@router.put("/{schedule_id}", response_model=Schedule)
async def update_schedule(schedule_id: str, request: UpdateScheduleRequest) -> Schedule:
    """Update an existing schedule.

    :param schedule_id: Schedule ID
    :type schedule_id: str
    :param request: Update request
    :type request: UpdateScheduleRequest
    :returns: Updated schedule
    :rtype: Schedule
    :raises HTTPException: If schedule not found or validation fails
    """
    store = get_schedule_store()

    try:
        schedule = store.get(schedule_id)

        if not schedule:
            raise HTTPException(status_code=404, detail=f"Schedule {schedule_id} not found")
        if request.name is not None:
            schedule.name = request.name
        if request.description is not None:
            schedule.description = request.description
        if request.cron_expression is not None:
            try:
                CronTrigger.from_crontab(request.cron_expression)
            except Exception as e:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid cron expression '{request.cron_expression}': {str(e)}",
                )
            schedule.cron_expression = request.cron_expression
        if request.timezone is not None:
            schedule.timezone = request.timezone
        if request.workspace_ids is not None:
            if not request.workspace_ids:
                raise HTTPException(status_code=400, detail="At least one workspace_id is required")
            schedule.workspace_ids = request.workspace_ids
        if request.test_group is not None:
            schedule.test_group = request.test_group
        if request.test_ids is not None:
            schedule.test_ids = request.test_ids
        if request.enabled is not None:
            schedule.enabled = request.enabled
        if schedule.enabled:
            trigger = CronTrigger.from_crontab(schedule.cron_expression)
            next_run = trigger.get_next_fire_time(None, datetime.utcnow())
            schedule.next_run_time = next_run
        else:
            schedule.next_run_time = None
        updated_schedule = store.update(schedule)

        logger.info(f"Updated schedule {schedule_id}")

        return updated_schedule

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to update schedule {schedule_id}: {e}", exc_info=e)
        raise HTTPException(status_code=500, detail=f"Failed to update schedule: {e}")


@router.delete("/{schedule_id}", status_code=204)
async def delete_schedule(schedule_id: str) -> None:
    """Delete a schedule.

    :param schedule_id: Schedule ID
    :type schedule_id: str
    :raises HTTPException: If schedule not found
    """
    store = get_schedule_store()

    try:
        store.delete(schedule_id)

        logger.info(f"Deleted schedule {schedule_id}")

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to delete schedule {schedule_id}: {e}", exc_info=e)
        raise HTTPException(status_code=500, detail=f"Failed to delete schedule: {e}")


@router.post("/{schedule_id}/toggle", response_model=Schedule)
async def toggle_schedule(schedule_id: str) -> Schedule:
    """Toggle a schedule's enabled state.

    :param schedule_id: Schedule ID
    :type schedule_id: str
    :returns: Updated schedule
    :rtype: Schedule
    :raises HTTPException: If schedule not found
    """
    store = get_schedule_store()

    try:
        schedule = store.get(schedule_id)

        if not schedule:
            raise HTTPException(status_code=404, detail=f"Schedule {schedule_id} not found")
        schedule.enabled = not schedule.enabled
        if schedule.enabled:
            trigger = CronTrigger.from_crontab(schedule.cron_expression)
            next_run = trigger.get_next_fire_time(None, datetime.utcnow())
            schedule.next_run_time = next_run
        else:
            schedule.next_run_time = None
        updated_schedule = store.update(schedule)

        logger.info(
            f"Toggled schedule {schedule_id} to {'enabled' if schedule.enabled else 'disabled'}"
        )

        return updated_schedule

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to toggle schedule {schedule_id}: {e}", exc_info=e)
        raise HTTPException(status_code=500, detail=f"Failed to toggle schedule: {e}")
