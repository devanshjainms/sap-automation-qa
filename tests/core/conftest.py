# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Shared fixtures for core module tests."""

import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator
from uuid import uuid4
import pytest
from pytest_mock import MockerFixture
from src.core.execution.worker import JobWorker
from src.core.models.job import Job
from src.core.models.schedule import Schedule
from src.core.models.workspace import MaterializedWorkspace
from src.core.services.scheduler import SchedulerService
from src.core.storage.job_store import JobStore
from src.core.storage.schedule_store import ScheduleStore


class FakeWorkspaceBackend:
    """Simple workspace backend for worker tests."""

    backend_name = "filesystem"

    def __init__(self, root: Path) -> None:
        self.root = root

    def materialize(self, workspace_id: str, job_id: str) -> MaterializedWorkspace:
        workspace_dir = self.root / workspace_id
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

    def cleanup(self, materialized: MaterializedWorkspace) -> None:
        return None


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """Create a temporary directory for a test.

    :yield: Temporary directory path.
    :rtype: Generator[Path, None, None]
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def sample_job() -> Job:
    """Create a sample pending job.

    :return: Sample job instance.
    :rtype: Job
    """
    return Job(
        id=uuid4(),
        workspace_id="TEST-WORKSPACE-01",
        test_group="ha_db_functional_tests",
        test_ids=["test_1", "test_2"],
        metadata={"source": "unit_test"},
    )


@pytest.fixture
def sample_running_job() -> Job:
    """Create a sample running job.

    :return: Sample running job instance.
    :rtype: Job
    """
    job = Job(id=uuid4(), workspace_id="TEST-WORKSPACE-02", test_group="ha_scs_functional_tests")
    job.start()
    return job


@pytest.fixture
def sample_completed_job() -> Job:
    """Create a sample completed job.

    :return: Sample completed job instance.
    :rtype: Job
    """
    job = Job(id=uuid4(), workspace_id="TEST-WORKSPACE-03", test_group="configuration_checks")
    job.start()
    job.complete({"passed": 5, "failed": 0})
    return job


@pytest.fixture
def sample_schedule() -> Schedule:
    """Create a sample enabled schedule.

    :return: Sample enabled schedule instance.
    :rtype: Schedule
    """
    return Schedule(
        id=str(uuid4()),
        name="Daily HA Tests",
        description="Run HA tests every day at midnight",
        cron_expression="0 0 * * *",
        timezone="UTC",
        workspace_ids=["WS-001", "WS-002"],
        test_group="ha_db_functional_tests",
        enabled=True,
    )


@pytest.fixture
def sample_disabled_schedule() -> Schedule:
    """Create a sample disabled schedule.

    :return: Sample disabled schedule instance.
    :rtype: Schedule
    """
    return Schedule(
        id=str(uuid4()),
        name="Disabled Schedule",
        cron_expression="0 12 * * *",
        workspace_ids=["WS-003"],
        enabled=False,
    )


@pytest.fixture
def due_schedule() -> Schedule:
    """Create a sample schedule that is due to run.

    :return: Sample due schedule instance.
    :rtype: Schedule
    """
    return Schedule(
        id=str(uuid4()),
        name="Due Schedule",
        cron_expression="* * * * *",
        workspace_ids=["WS-DUE"],
        enabled=True,
        next_run_time=datetime(2020, 1, 1, tzinfo=timezone.utc),
    )


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
def mock_executor(mocker: MockerFixture) -> Any:
    """Create a mock executor that completes successfully.

    :param mocker: Pytest mock fixture.
    :type mocker: MockerFixture
    :return: Configured mock executor.
    :rtype: Any
    """
    executor = mocker.MagicMock()
    executor.run_test = mocker.MagicMock(return_value={"status": "success"})
    executor.terminate_process = mocker.MagicMock(return_value=False)
    return executor


@pytest.fixture
def failing_executor(mocker: MockerFixture) -> Any:
    """
    Fixture for creating a failing executor instance.

    :param mocker: Mocker fixture
    :type mocker: MockerFixture
    :return: Failing executor instance
    :rtype: Any
    """
    executor = mocker.MagicMock()
    executor.run_test = mocker.MagicMock(side_effect=RuntimeError("Executor failure"))
    executor.terminate_process = mocker.MagicMock(return_value=False)
    return executor


@pytest.fixture
def workspace_backend(temp_dir: Path) -> FakeWorkspaceBackend:
    """Create a filesystem workspace backend for worker tests.

    :param temp_dir: Temporary directory path.
    :returns: Workspace backend rooted in the temporary directory.
    """
    return FakeWorkspaceBackend(temp_dir / "workspaces")


@pytest.fixture
def job_worker(
    job_store: JobStore, mock_executor: Any, workspace_backend: Any, temp_dir: Path
) -> JobWorker:
    """
    Fixture for creating a JobWorker instance.

    :param job_store: Job store instance
    :type job_store: JobStore
    :param mock_executor: Mock executor instance
    :type mock_executor: Any
    :param workspace_backend: Workspace backend instance.
    :type workspace_backend: Any
    :param temp_dir: Temporary directory path
    :type temp_dir: Path
    :return: JobWorker instance
    :rtype: JobWorker
    """
    return JobWorker(
        job_store=job_store,
        executor=mock_executor,
        workspace_backend=workspace_backend,
        log_dir=temp_dir / "job-logs",
    )


@pytest.fixture
def mock_job_worker(mocker: MockerFixture) -> Any:
    """
    Fixture for job worker

    :param mocker: Mocker
    :type mocker: MockerFixture
    :return: Mocked Job Worker
    :rtype: Any
    """
    worker = mocker.MagicMock()

    async def mock_submit(job: Job) -> Job:
        """Mock submit job method.

        :param job: Job instance to submit
        :type job: Job
        :return: Submitted job instance
        :rtype: Job
        """
        job.start()
        return job

    worker.submit_job = mocker.AsyncMock(side_effect=mock_submit)
    return worker


@pytest.fixture
def scheduler_service(schedule_store: ScheduleStore, mock_job_worker: Any) -> SchedulerService:
    """
    Fixture for creating a SchedulerService instance.

    :param schedule_store: Schedule store instance
    :type schedule_store: ScheduleStore
    :param mock_job_worker: Mock job worker instance
    :type mock_job_worker: Any
    :return: Scheduler service instance
    :rtype: SchedulerService
    """
    return SchedulerService(
        schedule_store=schedule_store,
        job_worker=mock_job_worker,
        check_interval_seconds=1,
    )
