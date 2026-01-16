# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Async job worker for background test execution.

This module provides the JobWorker class that executes tests
in the background and emits events for real-time status updates.
"""

import asyncio
import json
from datetime import datetime
from typing import Any, AsyncGenerator, Callable, Optional, TYPE_CHECKING
from uuid import UUID

from src.agents.models.job import ExecutionJob, JobEvent, JobEventType, JobStatus
from src.agents.execution.store import JobStore
from src.agents.execution.exceptions import WorkspaceLockError
from src.agents.observability import get_logger

if TYPE_CHECKING:
    from src.agents.plugins.execution import ExecutionPlugin

logger = get_logger(__name__)


class JobWorker:
    """Background worker for async test execution.

    Executes jobs from the job store and emits events for
    real-time status updates via SSE.
    """

    def __init__(
        self,
        job_store: JobStore,
        execution_plugin: "ExecutionPlugin",
    ) -> None:
        """Initialize the job worker.

        :param job_store: Job store for persistence
        :type job_store: JobStore
        :param execution_plugin: Plugin for test execution
        :type execution_plugin: ExecutionPlugin
        """
        self.job_store = job_store
        self.execution_plugin = execution_plugin
        self._running_jobs: dict[str, asyncio.Task] = {}
        self._event_queues: dict[str, asyncio.Queue[JobEvent]] = {}

        logger.info("JobWorker initialized")

    async def submit_job(self, job: ExecutionJob) -> ExecutionJob:
        """Submit a job for async execution.

        Handles both pre-created jobs (from workspace triggers) and new jobs (from scheduler).
        Enforces workspace-level locking for all submission paths.

        :param job: Job to execute (may or may not be persisted)
        :type job: ExecutionJob
        :returns: The submitted job
        :rtype: ExecutionJob
        :raises WorkspaceLockError: If workspace already has an active job
        """
        active_job = self.job_store.get_active_job_for_workspace(job.workspace_id)
        if active_job and active_job.id != job.id:
            logger.warning(f"Workspace {job.workspace_id} already has active job {active_job.id}")
            raise WorkspaceLockError(
                workspace_id=job.workspace_id,
                active_job_id=str(active_job.id),
            )

        if job.id is None:
            job = self.job_store.create_job(
                workspace_id=job.workspace_id,
                test_ids=job.test_ids,
                test_id=job.test_id,
                test_group=job.test_group,
                metadata=job.metadata,
                triggered_by_schedule_id=job.triggered_by_schedule_id,
            )
        self._event_queues[str(job.id)] = asyncio.Queue()

        task = asyncio.create_task(self._execute_job(job))
        self._running_jobs[str(job.id)] = task

        logger.info(f"Submitted job {job.id} for async execution")
        return job

    async def get_job_events(
        self, job_id: str, timeout: float = 60.0
    ) -> AsyncGenerator[JobEvent, None]:
        """Get events for a job as an async generator.

        This is used for SSE streaming.

        :param job_id: Job ID to get events for
        :type job_id: str
        :param timeout: Timeout in seconds to wait for events
        :type timeout: float
        :yields: Job events as they occur
        :rtype: AsyncGenerator[JobEvent, None]
        """
        queue = self._event_queues.get(job_id)

        if not queue:
            job = self.job_store.get_job(job_id)
            if job:
                for event in job.events:
                    yield event
            return

        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=timeout)
                    yield event

                    if event.event_type in (
                        JobEventType.COMPLETED,
                        JobEventType.FAILED,
                        JobEventType.CANCELLED,
                    ):
                        break

                except asyncio.TimeoutError:
                    yield JobEvent(
                        event_type=JobEventType.LOG,
                        message="Waiting for execution progress...",
                    )

        finally:
            if job_id in self._event_queues:
                del self._event_queues[job_id]

    async def cancel_job(self, job_id: str, reason: str = "Cancelled by user") -> bool:
        """Cancel a running job.

        :param job_id: Job ID to cancel
        :type job_id: str
        :param reason: Cancellation reason
        :type reason: str
        :returns: True if job was cancelled
        :rtype: bool
        """
        task = self._running_jobs.get(job_id)
        if task and not task.done():
            task.cancel()

            job = self.job_store.get_job(job_id)
            if job:
                event = job.cancel(reason)
                self.job_store.update_job(job)
                await self._emit_event(job_id, event)

            logger.info(f"Cancelled job {job_id}: {reason}")
            return True

        return False

    async def _emit_event(self, job_id: str, event: JobEvent) -> None:
        """Emit an event to the job's queue and store."""
        queue = self._event_queues.get(job_id)
        if queue:
            await queue.put(event)

        self.job_store._notify_event(job_id, event)

    async def _execute_job(self, job: ExecutionJob) -> None:
        """Execute a job in the background.

        :param job: Job to execute
        :type job: ExecutionJob
        """
        try:
            event = job.start()
            self.job_store.update_job(job)
            await self._emit_event(str(job.id), event)

            results = []
            test_ids = job.test_ids or ([job.test_id] if job.test_id else [])

            if not test_ids and job.test_group:
                test_ids = [""]
                logger.info(
                    f"Running entire {job.test_group} playbook for workspace {job.workspace_id}"
                )
            elif not test_ids:
                raise ValueError("No tests specified for execution")

            job.total_steps = len(test_ids)

            for idx, test_id in enumerate(test_ids):
                if job.status == JobStatus.CANCELLED:
                    break

                step_name = f"Test: {test_id}"
                event = job.step_started(idx, step_name, f"Starting {test_id}...")
                self.job_store.update_job(job)
                await self._emit_event(str(job.id), event)

                try:
                    result_json = await asyncio.to_thread(
                        self.execution_plugin.run_test_by_id,
                        workspace_id=job.workspace_id,
                        test_id=test_id,
                        test_group=job.test_group or "CONFIG_CHECKS",
                    )

                    result = json.loads(result_json)

                    if "error" in result:
                        event = job.step_failed(idx, step_name, result["error"])
                        await self._emit_event(str(job.id), event)
                        results.append(
                            {"test_id": test_id, "status": "failed", "error": result["error"]}
                        )
                    else:
                        # Capture stdout/stderr from the result
                        if result.get("stdout"):
                            job.raw_stdout = (job.raw_stdout or "") + f"\n=== {test_id or job.test_group} ===\n" + result["stdout"]
                        if result.get("stderr"):
                            job.raw_stderr = (job.raw_stderr or "") + f"\n=== {test_id or job.test_group} ===\n" + result["stderr"]
                        
                        # Update job in database with captured output
                        self.job_store.update_job(job)
                        
                        event = job.step_completed(
                            idx, step_name, f"{test_id or job.test_group} completed successfully"
                        )
                        await self._emit_event(str(job.id), event)
                        results.append(
                            {
                                "test_id": test_id,
                                "status": result.get("status", "success"),
                                "result": result,
                            }
                        )

                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    event = job.step_failed(idx, step_name, str(e))
                    await self._emit_event(str(job.id), event)
                    results.append({"test_id": test_id, "status": "failed", "error": str(e)})

                self.job_store.update_job(job)

            if job.status != JobStatus.CANCELLED:
                all_success = all(r.get("status") == "success" for r in results)
                summary = {
                    "results": results,
                    "status": "success" if all_success else "partial",
                    "tests_run": len(results),
                    "tests_passed": sum(1 for r in results if r.get("status") == "success"),
                    "tests_failed": sum(1 for r in results if r.get("status") == "failed"),
                }

                if all_success:
                    event = job.complete(
                        summary, f" All {len(results)} tests completed successfully!"
                    )
                else:
                    passed = summary["tests_passed"]
                    failed = summary["tests_failed"]
                    event = job.complete(summary, f" Completed: {passed} passed, {failed} failed")

                self.job_store.update_job(job)
                await self._emit_event(str(job.id), event)

        except asyncio.CancelledError:
            logger.info(f"Job {job.id} was cancelled")
            event = job.cancel("Job cancelled")
            self.job_store.update_job(job)
            await self._emit_event(str(job.id), event)

        except Exception as e:
            logger.error(f"Job {job.id} failed: {e}")
            event = job.fail(str(e))
            self.job_store.update_job(job)
            await self._emit_event(str(job.id), event)

        finally:
            if str(job.id) in self._running_jobs:
                del self._running_jobs[str(job.id)]

    def get_running_job_ids(self) -> list[str]:
        """Get IDs of currently running jobs.

        :returns: List of job IDs
        :rtype: list[str]
        """
        return list(self._running_jobs.keys())


