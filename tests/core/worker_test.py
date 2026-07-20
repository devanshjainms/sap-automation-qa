# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for JobWorker (single-owner in-process execution, RD-021/RD-022)."""

import asyncio
from pathlib import Path
from typing import Any
import pytest
from pytest_mock import MockerFixture
from src.core.execution.worker import JobWorker
from src.core.models.job import Job, JobEventType, JobStatus
from src.core.models.workspace import MaterializedWorkspace
from src.core.storage.job_store import JobStore

_POLL_INTERVAL = 0.02
_POLL_TIMEOUT = 3.0


async def _wait_for_terminal(
    job_store: JobStore, job_id: Any, timeout: float = _POLL_TIMEOUT
) -> Job:
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        found = job_store.get(job_id)
        if found and found.is_terminal:
            return found
        await asyncio.sleep(_POLL_INTERVAL)
    raise TimeoutError(f"Job {job_id} did not reach terminal state within {timeout}s")


def _materialized(temp_dir: Path, workspace_id: str, job_id: str) -> MaterializedWorkspace:
    workspace_dir = temp_dir / workspace_id
    workspace_dir.mkdir(parents=True, exist_ok=True)
    inventory = workspace_dir / "hosts.yaml"
    inventory.write_text("all:\n  hosts:\n    node1:\n", encoding="utf-8")
    return MaterializedWorkspace(
        workspace_id=workspace_id,
        job_id=job_id,
        local_path=workspace_dir,
        inventory_path=str(inventory),
        extra_vars={"sap_sid": "X00"},
        owned=False,
    )


