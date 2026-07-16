# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Shared fixtures for core module tests."""

import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Generator
from uuid import uuid4
import pytest
from pytest_mock import MockerFixture
from src.core.models.job import Job
from src.core.models.schedule import Schedule
from src.core.storage.job_store import JobStore
from src.core.storage.schedule_store import ScheduleStore
from src.core.execution.worker import JobWorker
from src.core.services.scheduler import SchedulerService


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
    executor.execute = mocker.AsyncMock(
        return_value={"status": "success", "tests_passed": 3, "tests_failed": 0}
    )
    executor.terminate_process = mocker.MagicMock(
        return_value=False,
    )
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
    executor.execute = mocker.AsyncMock(side_effect=RuntimeError("Executor failure"))
    executor.terminate_process = mocker.MagicMock(
        return_value=False,
    )
    return executor


@pytest.fixture
def workspace_loader() -> Callable[[str], dict[str, Any]]:
    """
    Fixture for loading workspace configuration.

    :return: Workspace configuration dictionary
    :rtype: dict[str, Any]
    """

    def loader(workspace_id: str) -> dict[str, Any]:
        """
        Load workspace configuration for the given workspace ID.

        :param workspace_id: Workspace ID
        :type workspace_id: str
        :return: Workspace configuration dictionary
        :rtype: dict[str, Any]
        """
        return {
            "inventory_path": f"WORKSPACES/SYSTEM/{workspace_id}/hosts.yaml",
            "sap_sid": "X00",
            "database_high_availability": True,
        }

    return loader


@pytest.fixture
def job_worker(
    job_store: JobStore, mock_executor: Any, workspace_loader: Any, temp_dir: Path
) -> JobWorker:
    """
    Fixture for creating a JobWorker instance.

    :param job_store: Job store instance
    :type job_store: JobStore
    :param mock_executor: Mock executor instance
    :type mock_executor: Any
    :param workspace_loader: Workspace loader callable
    :type workspace_loader: Any
    :param temp_dir: Temporary directory path
    :type temp_dir: Path
    :return: JobWorker instance
    :rtype: JobWorker
    """
    return JobWorker(
        job_store=job_store,
        executor=mock_executor,
        workspace_config_loader=workspace_loader,
        workspaces_base=temp_dir,
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