class JobEventEmitter:
    """Utility class for formatting job events as chat messages."""

    @staticmethod
    def format_event_as_message(event: JobEvent) -> str:
        """Format a job event as a user-friendly message.

        :param event: Job event to format
        :type event: JobEvent
        :returns: Formatted message string
        :rtype: str
        """
        progress_str = ""

        if event.step_index is not None and event.total_steps:
            progress_str = f" [{event.step_index + 1}/{event.total_steps}]"

        if event.progress_percent is not None:
            progress_str += f" ({event.progress_percent:.0f}%)"

        return f"{progress_str} {event.message}"

    @staticmethod
    def format_job_summary(job: ExecutionJob) -> str:
        """Format a job summary as a user-friendly message.

        :param job: Job to summarize
        :type job: ExecutionJob
        :returns: Formatted summary string
        :rtype: str
        """
        lines = []

        lines.append(f"**Job Status: {job.status.value.upper()}**")
        lines.append(f"   Workspace: `{job.workspace_id}`")

        if job.test_ids:
            lines.append(f"   Tests: {', '.join(job.test_ids)}")

        if job.status == JobStatus.RUNNING:
            lines.append(f"   Progress: {job.progress_percent:.0f}%")
            if job.current_step:
                lines.append(f"   Current step: {job.current_step}")

        if job.started_at:
            end_time = job.completed_at or datetime.utcnow()
            duration = (end_time - job.started_at).total_seconds()
            lines.append(f"   Duration: {duration:.1f}s")

        if job.result:
            result = job.result
            if "tests_passed" in result:
                lines.append(
                    f"   Results: {result['tests_passed']} passed, "
                    f"{result.get('tests_failed', 0)} failed"
                )

        if job.error_message:
            lines.append(f"   Error: {job.error_message}")

        return "\n".join(lines)
