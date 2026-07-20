# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for storage and workspace wiring in the FastAPI lifespan."""

from dataclasses import dataclass
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from pytest_mock import MockerFixture, MockType
from src.api.app import app
from src.core.models.storage import StorageContext


@dataclass(frozen=True)
class _RuntimeMocks:
    """Mock collaborators used by application lifespan tests."""

    azure_context: MockType
    storage_context: MockType
    workspace_backend: MockType
    execution_worker: MockType
    scheduler_service: MockType
    storage_factory: MockType
    worker_factory: MockType
    scheduler_factory: MockType


def _configure_runtime(
    mocker: MockerFixture,
    tmp_path: Path,
    *,
    storage_backend: str = "sqlite",
    workspace_backend: str = "filesystem",
) -> _RuntimeMocks:
    """Patch application runtime factories with controlled collaborators."""
    azure_context = mocker.MagicMock()
    storage_context = mocker.MagicMock(spec=StorageContext)
    storage_context.backend = storage_backend
    storage_context.job_store = mocker.MagicMock()
    storage_context.schedule_store = mocker.MagicMock()
    workspace = mocker.MagicMock()
    workspace.backend_name = workspace_backend
    worker = mocker.MagicMock()
    worker.recover_crashed_jobs.return_value = 0
    worker.shutdown = mocker.AsyncMock()
    scheduler = mocker.MagicMock()
    scheduler.start = mocker.AsyncMock()
    scheduler.stop = mocker.AsyncMock()

    mocker.patch("src.api.app.DATA_DIR", tmp_path)
    mocker.patch("src.api.app.WORKSPACES_BASE", tmp_path / "workspaces")
    mocker.patch("src.api.app.PLAYBOOK_DIR", tmp_path / "src")
    mocker.patch("src.api.app.create_azure_storage_context", return_value=azure_context)
    storage_factory = mocker.patch(
        "src.api.app.create_storage_context",
        return_value=storage_context,
    )
    mocker.patch("src.api.app.create_workspace_backend", return_value=workspace)
    worker_factory = mocker.patch("src.api.app.JobWorker", return_value=worker)
    scheduler_factory = mocker.patch("src.api.app.SchedulerService", return_value=scheduler)

    return _RuntimeMocks(
        azure_context=azure_context,
        storage_context=storage_context,
        workspace_backend=workspace,
        execution_worker=worker,
        scheduler_service=scheduler,
        storage_factory=storage_factory,
        worker_factory=worker_factory,
        scheduler_factory=scheduler_factory,
    )


class TestApplicationStorageWiring:
    """Verify runtime backend selection, injection, health, and ownership."""

    def test_startup_creates_storage_context(self, mocker: MockerFixture, tmp_path: Path) -> None:
        """Create storage using the configured scheduler database path."""
        runtime = _configure_runtime(mocker, tmp_path)

        with TestClient(app):
            runtime.storage_factory.assert_called_once_with(
                db_path=tmp_path / "scheduler.db",
                azure_context=runtime.azure_context,
            )

    def test_startup_failure_closes_azure_context(
        self,
        mocker: MockerFixture,
        tmp_path: Path,
    ) -> None:
        """Fail fast and close Azure resources when storage creation fails.

        :param mocker: Pytest mock fixture.
        :param tmp_path: Temporary application data directory.
        """
        runtime = _configure_runtime(mocker, tmp_path)
        runtime.storage_factory.side_effect = RuntimeError("Azure Table unreachable")

        with pytest.raises(RuntimeError, match="Azure Table unreachable"):
            with TestClient(app):
                pass

        runtime.azure_context.close.assert_called_once()

    def test_shutdown_closes_owned_runtime_services(
        self,
        mocker: MockerFixture,
        tmp_path: Path,
    ) -> None:
        """Stop asynchronous services and close each owned context once.

        :param mocker: Pytest mock fixture.
        :param tmp_path: Temporary application data directory.
        """
        runtime = _configure_runtime(mocker, tmp_path)

        with TestClient(app):
            pass

        runtime.scheduler_service.stop.assert_awaited_once()
        runtime.execution_worker.shutdown.assert_awaited_once()
        runtime.workspace_backend.close.assert_called_once()
        runtime.storage_context.close.assert_called_once()
        runtime.azure_context.close.assert_called_once()

    def test_runtime_stores_are_injected(self, mocker: MockerFixture, tmp_path: Path) -> None:
        """Inject stores into the worker, scheduler, routes, and application state.

        :param mocker: Pytest mock fixture.
        :param tmp_path: Temporary application data directory.
        """
        runtime = _configure_runtime(mocker, tmp_path)

        with TestClient(app):
            assert app.state.job_store is runtime.storage_context.job_store
            assert app.state.schedule_store is runtime.storage_context.schedule_store

        assert (
            runtime.worker_factory.call_args.kwargs["job_store"]
            is runtime.storage_context.job_store
        )
        assert (
            runtime.scheduler_factory.call_args.kwargs["schedule_store"]
            is runtime.storage_context.schedule_store
        )

    @pytest.mark.parametrize(
        ("storage_backend", "workspace_backend"),
        [("sqlite", "filesystem"), ("azure_table", "blob")],
    )
    def test_health_reports_backend_names(
        self,
        mocker: MockerFixture,
        tmp_path: Path,
        storage_backend: str,
        workspace_backend: str,
    ) -> None:
        """Expose only backend identifiers through the health endpoint.

        :param mocker: Pytest mock fixture.
        :param tmp_path: Temporary application data directory.
        :param storage_backend: Expected storage backend identifier.
        :param workspace_backend: Expected workspace backend identifier.
        """
        _configure_runtime(
            mocker,
            tmp_path,
            storage_backend=storage_backend,
            workspace_backend=workspace_backend,
        )

        with TestClient(app) as client:
            response = client.get("/healthz")

        assert response.status_code == 200
        assert response.json()["storage_backend"] == storage_backend
        assert response.json()["workspace_backend"] == workspace_backend
        assert "core.windows.net" not in response.text
