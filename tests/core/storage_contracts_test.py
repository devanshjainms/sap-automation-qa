# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Behavioral contract tests for storage protocols (P1-WP-002D / TEST-014)."""

from pathlib import Path
from typing import Any, Dict, Iterator, List, Mapping, Optional
from uuid import uuid4
import pytest
from src.core.models.job import Job, JobHistoryQuery, JobStatus
from src.core.models.schedule import Schedule
from src.core.contracts.storage import (
    JobLifecycleProtocol,
    JobQueryProtocol,
    JobStoreProtocol,
    ScheduleCrudProtocol,
    ScheduleRuntimeProtocol,
    ScheduleStoreProtocol,
)
from src.core.storage.job_store import JobStore
from src.core.storage.schedule_store import ScheduleStore
from src.core.exceptions import ConcurrencyConflictError
from src.core.storage.azure_table_store import (
    AzureTableJobStore,
    AzureTableScheduleStore,
)


class _FakeMetadata:
    """Mimics entity metadata with an etag."""

    def __init__(self, etag: str):
        self._etag = etag

    def get(self, key: str, default: Any = None) -> Any:
        if key == "etag":
            return self._etag
        return default


class _FakeEntity(dict):
    """Dict with a metadata attribute, mimicking Azure Table entity."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.metadata = _FakeMetadata(str(uuid4()))


class FakeTableClient:
    """In-memory fake of ``azure.data.tables.TableClient``.

    Supports create_entity, get_entity, update_entity, delete_entity,
    query_entities — enough for AzureTableJobStore/AzureTableScheduleStore.
    """

    def __init__(self) -> None:
        self._entities: Dict[str, _FakeEntity] = {}
        self._closed = False

    def _key(self, partition_key: str, row_key: str) -> str:
        return f"{partition_key}:{row_key}"

    def create_entity(self, entity: Mapping[str, Any]) -> Dict[str, str]:
        from azure.core.exceptions import ResourceExistsError

        key = self._key(entity["PartitionKey"], entity["RowKey"])
        if key in self._entities:
            raise ResourceExistsError("Entity already exists")
        self._entities[key] = _FakeEntity(dict(entity))
        return {"etag": self._entities[key].metadata.get("etag")}

    def get_entity(self, partition_key: str, row_key: str) -> _FakeEntity:
        from azure.core.exceptions import ResourceNotFoundError

        key = self._key(partition_key, row_key)
        if key not in self._entities:
            raise ResourceNotFoundError("Entity not found")
        return self._entities[key]

    def update_entity(
        self,
        entity: Mapping[str, Any],
        *,
        mode: Any = None,
        etag: Any = None,
        match_condition: Any = None,
    ) -> Dict[str, str]:
        from azure.core.exceptions import HttpResponseError

        key = self._key(entity["PartitionKey"], entity["RowKey"])
        if key not in self._entities:
            from azure.core.exceptions import ResourceNotFoundError

            raise ResourceNotFoundError("Entity not found")
        current = self._entities[key]
        if etag is not None and current.metadata.get("etag") != etag:
            error = HttpResponseError("Precondition failed")
            error.status_code = 412
            raise error
        self._entities[key] = _FakeEntity(dict(entity))
        return {"etag": self._entities[key].metadata.get("etag")}

    def delete_entity(
        self,
        partition_key: str,
        row_key: str,
        *,
        etag: Any = None,
        match_condition: Any = None,
    ) -> None:
        from azure.core.exceptions import ResourceNotFoundError

        key = self._key(partition_key, row_key)
        if key not in self._entities:
            raise ResourceNotFoundError("Entity not found")
        current = self._entities[key]
        if etag is not None and current.metadata.get("etag") != etag:
            from azure.core.exceptions import HttpResponseError

            error = HttpResponseError("Precondition failed")
            error.status_code = 412
            raise error
        del self._entities[key]

    def query_entities(
        self, query_filter: str, *, parameters: Optional[Dict[str, Any]] = None
    ) -> List[_FakeEntity]:
        """Simple query filter implementation for tests.

        Handles basic filter patterns used by the Azure Table stores:
        - PartitionKey eq @pk
        - workspace_id eq @ws
        - schedule_id eq @sid
        - enabled eq true
        - status eq @t0/t1/t2 (terminal status filter)
        """
        results = []
        params = parameters or {}
        pk = params.get("pk", "staf")

        terminal_statuses = set()
        for key, val in params.items():
            if key.startswith("t") and key[1:].isdigit():
                terminal_statuses.add(val)
            if key.startswith("terminal") and key[len("terminal") :].isdigit():
                terminal_statuses.add(val)

        for entity in self._entities.values():
            if entity.get("PartitionKey") != pk:
                continue
            if "ws" in params and entity.get("workspace_id") != params["ws"]:
                continue
            if "sid" in params and entity.get("schedule_id") != params["sid"]:
                continue
            if "enabled eq true" in query_filter and not entity.get("enabled"):
                continue
            if "status eq @status" in query_filter and entity.get("status") != params["status"]:
                continue
            if terminal_statuses and "status eq @t" in query_filter:
                if entity.get("status") not in terminal_statuses:
                    continue
            results.append(entity)
        return results

    def close(self) -> None:
        self._closed = True


@pytest.fixture
def sqlite_job_store(tmp_path: Path) -> Iterator[JobStore]:
    store = JobStore(db_path=tmp_path / "test.db")
    yield store
    store.close()


@pytest.fixture
def sqlite_schedule_store(tmp_path: Path) -> Iterator[ScheduleStore]:
    store = ScheduleStore(db_path=tmp_path / "test.db")
    yield store
    store.close()


@pytest.fixture
def azure_job_store() -> Iterator[AzureTableJobStore]:
    client = FakeTableClient()
    store = AzureTableJobStore(table_client=client)
    yield store
    store.close()


@pytest.fixture
def azure_schedule_store() -> Iterator[AzureTableScheduleStore]:
    client = FakeTableClient()
    store = AzureTableScheduleStore(table_client=client)
    yield store
    store.close()


def _make_job(**kwargs: Any) -> Job:
    defaults = {
        "workspace_id": "WS-001",
        "test_group": "ha_db_functional_tests",
        "test_ids": ["test_a"],
    }
    defaults.update(kwargs)
    return Job(**defaults)


def _make_schedule(**kwargs: Any) -> Schedule:
    defaults = {
        "name": "Test Schedule",
        "cron_expression": "0 0 * * *",
        "workspace_ids": ["WS-001"],
        "enabled": True,
    }
    defaults.update(kwargs)
    return Schedule(**defaults)


class TestStorageContracts:
    """Verify concrete stores satisfy protocol structural checks."""

    def test_sqlite_job_store_satisfies_protocol(self, sqlite_job_store: JobStore) -> None:
        assert isinstance(sqlite_job_store, JobQueryProtocol)
        assert isinstance(sqlite_job_store, JobLifecycleProtocol)
        assert isinstance(sqlite_job_store, JobStoreProtocol)

    def test_sqlite_schedule_store_satisfies_protocol(
        self, sqlite_schedule_store: ScheduleStore
    ) -> None:
        assert isinstance(sqlite_schedule_store, ScheduleCrudProtocol)
        assert isinstance(sqlite_schedule_store, ScheduleRuntimeProtocol)
        assert isinstance(sqlite_schedule_store, ScheduleStoreProtocol)

    def test_azure_job_store_satisfies_protocol(self, azure_job_store: AzureTableJobStore) -> None:
        assert isinstance(azure_job_store, JobQueryProtocol)
        assert isinstance(azure_job_store, JobLifecycleProtocol)
        assert isinstance(azure_job_store, JobStoreProtocol)

    def test_azure_schedule_store_satisfies_protocol(
        self, azure_schedule_store: AzureTableScheduleStore
    ) -> None:
        assert isinstance(azure_schedule_store, ScheduleCrudProtocol)
        assert isinstance(azure_schedule_store, ScheduleRuntimeProtocol)
        assert isinstance(azure_schedule_store, ScheduleStoreProtocol)

    def test_job_create_and_get(self, job_store: JobStoreProtocol) -> None:
        """create() persists a job; get() retrieves it by ID."""
        job = _make_job()
        created = job_store.create(job)
        assert created.id == job.id
        fetched = job_store.get(job.id)
        assert fetched is not None
        assert fetched.id == job.id
        assert fetched.workspace_id == "WS-001"
        assert fetched.test_ids == ["test_a"]

    def test_job_get_missing_returns_none(self, job_store: JobStoreProtocol) -> None:
        """get() returns None for a non-existent job ID."""
        result = job_store.get(uuid4())
        assert result is None

    def test_job_update_persists_changes(self, job_store: JobStoreProtocol) -> None:
        """update() persists status and field changes."""
        job = _make_job()
        job_store.create(job)
        job.start()
        job_store.update(job)
        fetched = job_store.get(job.id)
        assert fetched is not None
        assert fetched.status == JobStatus.RUNNING

    def test_job_update_nonexistent_is_noop(self, job_store: JobStoreProtocol) -> None:
        """update() on a non-existent job is a no-op (no exception)."""
        job = _make_job()
        job_store.update(job)

    def test_job_get_active_filters_terminal(self, job_store: JobStoreProtocol) -> None:
        """get_active() excludes completed/failed/cancelled jobs."""
        active = _make_job(workspace_id="WS-ACTIVE")
        job_store.create(active)
        completed = _make_job(workspace_id="WS-DONE")
        completed.start()
        completed.complete({"ok": True})
        job_store.create(completed)
        results = job_store.get_active()
        ids = [j.id for j in results]
        assert active.id in ids
        assert completed.id not in ids

    def test_job_get_active_with_workspace_filter(self, job_store: JobStoreProtocol) -> None:
        """get_active(workspace_id=...) filters by workspace."""
        j1 = _make_job(workspace_id="WS-A")
        j2 = _make_job(workspace_id="WS-B")
        job_store.create(j1)
        job_store.create(j2)
        results = job_store.get_active(workspace_id="WS-A")
        assert all(j.workspace_id == "WS-A" for j in results)

    def test_job_get_history_returns_terminal_jobs(self, job_store: JobStoreProtocol) -> None:
        """get_history() returns only terminal jobs."""
        active = _make_job(workspace_id="WS-HIST")
        job_store.create(active)
        done = _make_job(workspace_id="WS-HIST")
        done.start()
        done.complete({"ok": True})
        job_store.create(done)
        history = job_store.get_history(JobHistoryQuery(workspace_id="WS-HIST"))
        for j in history:
            assert j.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED)

    def test_schedule_create_and_get(self, schedule_store: ScheduleStoreProtocol) -> None:
        """create() persists a schedule; get() retrieves it."""
        sched = _make_schedule()
        created = schedule_store.create(sched)
        assert created.id == sched.id
        fetched = schedule_store.get(sched.id)
        assert fetched is not None
        assert fetched.name == "Test Schedule"

    def test_schedule_get_missing_returns_none(self, schedule_store: ScheduleStoreProtocol) -> None:
        """get() returns None for non-existent schedule."""
        result = schedule_store.get("nonexistent-id")
        assert result is None

    def test_schedule_list_returns_all(self, schedule_store: ScheduleStoreProtocol) -> None:
        """list() returns all schedules."""
        s1 = _make_schedule(name="S1")
        s2 = _make_schedule(name="S2", enabled=False)
        schedule_store.create(s1)
        schedule_store.create(s2)
        all_schedules = schedule_store.list()
        assert len(all_schedules) >= 2

    def test_schedule_list_enabled_only(self, schedule_store: ScheduleStoreProtocol) -> None:
        """list(enabled_only=True) returns only enabled schedules."""
        enabled = _make_schedule(name="Enabled", enabled=True)
        disabled = _make_schedule(name="Disabled", enabled=False)
        schedule_store.create(enabled)
        schedule_store.create(disabled)
        results = schedule_store.list(enabled_only=True)
        ids = [s.id for s in results]
        assert enabled.id in ids
        assert disabled.id not in ids

    def test_schedule_update_persists_changes(self, schedule_store: ScheduleStoreProtocol) -> None:
        """update() persists field changes."""
        sched = _make_schedule()
        schedule_store.create(sched)
        sched.name = "Updated Name"
        schedule_store.update(sched)
        fetched = schedule_store.get(sched.id)
        assert fetched is not None
        assert fetched.name == "Updated Name"

    def test_schedule_delete_removes_schedule(self, schedule_store: ScheduleStoreProtocol) -> None:
        """delete() removes the schedule; subsequent get() returns None."""
        sched = _make_schedule()
        schedule_store.create(sched)
        assert schedule_store.delete(sched.id) is True
        assert schedule_store.get(sched.id) is None

    def test_schedule_delete_nonexistent_returns_false(
        self, schedule_store: ScheduleStoreProtocol
    ) -> None:
        """delete() returns False for non-existent schedule."""
        assert schedule_store.delete("no-such-id") is False

    def test_schedule_get_enabled_matches_list_enabled_only(
        self, schedule_store: ScheduleStoreProtocol
    ) -> None:
        """get_enabled() returns same results as list(enabled_only=True)."""
        s1 = _make_schedule(name="E1", enabled=True)
        s2 = _make_schedule(name="E2", enabled=False)
        schedule_store.create(s1)
        schedule_store.create(s2)
        enabled_list = schedule_store.list(enabled_only=True)
        get_enabled = schedule_store.get_enabled()
        assert set(s.id for s in enabled_list) == set(s.id for s in get_enabled)

    def test_job_update_detects_concurrent_modification(self) -> None:
        """update() raises ConcurrencyConflictError on ETag mismatch."""
        client = FakeTableClient()
        store = AzureTableJobStore(table_client=client)
        job = _make_job()
        store.create(job)

        original_update = client.update_entity
        call_count = [0]

        def patched_update(entity, *, mode=None, etag=None, match_condition=None):
            key = f"{entity['PartitionKey']}:{entity['RowKey']}"
            if key in client._entities:
                client._entities[key].metadata = _FakeMetadata("modified-by-other")
            return original_update(entity, mode=mode, etag=etag, match_condition=match_condition)

        client.update_entity = patched_update

        job.start()
        with pytest.raises(ConcurrencyConflictError):
            store.update(job)
        store.close()

    def test_job_update_rejects_object_loaded_before_intervening_write(self) -> None:
        """A stale object retains its original ETag and cannot overwrite a newer write."""
        client = FakeTableClient()
        store = AzureTableJobStore(table_client=client)
        original = _make_job()
        store.create(original)
        first = store.get(original.id)
        stale = store.get(original.id)
        assert first is not None
        assert stale is not None

        first.start()
        store.update(first)
        stale.start()

        with pytest.raises(ConcurrencyConflictError):
            store.update(stale)

    def test_workspace_lock_blocks_second_job_and_releases_on_terminal_update(self) -> None:
        """Conditional lock creation preserves one active job per workspace."""
        from src.core.execution.exceptions import WorkspaceLockError

        client = FakeTableClient()
        store = AzureTableJobStore(table_client=client)
        first = _make_job(workspace_id="WS-LOCK")
        second = _make_job(workspace_id="WS-LOCK")
        store.create(first)

        with pytest.raises(WorkspaceLockError):
            store.create(second)

        first.start()
        first.complete({})
        store.update(first)
        store.create(second)

    def test_schedule_update_nonexistent_raises(self) -> None:
        """Schedule update() on non-existent raises ValueError."""
        client = FakeTableClient()
        store = AzureTableScheduleStore(table_client=client)
        sched = _make_schedule()
        with pytest.raises(ValueError, match="not found"):
            store.update(sched)
        store.close()

    def test_schedule_update_rejects_stale_object(self) -> None:
        """Schedules use the ETag captured by their original read."""
        client = FakeTableClient()
        store = AzureTableScheduleStore(table_client=client)
        original = _make_schedule()
        store.create(original)
        first = store.get(original.id)
        stale = store.get(original.id)
        assert first is not None
        assert stale is not None

        first.name = "first"
        store.update(first)
        stale.name = "stale"

        with pytest.raises(ConcurrencyConflictError):
            store.update(stale)

    def test_sqlite_job_store_close_idempotent(self, tmp_path: Path) -> None:
        store = JobStore(db_path=tmp_path / "close.db")
        store.close()
        store.close()

    def test_azure_table_store_close_idempotent(self) -> None:
        client = FakeTableClient()
        store = AzureTableJobStore(table_client=client)
        store.close()
        store.close()
        assert client._closed is False

    @pytest.fixture(params=("sqlite_job_store", "azure_job_store"))
    def job_store(self, request: pytest.FixtureRequest) -> JobStoreProtocol:
        """Return each job store implementation under the shared contract."""
        return request.getfixturevalue(request.param)

    @pytest.fixture(params=("sqlite_schedule_store", "azure_schedule_store"))
    def schedule_store(self, request: pytest.FixtureRequest) -> ScheduleStoreProtocol:
        """Return each schedule store implementation under the shared contract."""
        return request.getfixturevalue(request.param)

    def test_azure_schedule_store_close_idempotent(self) -> None:
        client = FakeTableClient()
        store = AzureTableScheduleStore(table_client=client)
        store.close()
        store.close()
        assert client._closed is False