class TestJobWorker:
    """Tests for JobWorker submission, cancellation, and startup recovery."""

    @pytest.mark.asyncio
    async def test_submit_executes_without_poll_loop(
        self, job_store: JobStore, temp_dir: Path, mocker: MockerFixture
    ) -> None:
        """submit() executes a PENDING job directly; no poll loop exists at all.

        ``JobWorker`` has no ``_poll_task``/``start`` concept — proving the
        single embedded execution path is authoritative for submission.
        """
        executor = mocker.MagicMock()
        executor.run_test = mocker.MagicMock(return_value={"status": "success"})
        executor.terminate_process = mocker.MagicMock(return_value=False)
        backend = mocker.MagicMock()
        backend.materialize.side_effect = lambda workspace_id, job_id: _materialized(
            temp_dir, workspace_id, job_id
        )
        backend.cleanup = mocker.MagicMock()
        worker = JobWorker(
            job_store=job_store,
            executor=executor,
            workspace_backend=backend,
            log_dir=temp_dir / "job-logs",
        )

        job = Job(workspace_id="WS-DIRECT", test_group="test", test_ids=["t1"])
        job_store.create(job)

        worker.submit(job)
        found = await _wait_for_terminal(job_store, str(job.id))

        assert not hasattr(worker, "_poll_task")
        assert not hasattr(worker, "start")
        assert found.status == JobStatus.COMPLETED
        backend.cleanup.assert_called_once()

    def test_submit_rejects_non_pending_job(
        self, job_store: JobStore, temp_dir: Path, mocker: MockerFixture
    ) -> None:
        """submit() rejects a job that is not currently PENDING."""
        worker = JobWorker(
            job_store=job_store,
            executor=mocker.MagicMock(),
            workspace_backend=mocker.MagicMock(),
            log_dir=temp_dir / "job-logs",
        )
        job = Job(workspace_id="WS-NOT-PENDING", test_group="test")
        job.start()

        with pytest.raises(ValueError, match="PENDING"):
            worker.submit(job)

    @pytest.mark.asyncio
    async def test_cancel_terminates_owned_subprocess_and_persists_reason(
        self, job_store: JobStore, temp_dir: Path, mocker: MockerFixture
    ) -> None:
        """cancel() terminates the locally-owned subprocess/task immediately
        and persists CANCELLED with the given reason — no durable
        cancellation-request round trip exists."""
        executor = mocker.MagicMock()

        def slow_run(**_: Any) -> dict[str, Any]:
            import time

            time.sleep(0.2)
            return {"status": "success"}

        executor.run_test = mocker.MagicMock(side_effect=slow_run)
        executor.terminate_process = mocker.MagicMock(return_value=True)
        backend = mocker.MagicMock()
        backend.materialize.side_effect = lambda workspace_id, job_id: _materialized(
            temp_dir, workspace_id, job_id
        )
        backend.cleanup = mocker.MagicMock()
        worker = JobWorker(
            job_store=job_store,
            executor=executor,
            workspace_backend=backend,
            log_dir=temp_dir / "job-logs",
        )

        job = Job(workspace_id="WS-CANCEL", test_group="test", test_ids=["t1"])
        job_store.create(job)
        worker.submit(job)
        await asyncio.sleep(0.05)

        assert worker.cancel(str(job.id), "stop now") is True
        found = await _wait_for_terminal(job_store, str(job.id))

        assert found.status == JobStatus.CANCELLED
        assert found.error == "stop now"
        executor.terminate_process.assert_called_once_with(str(job.id))

    def test_cancel_returns_false_for_untracked_job(
        self, job_store: JobStore, temp_dir: Path, mocker: MockerFixture
    ) -> None:
        """cancel() returns False for a job this worker is not executing."""
        executor = mocker.MagicMock()
        worker = JobWorker(
            job_store=job_store,
            executor=executor,
            workspace_backend=mocker.MagicMock(),
            log_dir=temp_dir / "job-logs",
        )
        assert worker.cancel("nonexistent-job-id") is False
        executor.terminate_process.assert_not_called()

    @pytest.mark.asyncio
    async def test_shutdown_cancels_running_jobs(
        self, job_store: JobStore, temp_dir: Path, mocker: MockerFixture
    ) -> None:
        """shutdown() terminates and clears outstanding jobs."""
        executor = mocker.MagicMock()

        def slow_run(**_: Any) -> dict[str, Any]:
            import time

            time.sleep(10)
            return {"status": "success"}

        executor.run_test = mocker.MagicMock(side_effect=slow_run)
        executor.terminate_process = mocker.MagicMock(return_value=True)
        backend = mocker.MagicMock()
        backend.materialize.side_effect = lambda workspace_id, job_id: _materialized(
            temp_dir, workspace_id, job_id
        )
        backend.cleanup = mocker.MagicMock()
        worker = JobWorker(
            job_store=job_store,
            executor=executor,
            workspace_backend=backend,
            log_dir=temp_dir / "job-logs",
        )

        job = Job(workspace_id="WS-SHUTDOWN", test_group="test", test_ids=["t1"])
        job_store.create(job)
        worker.submit(job)
        await asyncio.sleep(0.1)
        await worker.shutdown(timeout=1.0)

        assert len(worker._controls) == 0

    @pytest.mark.asyncio
    async def test_emits_started_event(
        self, job_store: JobStore, workspace_backend: Any, temp_dir: Path, mocker: MockerFixture
    ) -> None:
        """Worker emits a STARTED event for a submitted job."""
        executor = mocker.MagicMock()
        executor.run_test = mocker.MagicMock(return_value={"status": "success"})
        executor.terminate_process = mocker.MagicMock(return_value=False)
        worker = JobWorker(
            job_store=job_store,
            executor=executor,
            workspace_backend=workspace_backend,
            log_dir=temp_dir / "job-logs",
        )
        job = Job(workspace_id="WS-01", test_group="test", test_ids=["t1"])
        job_store.create(job)
        worker.submit(job)
        found = await _wait_for_terminal(job_store, str(job.id))
        assert JobEventType.STARTED in [event.event_type for event in found.events]

    @pytest.mark.asyncio
    async def test_offline_job_skips_ssh_and_forwards_offline(
        self, job_store: JobStore, temp_dir: Path, mocker: MockerFixture
    ) -> None:
        """Offline job skips SSH provisioning."""
        executor = mocker.MagicMock()
        executor.run_test.return_value = {"status": "success"}
        executor.terminate_process.return_value = False
        backend = mocker.MagicMock()
        backend.materialize.side_effect = lambda workspace_id, job_id: _materialized(
            temp_dir, workspace_id, job_id
        )
        worker = JobWorker(
            job_store=job_store,
            executor=executor,
            workspace_backend=backend,
            log_dir=temp_dir / "job-logs",
        )
        provision = mocker.patch.object(worker, "_provision_ssh_credential")
        job = Job(
            workspace_id="WS-OFFLINE",
            test_group="DatabaseHighAvailability",
            test_ids=["ha-config-offline"],
            offline=True,
        )
        job_store.create(job)
        worker.submit(job)
        await _wait_for_terminal(job_store, job.id)

        provision.assert_not_called()
        call = executor.run_test.call_args.kwargs
        assert call["offline"] is True
        assert call["private_key_path"] is None
        assert call["ssh_password"] is None

    @pytest.mark.asyncio
    async def test_materialize_exception_fails_job(
        self, job_store: JobStore, temp_dir: Path, mocker: MockerFixture
    ) -> None:
        """Materialize failure transitions job to FAILED."""
        executor = mocker.MagicMock()
        executor.terminate_process = mocker.MagicMock(return_value=False)
        backend = mocker.MagicMock()
        backend.materialize.side_effect = RuntimeError("Config not found")
        backend.cleanup = mocker.MagicMock()
        worker = JobWorker(
            job_store=job_store,
            executor=executor,
            workspace_backend=backend,
            log_dir=temp_dir / "job-logs",
        )
        job = Job(workspace_id="WS-ERR", test_group="test")
        job_store.create(job)
        worker.submit(job)
        retrieved = await _wait_for_terminal(job_store, job.id)
        assert retrieved.status == JobStatus.FAILED
        assert retrieved.error is not None
        assert "Config not found" in retrieved.error
        backend.cleanup.assert_not_called()

    def test_recover_crashed_jobs_marks_all_active_jobs_failed_and_frees_locks(
        self, job_store: JobStore, execution_worker: JobWorker
    ) -> None:
        """Startup recovery marks every persisted PENDING/RUNNING job FAILED
        with a precise restart reason and releases its workspace lock.

        Unlike the removed lease-based recovery, this is unconditional: a
        crash always leaves a job orphaned since no owner/lease can survive
        a process restart in the single-owner model.
        """
        pending = Job(workspace_id="WS-CRASH-PENDING", test_group="test")
        job_store.create(pending)

        running = Job(workspace_id="WS-CRASH-RUNNING", test_group="test")
        running.start()
        job_store.create(running)

        recovered = execution_worker.recover_crashed_jobs()

        assert recovered == 2
        found_pending = job_store.get(pending.id)
        found_running = job_store.get(running.id)
        assert found_pending is not None and found_pending.status == JobStatus.FAILED
        assert found_running is not None and found_running.status == JobStatus.FAILED
        assert "Recovered at startup" in (found_pending.error or "")
        assert "Recovered at startup" in (found_running.error or "")
        assert job_store.get_active_for_workspace("WS-CRASH-PENDING") is None
        assert job_store.get_active_for_workspace("WS-CRASH-RUNNING") is None

    def test_recover_crashed_jobs_is_noop_when_no_active_jobs(
        self, job_store: JobStore, execution_worker: JobWorker
    ) -> None:
        """Recovery reports zero when no non-terminal jobs are persisted."""
        assert execution_worker.recover_crashed_jobs() == 0

    def test_get_running_job_ids_reflects_only_in_flight_tasks(
        self, job_store: JobStore, temp_dir: Path, mocker: MockerFixture
    ) -> None:
        """get_running_job_ids() reports no jobs when none are submitted."""
        worker = JobWorker(
            job_store=job_store,
            executor=mocker.MagicMock(),
            workspace_backend=mocker.MagicMock(),
            log_dir=temp_dir / "job-logs",
        )
        assert worker.get_running_job_ids() == []
