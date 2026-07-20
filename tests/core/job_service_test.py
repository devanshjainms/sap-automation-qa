# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for JobApplicationService (P1-WP-005B/C/D)."""

from pathlib import Path
from typing import Any, Generator
from uuid import uuid4

import pytest
from pytest_mock import MockerFixture

from src.core.execution.exceptions import WorkspaceLockError
from src.core.models.job import (
    CreateJobRequest,
    Job,
    JobStatus,
)
from src.core.models.schedule import Schedule
from src.core.services.job_service import JobApplicationService
from src.core.services.scheduler import SchedulerService
from src.core.storage.job_store import JobStore
from src.core.storage.schedule_store import ScheduleStore


class _RecordingExecutionPort:
    """Test double recording submit/cancel calls made through the mandatory
    ``JobExecutionPort``, in place of a real embedded ``JobWorker``.
    """

    def __init__(
        self,
        cancel_result: bool = True,
        submit_error: Exception | None = None,
    ) -> None:
        """Initialize the recording port.

        :param cancel_result: Value returned by :meth:`cancel`.
        :param submit_error: Error raised by :meth:`submit`, if configured.
        """
        self.submitted: list[Job] = []
        self.cancelled: list[tuple[str, str]] = []
        self._cancel_result = cancel_result
        self._submit_error = submit_error

    def submit(self, job: Job) -> None:
        """Record a submission handed off by the application service.

        :param job: Persisted PENDING job handed off for execution.
        """
        if self._submit_error is not None:
            raise self._submit_error
        self.submitted.append(job)

    def cancel(self, job_id: str, reason: str = "Cancelled by user") -> bool:
        """Record a cancellation request.

        :param job_id: Identifier of the job to cancel.
        :param reason: Human-readable cancellation reason.
        :return: The configured cancel result.
        """
        self.cancelled.append((job_id, reason))
        return self._cancel_result


