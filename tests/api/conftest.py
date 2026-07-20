# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Fixtures for API tests."""

import tempfile
from pathlib import Path
from typing import Any, Generator
from uuid import uuid4
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from src.api.routes import jobs, schedules
from src.api.routes.workspaces import set_workspace_backend
from src.core.models.job import Job
from src.core.models.schedule import Schedule
from src.core.models.workspace import MaterializedWorkspace, WorkspaceConfig, WorkspaceSummary
from src.core.services.job_service import JobApplicationService
from src.core.storage.job_store import JobStore
from src.core.storage.schedule_store import ScheduleStore
from src.api.routes.health import router as health_router
from src.api.routes.jobs import router as jobs_router
from src.api.routes.schedules import router as schedules_router
from src.api.routes.workspaces import router as workspaces_router
from src.core.exceptions import WorkspaceNotFoundError


class ApiWorkspaceBackend:
    """Simple backend used by API tests."""

    backend_name = "filesystem"

    def __init__(self, root: Path) -> None:
        """Initialize the test workspace backend.

        :param root: Root directory for test workspaces.
        :type root: Path
        """
        self.root = root

    def list_workspaces(self) -> list[WorkspaceSummary]:
        """List the workspaces exposed by the test backend.

        :return: Summaries of available test workspaces.
        :rtype: list[WorkspaceSummary]
        """
        return [
            WorkspaceSummary(
                workspace_id=ws_id, name=ws_id, environment="test", path=str(self.root / ws_id)
            )
            for ws_id in (
                "NEW-WORKSPACE",
                "EXEC-TEST",
                "WS",
                "WS-A",
                "WS-B",
                "TEST-WORKSPACE-01",
                "TEST-WORKSPACE-02",
            )
        ]

    def get_workspace_config(self, workspace_id: str) -> WorkspaceConfig:
        """Get or create the configuration for a test workspace.

        :param workspace_id: Identifier of the workspace to retrieve.
        :type workspace_id: str
        :return: Configuration for the requested workspace.
        :rtype: WorkspaceConfig
        :raises WorkspaceNotFoundError: If the workspace identifier is unknown.
        """
        if workspace_id not in {summary.workspace_id for summary in self.list_workspaces()}:

            raise WorkspaceNotFoundError(f"Workspace {workspace_id} not found")
        workspace_dir = self.root / workspace_id
        workspace_dir.mkdir(parents=True, exist_ok=True)
        inventory = workspace_dir / "hosts.yaml"
        inventory.write_text("all:\n  hosts:\n    node1:\n", encoding="utf-8")
        return WorkspaceConfig(
            workspace_id=workspace_id,
            inventory_path=str(inventory),
            sap_sid=workspace_id,
            extra_vars={"sap_sid": workspace_id},
            path=str(workspace_dir),
        )

    def materialize(self, workspace_id: str, job_id: str) -> MaterializedWorkspace:
        """Materialize a test workspace for a job.

        :param workspace_id: Identifier of the workspace to materialize.
        :type workspace_id: str
        :param job_id: Identifier of the job using the workspace.
        :type job_id: str
        :return: Materialized test workspace.
        :rtype: MaterializedWorkspace
        """
        config = self.get_workspace_config(workspace_id)
        return MaterializedWorkspace(
            workspace_id=workspace_id,
            job_id=job_id,
            local_path=Path(config.path),
            inventory_path=config.inventory_path,
            extra_vars=config.extra_vars,
            owned=False,
        )

    def cleanup(self, materialized: MaterializedWorkspace) -> None:
        """Clean up a materialized test workspace.

        :param materialized: Materialized workspace to clean up.
        :type materialized: MaterializedWorkspace
        """
        return None

    def close(self) -> None:
        """Close the test backend."""
        return None


def create_test_app() -> FastAPI:
    """Create a minimal FastAPI app for testing.

    :return: FastAPI application with the API routers registered.
    :rtype: FastAPI
    """

    app = FastAPI(title="Test API")
    app.include_router(health_router)
    app.include_router(jobs_router, prefix="/api/v1")
    app.include_router(schedules_router, prefix="/api/v1")
    app.include_router(workspaces_router, prefix="/api/v1")
    return app


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """Create a temporary directory for an API test.

    :yield: Temporary directory path.
    :rtype: Generator[Path, None, None]
    """
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


@pytest.fixture
def job_store(temp_dir: Path) -> Generator[JobStore, None, None]:
    """Create a job store backed by a temporary database.

    :param temp_dir: Temporary directory path.
    :type temp_dir: Path
    :yield: Initialized job store.
    :rtype: Generator[JobStore, None, None]
    """
    store = JobStore(db_path=temp_dir / "test.db")
    yield store
    store.close()


@pytest.fixture
def schedule_store(temp_dir: Path) -> Generator[ScheduleStore, None, None]:
    """Create a schedule store backed by a temporary database.

    :param temp_dir: Temporary directory path.
    :type temp_dir: Path
    :yield: Initialized schedule store.
    :rtype: Generator[ScheduleStore, None, None]
    """
    store = ScheduleStore(db_path=temp_dir / "test.db")
    yield store
    store.close()


