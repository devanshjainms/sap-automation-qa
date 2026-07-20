# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for single-worker API composition (RD-021/RD-022).

There is no ``EXECUTION_HOST_MODE`` env var or dedicated-worker-host mode:
FastAPI always constructs exactly one embedded ``JobWorker`` and wires it as
the mandatory ``JobExecutionPort`` for ``JobApplicationService``.
"""

from pathlib import Path

import pytest
from pytest_mock import MockerFixture


class TestAppWorkerComposition:
    """Tests for the single embedded JobWorker composition in src/api/app.py."""

    @staticmethod
    def _patch_common(mocker: MockerFixture, tmp_path: Path) -> tuple:
        """Patch the storage/workspace/scheduler dependencies shared by every test."""
        from src.core.models.storage import StorageContext

        mocker.patch("src.api.app.DATA_DIR", tmp_path)
        mocker.patch("src.api.app.WORKSPACES_BASE", tmp_path / "ws")
        mocker.patch("src.api.app.PLAYBOOK_DIR", tmp_path / "src")
        azure_ctx = mocker.MagicMock()
        mocker.patch("src.api.app.create_azure_storage_context", return_value=azure_ctx)
        storage_ctx = mocker.MagicMock(spec=StorageContext)
        storage_ctx.backend = "sqlite"
        storage_ctx.job_store = mocker.MagicMock()
        storage_ctx.schedule_store = mocker.MagicMock()
        mocker.patch("src.api.app.create_storage_context", return_value=storage_ctx)
        workspace = mocker.MagicMock()
        workspace.backend_name = "filesystem"
        mocker.patch("src.api.app.create_workspace_backend", return_value=workspace)
        scheduler = mocker.MagicMock()
        scheduler.start = mocker.AsyncMock()
        scheduler.stop = mocker.AsyncMock()
        mocker.patch("src.api.app.SchedulerService", return_value=scheduler)
        return azure_ctx, storage_ctx, workspace, scheduler

    def test_no_execution_host_mode_env_var_exists(self) -> None:
        """The app module carries no EXECUTION_HOST_MODE toggle at all."""
        import src.api.app as app_module

        assert not hasattr(app_module, "EXECUTION_HOST_MODE")
        assert not hasattr(app_module, "_VALID_EXECUTION_HOST_MODES")

    def test_exactly_one_worker_is_constructed_and_started(
        self, mocker: MockerFixture, tmp_path: Path
    ) -> None:
        """Exactly one JobWorker is constructed; recover_crashed_jobs runs once."""
        from src.api.app import app

        self._patch_common(mocker, tmp_path)
        worker = mocker.MagicMock()
        worker.recover_crashed_jobs.return_value = 0
        worker.shutdown = mocker.AsyncMock()
        worker_cls = mocker.patch("src.api.app.JobWorker", return_value=worker)

        from fastapi.testclient import TestClient

        with TestClient(app):
            pass

        worker_cls.assert_called_once()
        worker.recover_crashed_jobs.assert_called_once()
        worker.shutdown.assert_awaited_once()

    def test_worker_wired_as_mandatory_execution_port(
        self, mocker: MockerFixture, tmp_path: Path
    ) -> None:
        """The single embedded worker is the required execution port for
        JobApplicationService — the port is never None."""
        from src.api.app import app

        self._patch_common(mocker, tmp_path)
        worker = mocker.MagicMock()
        worker.recover_crashed_jobs.return_value = 0
        worker.shutdown = mocker.AsyncMock()
        mocker.patch("src.api.app.JobWorker", return_value=worker)

        from fastapi.testclient import TestClient

        with TestClient(app):
            assert app.state.job_service._execution_port is worker
            assert app.state.execution_worker is worker

    def test_scheduler_submits_through_same_job_service(
        self, mocker: MockerFixture, tmp_path: Path
    ) -> None:
        """SchedulerService is composed with the same JobApplicationService
        instance used by FastAPI routes — no second ownership path."""
        from src.api.app import app

        self._patch_common(mocker, tmp_path)
        worker = mocker.MagicMock()
        worker.recover_crashed_jobs.return_value = 0
        worker.shutdown = mocker.AsyncMock()
        mocker.patch("src.api.app.JobWorker", return_value=worker)
        scheduler_cls = mocker.patch("src.api.app.SchedulerService")
        scheduler = scheduler_cls.return_value
        scheduler.start = mocker.AsyncMock()
        scheduler.stop = mocker.AsyncMock()

        from fastapi.testclient import TestClient

        with TestClient(app):
            _, kwargs = scheduler_cls.call_args
            assert kwargs["job_submitter"] is app.state.job_service
