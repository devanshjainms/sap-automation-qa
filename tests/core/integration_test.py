# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Deterministic integration tests for the durable job execution flow."""

from __future__ import annotations

import asyncio
import shutil
import threading
from pathlib import Path
from typing import Any, Generator
from uuid import uuid4

import pytest
from pytest_mock import MockerFixture

from src.core.contracts.workspace import WorkspaceBackendProtocol
from src.core.execution.ssh_provider import SshCredentialProvider
from src.core.execution.worker import JobWorker
from src.core.models.job import CreateJobRequest, Job, JobEventType, JobStatus
from src.core.models.storage import StorageContext
from src.core.services.job_service import JobApplicationService
from src.core.storage.factory import create_storage_context
from src.core.storage.workspace import create_workspace_backend

_POLL_INTERVAL = 0.02
_POLL_TIMEOUT = 3.0


def _create_workspace(workspaces_base: Path, workspace_id: str) -> None:
    """Create a minimal workspace that passes filesystem backend validation."""
    workspace_dir = workspaces_base / workspace_id
    workspace_dir.mkdir(parents=True, exist_ok=True)
    (workspace_dir / "hosts.yaml").write_text("all:\n  hosts:\n    node1:\n", encoding="utf-8")
    (workspace_dir / "sap-parameters.yaml").write_text(
        "sap_sid: HDB\ndatabase_high_availability: true\n",
        encoding="utf-8",
    )


async def _wait_for_job(
    job_store: Any,
    job_id: str,
    *,
    predicate: Any = None,
    timeout: float = _POLL_TIMEOUT,
) -> Job:
    """Poll storage until the job satisfies the predicate or reaches a terminal state."""
    deadline = asyncio.get_running_loop().time() + timeout
    matcher = predicate or (lambda job: job.is_terminal)

    while asyncio.get_running_loop().time() < deadline:
        found = job_store.get(job_id)
        if found is not None and matcher(found):
            return found
        await asyncio.sleep(_POLL_INTERVAL)

    raise TimeoutError(f"Job {job_id} did not satisfy the expected condition within {timeout}s")


def _build_worker_service(
    *,
    storage_context: StorageContext,
    workspace_backend: WorkspaceBackendProtocol,
    workspaces_base: Path,
    data_dir: Path,
    executor: Any,
) -> tuple[JobWorker, JobApplicationService]:
    """Create an integration-scoped worker wired as the mandatory execution port.

    FastAPI and the scheduler both submit through this same
    ``JobApplicationService``/``JobExecutionPort`` path — there is no
    second ownership path or poll/claim/lease step.
    """
    worker = JobWorker(
        job_store=storage_context.job_store,
        executor=executor,
        workspace_backend=workspace_backend,
        log_dir=data_dir / "job-logs",
        ssh_provider=SshCredentialProvider(workspaces_base=workspaces_base),
    )
    service = JobApplicationService(
        job_store=storage_context.job_store,
        workspace_reader=workspace_backend,
        execution_port=worker,
    )
    return worker, service