@pytest.fixture
def workspace_backend(temp_dir: Path) -> ApiWorkspaceBackend:
    """Create the workspace backend used by API tests.

    :param temp_dir: Temporary directory path.
    :type temp_dir: Path
    :return: Test workspace backend.
    :rtype: ApiWorkspaceBackend
    """
    return ApiWorkspaceBackend(temp_dir / "api-workspaces")


class FakeExecutionPort:
    """In-process test double for the mandatory ``JobExecutionPort``.

    Mirrors the single-owner ``JobWorker`` contract without spawning real
    subprocesses: :meth:`submit` is a no-op recording nothing beyond what the
    job store already persisted, and :meth:`cancel` marks a non-terminal job
    ``CANCELLED`` directly in the store.
    """

    def __init__(self, job_store: JobStore) -> None:
        """Initialize the fake port.

        :param job_store: Job store used to persist cancellation outcomes.
        :type job_store: JobStore
        """
        self._job_store = job_store

    def submit(self, job: Job) -> None:
        """Accept a submitted job without performing real execution.

        :param job: Persisted PENDING job handed off for execution.
        :type job: Job
        """

    def cancel(self, job_id: str, reason: str = "Cancelled by user") -> bool:
        """Cancel a non-terminal job.

        :param job_id: Identifier of the job to cancel.
        :type job_id: str
        :param reason: Human-readable cancellation reason.
        :type reason: str
        :return: ``True`` if an active job was cancelled.
        :rtype: bool
        """
        job = self._job_store.get(job_id)
        if job is None or job.is_terminal:
            return False
        job.cancel(reason)
        self._job_store.update(job)
        return True


@pytest.fixture
def job_service(
    job_store: JobStore,
    workspace_backend: ApiWorkspaceBackend,
) -> JobApplicationService:
    """Create a JobApplicationService for API tests.

    :param job_store: Temporary job store.
    :type job_store: JobStore
    :param workspace_backend: Test workspace backend.
    :type workspace_backend: ApiWorkspaceBackend
    :return: Configured job application service.
    :rtype: JobApplicationService
    """
    return JobApplicationService(
        job_store=job_store,
        workspace_reader=workspace_backend,
        execution_port=FakeExecutionPort(job_store),
    )


@pytest.fixture
def client(
    job_store: JobStore,
    schedule_store: ScheduleStore,
    job_service: JobApplicationService,
    workspace_backend: ApiWorkspaceBackend,
) -> Generator[TestClient, None, None]:
    """Create an API test client with route dependencies configured.

    :param job_store: Temporary job store.
    :type job_store: JobStore
    :param schedule_store: Temporary schedule store.
    :type schedule_store: ScheduleStore
    :param job_service: Configured job application service.
    :type job_service: JobApplicationService
    :param workspace_backend: Test workspace backend.
    :type workspace_backend: ApiWorkspaceBackend
    :yield: Configured FastAPI test client.
    :rtype: Generator[TestClient, None, None]
    """
    app = create_test_app()
    app.state.job_store = job_store
    app.state.schedule_store = schedule_store
    app.state.job_service = job_service
    jobs.set_job_service(job_service)
    schedules.set_schedule_store(schedule_store)
    set_workspace_backend(workspace_backend)
    with TestClient(app) as test_client:
        yield test_client
    set_workspace_backend(None)


@pytest.fixture
def sample_job(job_store: JobStore) -> Job:
    """Create and persist a sample pending job.

    :param job_store: Job store in which to persist the job.
    :type job_store: JobStore
    :return: Persisted sample job.
    :rtype: Job
    """
    job = Job(
        id=uuid4(),
        workspace_id="TEST-WORKSPACE-01",
        test_group="ConfigurationChecks",
        test_ids=["test1", "test2"],
    )
    job_store.create(job)
    return job


@pytest.fixture
def sample_running_job(job_store: JobStore) -> Job:
    """Create and persist a sample running job.

    :param job_store: Job store in which to persist the job.
    :type job_store: JobStore
    :return: Persisted running job.
    :rtype: Job
    """
    job = Job(id=uuid4(), workspace_id="TEST-WORKSPACE-02", test_group="DatabaseHighAvailability")
    job.start()
    job_store.create(job)
    return job


@pytest.fixture
def sample_schedule(schedule_store: ScheduleStore) -> Schedule:
    """Create and persist a sample schedule.

    :param schedule_store: Schedule store in which to persist the schedule.
    :type schedule_store: ScheduleStore
    :return: Persisted sample schedule.
    :rtype: Schedule
    """
    schedule = Schedule(
        name="Nightly Config Checks",
        cron_expression="0 0 * * *",
        workspace_ids=["WS-01", "WS-02"],
        test_group="ConfigurationChecks",
    )
    schedule_store.create(schedule)
    return schedule
