# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Lightweight scheduler service for multi-workspace job execution."""

import asyncio
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional
from apscheduler.triggers.cron import CronTrigger
from src.agents.models.job import ExecutionJob
from src.agents.observability import get_logger

if TYPE_CHECKING:
    from src.agents.execution.schedule_store import ScheduleStore
    from src.agents.execution.worker import JobWorker

logger = get_logger(__name__)


class SchedulerService:
    """Lightweight scheduler for multi-workspace automated test execution.

    Periodically checks schedules and triggers jobs for each configured workspace.
    """

    def __init__(
        self,
        schedule_store: "ScheduleStore",
        job_worker: "JobWorker",
        check_interval_seconds: int = 60,
    ) -> None:
        """Initialize the scheduler service.

        :param schedule_store: Store for loading schedules
        :type schedule_store: ScheduleStore
        :param job_worker: Worker for submitting jobs
        :type job_worker: JobWorker
        :param check_interval_seconds: Interval between schedule checks
        :type check_interval_seconds: int
        """
        self._schedule_store = schedule_store
        self._job_worker = job_worker
        self._check_interval = check_interval_seconds
        self._running = False
        self._task: Optional[asyncio.Task] = None

        logger.info(f"SchedulerService initialized (check_interval={check_interval_seconds}s)")

    async def start(self) -> None:
        """Start the scheduler background task."""
        if self._running:
            logger.warning("SchedulerService already running")
            return

        self._running = True
        self._task = asyncio.create_task(self._scheduler_loop())
        logger.info("SchedulerService started")

    async def stop(self) -> None:
        """Stop the scheduler background task."""
        if not self._running:
            return

        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        logger.info("SchedulerService stopped")

    async def _scheduler_loop(self) -> None:
        """Main scheduler loop that checks schedules periodically."""
        logger.info("Scheduler loop started")

        while self._running:
            try:
                await self._check_and_trigger_schedules()
            except Exception as e:
                logger.error(f"Error in scheduler loop: {e}", exc_info=e)

            await asyncio.sleep(self._check_interval)

    async def _check_and_trigger_schedules(self) -> None:
        """Check all schedules and trigger due jobs."""
        now = datetime.now(timezone.utc)
        logger.debug(f"Checking schedules at {now.isoformat()}")

        try:
            schedules = self._schedule_store.list(enabled_only=True)
            logger.debug(f"Found {len(schedules)} enabled schedules")

            for schedule in schedules:
                if schedule.next_run_time and schedule.next_run_time <= now:
                    await self._trigger_schedule(schedule)

        except Exception as e:
            logger.error(f"Failed to check and trigger schedules: {e}", exc_info=e)

    async def _trigger_schedule(self, schedule) -> None:
        """Trigger a schedule - creates one job per workspace.

        :param schedule: Schedule to trigger
        :type schedule: Schedule
        """
        try:
            current_schedule = self._schedule_store.get(schedule.id)
            if not current_schedule:
                logger.warning(
                    f"Schedule '{schedule.name}' (ID: {schedule.id}) "
                    + f"was deleted before trigger. Skipping."
                )
                return

            if not current_schedule.enabled:
                logger.info(
                    f"Schedule '{schedule.name}' (ID: {schedule.id}) "
                    + f"was disabled before trigger. Skipping."
                )
                return
            schedule = current_schedule

            logger.info(
                f"Triggering schedule '{schedule.name}' (ID: {schedule.id}) "
                f"for {len(schedule.workspace_ids)} workspace(s)"
            )

            job_ids = []
            for workspace_id in schedule.workspace_ids:
                try:
                    job = ExecutionJob(
                        workspace_id=workspace_id,
                        triggered_by_schedule_id=schedule.id,
                        test_group=schedule.test_group,
                        test_ids=schedule.test_ids,
                        metadata={
                            "scheduled": True,
                            "schedule_name": schedule.name,
                            "schedule_id": schedule.id,
                        },
                    )

                    submitted_job = await self._job_worker.submit_job(job)
                    job_ids.append(str(submitted_job.id))

                    logger.info(
                        f"Triggered job {submitted_job.id} for workspace {workspace_id} "
                        f"(schedule: {schedule.name})"
                    )

                except Exception as e:
                    logger.error(
                        f"Failed to trigger job for workspace {workspace_id} "
                        f"(schedule {schedule.id}): {e}",
                        exc_info=e,
                    )
                    schedule.consecutive_failures += 1
            schedule.last_run_time = datetime.now(timezone.utc)
            schedule.last_run_job_ids = job_ids
            schedule.total_runs += 1
            if schedule.enabled:
                trigger = CronTrigger.from_crontab(schedule.cron_expression)
                next_run = trigger.get_next_fire_time(None, datetime.utcnow())
                schedule.next_run_time = next_run
            else:
                schedule.next_run_time = None
            if schedule.consecutive_failures >= 3:
                logger.error(
                    f"Disabling schedule '{schedule.name}' after "
                    f"{schedule.consecutive_failures} consecutive failures"
                )
                schedule.enabled = False
                schedule.next_run_time = None
            if job_ids:
                schedule.consecutive_failures = 0

            try:
                self._schedule_store.update(schedule)
            except ValueError as e:
                logger.warning(
                    f"Schedule '{schedule.name}' (ID: {schedule.id}) not found during update. "
                    f"Likely deleted by user. Jobs already submitted: {job_ids}"
                )
                return

            logger.info(
                f"Schedule '{schedule.name}' triggered successfully. "
                f"Created {len(job_ids)} job(s). Next run: {schedule.next_run_time}"
            )

        except Exception as e:
            logger.error(
                f"Failed to trigger schedule '{schedule.name}': {e}",
                exc_info=e,
            )