class TestJobApplicationService:
    """Unit tests for the stateless JobApplicationService."""

    @pytest.fixture
    def job_store(self, tmp_path: Path) -> Generator[JobStore, None, None]:
        """Create a temporary job store.

        :param tmp_path: Pytest temporary path.
        :yield: Initialized job store.
        """
        store = JobStore(db_path=tmp_path / "test.db")
        yield store
        store.close()

    @pytest.fixture
    def workspace_summaries(self, mocker: MockerFixture) -> Any:
        """Return a list of workspace summaries.

        :param mocker: Pytest mock fixture.
        :return: Workspace summary list loader.
        """
        ws1 = mocker.MagicMock()
        ws1.workspace_id = "WS-01"
        ws2 = mocker.MagicMock()
        ws2.workspace_id = "WS-02"
        return [ws1, ws2]

    @pytest.fixture
    def workspace_reader(self, mocker: MockerFixture, workspace_summaries: Any) -> Any:
        """Create a mock workspace reader.

        :param mocker: Pytest mock fixture.
        :param workspace_summaries: Available workspace summaries.
        :return: Mock workspace reader.
        """
        reader = mocker.MagicMock()
        reader.list_workspaces.return_value = workspace_summaries
        return reader

    @pytest.fixture
    def execution_port(self) -> _RecordingExecutionPort:
        """Create a recording execution port test double.

        :return: Recording execution port double.
        """
        return _RecordingExecutionPort()

    @pytest.fixture
    def service(
        self,
        job_store: JobStore,
        workspace_reader: Any,
        execution_port: _RecordingExecutionPort,
    ) -> JobApplicationService:
        """Create a JobApplicationService instance wired with the mandatory
        execution port.

        :param job_store: Job store instance.
        :param workspace_reader: Mock workspace reader.
        :param execution_port: Recording execution port double.
        :return: Configured service.
        """
        return JobApplicationService(
            job_store=job_store,
            workspace_reader=workspace_reader,
            execution_port=execution_port,
        )

    def test_list_jobs_empty(self, service: JobApplicationService) -> None:
        """Returns empty list when no jobs exist."""
        result = service.list_jobs()
        assert result.jobs == []
        assert result.total == 0

    def test_list_jobs_with_data(self, service: JobApplicationService, job_store: JobStore) -> None:
        """Returns jobs when data exists."""
        job_store.create(Job(workspace_id="WS-01", test_group="test"))
        result = service.list_jobs()
        assert result.total == 1

    def test_list_jobs_workspace_filter(
        self, service: JobApplicationService, job_store: JobStore
    ) -> None:
        """Filters jobs by workspace_id."""
        job_store.create(Job(workspace_id="WS-01", test_group="test"))
        job_store.create(Job(workspace_id="WS-02", test_group="test"))
        result = service.list_jobs(workspace_id="WS-01")
        assert all(j.workspace_id == "WS-01" for j in result.jobs)

    def test_list_jobs_status_filter(
        self, service: JobApplicationService, job_store: JobStore
    ) -> None:
        """Filters jobs by status."""
        job = Job(workspace_id="WS-01", test_group="test")
        job.start()
        job.complete({"ok": True})
        job_store.create(job)
        result = service.list_jobs(status=JobStatus.COMPLETED)
        assert all(j.status == JobStatus.COMPLETED for j in result.jobs)

    def test_list_jobs_invalid_status_raises(self, service: JobApplicationService) -> None:
        """Raises ValueError for invalid status string."""
        with pytest.raises(ValueError, match="Invalid status"):
            service.list_jobs(status="BOGUS")

    def test_list_jobs_active_only(
        self, service: JobApplicationService, job_store: JobStore
    ) -> None:
        """Returns only active jobs when active_only=True."""
        pending = Job(workspace_id="WS-01", test_group="test")
        job_store.create(pending)
        done = Job(workspace_id="WS-02", test_group="test")
        done.start()
        done.complete({"ok": True})
        job_store.create(done)
        result = service.list_jobs(active_only=True)
        assert all(not j.is_terminal for j in result.jobs)

    def test_list_jobs_limit(self, service: JobApplicationService, job_store: JobStore) -> None:
        """Respects the limit parameter."""
        for i in range(10):
            job_store.create(Job(workspace_id=f"WS-{i}", test_group="test"))
        result = service.list_jobs(limit=3)
        assert len(result.jobs) <= 3

    def test_get_job_found(self, service: JobApplicationService, job_store: JobStore) -> None:
        """Returns job when it exists."""
        job = Job(workspace_id="WS-01", test_group="test")
        job_store.create(job)
        result = service.get_job(str(job.id))
        assert result is not None
        assert result.id == job.id

    def test_get_job_missing_returns_none(self, service: JobApplicationService) -> None:
        """Returns None when job not found."""
        result = service.get_job(str(uuid4()))
        assert result is None

    @pytest.mark.asyncio
    async def test_submit_job_success(
        self, service: JobApplicationService, job_store: JobStore
    ) -> None:
        """Submits a job for a valid workspace and persists as PENDING."""
        request = CreateJobRequest(
            workspace_id="WS-01",
            test_group="ConfigurationChecks",
            test_ids=["t1"],
        )
        job = await service.submit_job(request)
        assert job.workspace_id == "WS-01"
        assert job.status == JobStatus.PENDING
        persisted = job_store.get(job.id)
        assert persisted is not None
        assert persisted.status == JobStatus.PENDING

    @pytest.mark.asyncio
    async def test_submit_job_unknown_workspace(self, service: JobApplicationService) -> None:
        """Raises ValueError for unknown workspace."""
        request = CreateJobRequest(
            workspace_id="NONEXISTENT",
            test_group="ConfigurationChecks",
        )
        with pytest.raises(ValueError, match="not found"):
            await service.submit_job(request)

    @pytest.mark.asyncio
    async def test_submit_job_invalid_test_group(self, service: JobApplicationService) -> None:
        """Raises ValueError for unknown test_group."""
        request = CreateJobRequest(
            workspace_id="WS-01",
            test_group="NONEXISTENT_GROUP",
        )
        with pytest.raises(ValueError, match="Unknown test_group"):
            await service.submit_job(request)

    @pytest.mark.asyncio
    async def test_submit_job_offline_requires_test_group(
        self, service: JobApplicationService
    ) -> None:
        """Raises ValueError when offline=true without test_group."""
        request = CreateJobRequest(
            workspace_id="WS-01",
            offline=True,
        )
        with pytest.raises(ValueError, match="requires a test_group"):
            await service.submit_job(request)

    @pytest.mark.asyncio
    async def test_submit_job_offline_ineligible_group(
        self, service: JobApplicationService
    ) -> None:
        """Raises ValueError for ineligible offline group."""
        request = CreateJobRequest(
            workspace_id="WS-01",
            test_group="ConfigurationChecks",
            offline=True,
        )
        with pytest.raises(ValueError, match="not eligible for offline"):
            await service.submit_job(request)

    @pytest.mark.asyncio
    async def test_submit_job_workspace_locked(
        self,
        service: JobApplicationService,
        job_store: JobStore,
    ) -> None:
        """Raises WorkspaceLockError for duplicate workspace submission."""
        # Create a pending job for WS-01 (acquires workspace lock)
        job_store.create(Job(workspace_id="WS-01", test_group="test"))

        request = CreateJobRequest(
            workspace_id="WS-01",
            test_group="ConfigurationChecks",
        )
        with pytest.raises(WorkspaceLockError):
            await service.submit_job(request)

    @pytest.mark.asyncio
    async def test_cancel_job_success(
        self,
        service: JobApplicationService,
        execution_port: _RecordingExecutionPort,
        job_store: JobStore,
    ) -> None:
        """Cancels a running job via the mandatory execution port."""
        job = Job(workspace_id="WS-01", test_group="test")
        job_store.create(job)
        result = await service.cancel_job(str(job.id), "test reason")
        assert result is True
        assert execution_port.cancelled == [(str(job.id), "test reason")]

    @pytest.mark.asyncio
    async def test_cancel_job_not_found(
        self,
        job_store: JobStore,
        workspace_reader: Any,
    ) -> None:
        """Returns False when the execution port reports no tracked job."""
        service = JobApplicationService(
            job_store=job_store,
            workspace_reader=workspace_reader,
            execution_port=_RecordingExecutionPort(cancel_result=False),
        )
        result = await service.cancel_job(str(uuid4()), "reason")
        assert result is False

    def test_get_job_events_found(
        self, service: JobApplicationService, job_store: JobStore
    ) -> None:
        """Returns events for an existing job."""
        job = Job(workspace_id="WS-01", test_group="test")
        job.start()
        job_store.create(job)
        events = service.get_job_events(str(job.id))
        assert events is not None
        assert len(events) >= 1

    def test_get_job_events_not_found(self, service: JobApplicationService) -> None:
        """Returns None for missing job."""
        result = service.get_job_events(str(uuid4()))
        assert result is None

    @pytest.mark.asyncio
    async def test_submit_preserves_actor_fields(self, service: JobApplicationService) -> None:
        """Actor, approval_ref, and incident_ticket are preserved."""
        request = CreateJobRequest(
            workspace_id="WS-01",
            test_group="ConfigurationChecks",
            actor="mcp-agent",
            approval_ref="CHG-99",
            incident_ticket="INC-1",
        )
        job = await service.submit_job(request)
        assert job.actor == "mcp-agent"
        assert job.approval_ref == "CHG-99"
        assert job.incident_ticket == "INC-1"

    # --- Mandatory execution-port coordination (RD-021/RD-022) ---

    @pytest.mark.asyncio
    async def test_submit_job_invokes_execution_port_exactly_once(
        self,
        service: JobApplicationService,
        execution_port: _RecordingExecutionPort,
    ) -> None:
        """submit_job creates the job once and hands it to the execution
        port exactly once — no distributed poll/claim step exists."""
        request = CreateJobRequest(
            workspace_id="WS-01",
            test_group="ConfigurationChecks",
            test_ids=["t1"],
        )
        job = await service.submit_job(request)

        assert len(execution_port.submitted) == 1
        assert execution_port.submitted[0].id == job.id
        assert execution_port.submitted[0].status == JobStatus.PENDING

    @pytest.mark.asyncio
    async def test_submit_failure_marks_job_failed_and_releases_workspace(
        self,
        job_store: JobStore,
        workspace_reader: Any,
    ) -> None:
        """A scheduling failure must not orphan a PENDING job or workspace lock."""
        service = JobApplicationService(
            job_store=job_store,
            workspace_reader=workspace_reader,
            execution_port=_RecordingExecutionPort(
                submit_error=RuntimeError("task scheduling failed")
            ),
        )
        request = CreateJobRequest(
            workspace_id="WS-01",
            test_group="ConfigurationChecks",
            test_ids=["t1"],
        )

        with pytest.raises(RuntimeError, match="task scheduling failed"):
            await service.submit_job(request)

        failed_jobs = job_store.get_history()
        assert len(failed_jobs) == 1
        assert failed_jobs[0].status == JobStatus.FAILED
        assert failed_jobs[0].error == "Failed to schedule job: task scheduling failed"
        assert job_store.get_active_for_workspace("WS-01") is None

    @pytest.mark.asyncio
    async def test_scheduler_submission_reaches_same_execution_port(
        self,
        service: JobApplicationService,
        execution_port: _RecordingExecutionPort,
        tmp_path: Path,
    ) -> None:
        """Scheduler-triggered submissions flow through the same narrow
        port/service as FastAPI — SchedulerService only depends on
        ``JobApplicationService.submit_job``, so there is no second
        ownership path."""
        schedule_store = ScheduleStore(db_path=tmp_path / "schedule.db")
        try:
            schedule = schedule_store.create(
                Schedule(
                    name="Nightly",
                    cron_expression="0 0 * * *",
                    workspace_ids=["WS-01"],
                    test_group="ConfigurationChecks",
                    enabled=True,
                )
            )
            scheduler = SchedulerService(
                schedule_store=schedule_store,
                job_submitter=service,
                check_interval_seconds=60,
            )
            job_ids = await scheduler.trigger_now(schedule.id)
        finally:
            schedule_store.close()

        assert len(job_ids) == 1
        assert len(execution_port.submitted) == 1
        assert str(execution_port.submitted[0].id) == job_ids[0]