class TestIntegrationFlow:
    """Deterministic integration tests for job execution lifecycle."""

    @pytest.fixture
    def integration_root(self) -> Generator[Path, None, None]:
        """Create a repository-local integration workspace and clean it afterward."""
        root = Path(__file__).resolve().parents[1] / "_artifacts" / f"integration-{uuid4().hex}"
        root.mkdir(parents=True, exist_ok=False)
        try:
            yield root
        finally:
            shutil.rmtree(root, ignore_errors=True)

    @pytest.fixture
    def workspaces_base(self, integration_root: Path) -> Path:
        """Return the workspace root used by the filesystem backend."""
        base = integration_root / "WORKSPACES" / "SYSTEM"
        base.mkdir(parents=True, exist_ok=True)
        return base

    @pytest.fixture
    def data_dir(self, integration_root: Path) -> Path:
        """Return the repository-local data directory for SQLite and logs."""
        data = integration_root / "data"
        data.mkdir(parents=True, exist_ok=True)
        return data

    @pytest.fixture
    def storage_context(self, data_dir: Path) -> Generator[StorageContext, None, None]:
        """Create a real SQLite storage context for integration coverage."""
        context = create_storage_context(db_path=data_dir / "scheduler.db")
        try:
            yield context
        finally:
            context.close()

    @pytest.fixture
    def workspace_backend(
        self, workspaces_base: Path, data_dir: Path
    ) -> Generator[WorkspaceBackendProtocol, None, None]:
        """Create a filesystem workspace backend using the production factory."""
        backend = create_workspace_backend(workspaces_base=workspaces_base, data_dir=data_dir)
        try:
            yield backend
        finally:
            backend.close()

    @pytest.mark.asyncio
    async def test_submit_execute_complete_direct_path(
        self,
        storage_context: StorageContext,
        workspace_backend: WorkspaceBackendProtocol,
        workspaces_base: Path,
        data_dir: Path,
        mocker: MockerFixture,
    ) -> None:
        """Submitting a job creates it once and schedules execution exactly once.

        No claim/lease/heartbeat step is used — the single embedded worker
        is the sole execution owner.
        """
        _create_workspace(workspaces_base, "WS-INTEGRATION-COMPLETE")
        run_snapshot: dict[str, Any] = {}
        executor = mocker.MagicMock()

        def run_test(**kwargs: Any) -> dict[str, Any]:
            stored_job = storage_context.job_store.get(kwargs["job_id"])
            assert stored_job is not None
            run_snapshot["status"] = stored_job.status
            run_snapshot["started_at"] = stored_job.started_at
            run_snapshot["offline"] = kwargs["offline"]
            return {"status": "success", "detail": "executor completed"}

        executor.run_test = mocker.MagicMock(side_effect=run_test)
        executor.terminate_process = mocker.MagicMock(return_value=False)
        worker, service = _build_worker_service(
            storage_context=storage_context,
            workspace_backend=workspace_backend,
            workspaces_base=workspaces_base,
            data_dir=data_dir,
            executor=executor,
        )
        create_spy = mocker.spy(storage_context.job_store, "create")
        submit_spy = mocker.spy(worker, "submit")

        try:
            submitted = await service.submit_job(
                CreateJobRequest(
                    workspace_id="WS-INTEGRATION-COMPLETE",
                    test_group="DatabaseHighAvailability",
                    test_ids=["ha-config-offline"],
                    offline=True,
                )
            )
            found = await _wait_for_job(storage_context.job_store, str(submitted.id))
        finally:
            await worker.shutdown(timeout=1)

        assert not hasattr(worker, "_poll_task")
        create_spy.assert_called_once()
        submit_spy.assert_called_once()
        assert run_snapshot["status"] == JobStatus.RUNNING
        assert run_snapshot["started_at"] is not None
        assert run_snapshot["offline"] is True
        assert found.status == JobStatus.COMPLETED
        assert found.result is not None
        assert found.result["status"] == "success"
        assert found.result["tests_run"] == 1
        assert found.result["tests_passed"] == 1
        assert found.result["tests_failed"] == 0
        assert [event.event_type for event in found.events] == [
            JobEventType.STARTED,
            JobEventType.COMPLETED,
        ]

    @pytest.mark.asyncio
    async def test_submit_cancel_direct_path(
        self,
        storage_context: StorageContext,
        workspace_backend: WorkspaceBackendProtocol,
        workspaces_base: Path,
        data_dir: Path,
        mocker: MockerFixture,
    ) -> None:
        """Cancelling a job terminates the locally owned subprocess immediately.

        No durable cancellation-request round trip is required — the call
        reaches the one worker that owns the subprocess directly.
        """
        _create_workspace(workspaces_base, "WS-INTEGRATION-CANCEL")
        started_event = threading.Event()
        release_event = threading.Event()
        executor = mocker.MagicMock()

        def run_test(**kwargs: Any) -> dict[str, Any]:
            stored_job = storage_context.job_store.get(kwargs["job_id"])
            assert stored_job is not None
            assert stored_job.status == JobStatus.RUNNING
            started_event.set()
            if not release_event.wait(timeout=2):
                raise TimeoutError("Cancellation test executor was not released")
            return {"status": "success", "detail": "executor released"}

        def terminate_process(job_id: str) -> bool:
            release_event.set()
            return True

        executor.run_test = mocker.MagicMock(side_effect=run_test)
        executor.terminate_process = mocker.MagicMock(side_effect=terminate_process)
        worker, service = _build_worker_service(
            storage_context=storage_context,
            workspace_backend=workspace_backend,
            workspaces_base=workspaces_base,
            data_dir=data_dir,
            executor=executor,
        )

        try:
            submitted = await service.submit_job(
                CreateJobRequest(
                    workspace_id="WS-INTEGRATION-CANCEL",
                    test_group="DatabaseHighAvailability",
                    test_ids=["ha-config-offline"],
                    offline=True,
                )
            )
            assert await asyncio.to_thread(started_event.wait, 2.0) is True
            running = await _wait_for_job(
                storage_context.job_store,
                str(submitted.id),
                predicate=lambda job: job.status == JobStatus.RUNNING,
            )
            assert running.status == JobStatus.RUNNING

            assert await service.cancel_job(str(submitted.id), "stop requested") is True
            found = await _wait_for_job(storage_context.job_store, str(submitted.id))
        finally:
            release_event.set()
            await worker.shutdown(timeout=1)

        assert found.status == JobStatus.CANCELLED
        assert found.error == "stop requested"
        assert [event.event_type for event in found.events] == [
            JobEventType.STARTED,
            JobEventType.CANCELLED,
        ]
        executor.terminate_process.assert_called_once_with(str(submitted.id))
