# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Consumer-focused storage protocols (P1-WP-002D).

Each protocol captures *exactly* the methods that a specific consumer calls.
Concrete stores (``JobStore``, ``AzureTableJobStore``, etc.) keep their names
unchanged; protocols use distinct ``…Protocol`` suffixes to avoid collision.
"""

from __future__ import annotations
from typing import List, Optional, Protocol, runtime_checkable, Iterable, Any, Mapping, Dict
from uuid import UUID
from src.core.models.job import Job, JobHistoryQuery
from src.core.models.schedule import Schedule


@runtime_checkable
class JobQueryProtocol(Protocol):
    """Job read operations consumed by jobs routes."""

    def get(self, job_id: UUID | str) -> Optional[Job]: ...

    def get_active(self, workspace_id: Optional[str] = None) -> List[Job]: ...

    def get_history(
        self,
        query: Optional[JobHistoryQuery] = None,
    ) -> List[Job]: ...

    def get_jobs_for_schedule(
        self,
        schedule_id: str,
        limit: int = 50,
    ) -> List[Job]: ...


@runtime_checkable
class JobLifecycleProtocol(Protocol):
    """Job persistence operations consumed by JobWorker."""

    def get(self, job_id: UUID | str) -> Optional[Job]: ...

    def get_active(self, workspace_id: Optional[str] = None) -> List[Job]: ...

    def get_active_for_workspace(self, workspace_id: str) -> Optional[Job]: ...

    def create(self, job: Job) -> Job: ...

    def update(self, job: Job) -> None: ...


@runtime_checkable
class JobStoreProtocol(JobQueryProtocol, JobLifecycleProtocol, Protocol):
    """Full job store protocol for StorageContext / backend composition.

    Satisfied by both SQLite ``JobStore`` and ``AzureTableJobStore``.
    """

    def close(self) -> None: ...


@runtime_checkable
class ScheduleCrudProtocol(Protocol):
    """Schedule operations consumed by schedules routes."""

    def get(self, schedule_id: str) -> Optional[Schedule]: ...

    def list(self, enabled_only: bool = False) -> List[Schedule]: ...

    def create(self, schedule: Schedule) -> Schedule: ...

    def update(self, schedule: Schedule) -> Schedule: ...

    def delete(self, schedule_id: str) -> bool: ...


@runtime_checkable
class ScheduleRuntimeProtocol(Protocol):
    """Schedule operations consumed by SchedulerService at runtime."""

    def get(self, schedule_id: str) -> Optional[Schedule]: ...

    def get_enabled(self) -> List[Schedule]: ...

    def update(self, schedule: Schedule) -> Schedule: ...


@runtime_checkable
class ScheduleStoreProtocol(ScheduleCrudProtocol, ScheduleRuntimeProtocol, Protocol):
    """Full schedule store protocol for StorageContext / backend composition.

    Satisfied by both SQLite ``ScheduleStore`` and ``AzureTableScheduleStore``.
    """

    def close(self) -> None: ...


class ContainerClientProtocol(Protocol):
    """Azure Blob container operations required by the workspace backend."""

    def list_blobs(self, **kwargs: Any) -> Iterable[Any]:
        """List blobs matching optional filters."""
        raise NotImplementedError

    def walk_blobs(self, **kwargs: Any) -> Iterable[Any]:
        """Walk virtual directory prefixes."""
        raise NotImplementedError

    def get_blob_client(self, blob: str) -> Any:
        """Return a client for one blob."""
        raise NotImplementedError


class TableClientProtocol(Protocol):
    """Azure Table client operations required by STAF stores."""

    def create_entity(self, entity: Mapping[str, Any]) -> Any:
        """Create one table entity."""
        raise NotImplementedError

    def get_entity(self, partition_key: str, row_key: str) -> Any:
        """Read one table entity."""
        raise NotImplementedError

    def update_entity(
        self,
        entity: Mapping[str, Any],
        *,
        mode: Any = None,
        etag: Any = None,
        match_condition: Any = None,
    ) -> Any:
        """Update one table entity."""
        raise NotImplementedError

    def delete_entity(
        self,
        partition_key: str,
        row_key: str,
        *,
        etag: Any = None,
        match_condition: Any = None,
    ) -> None:
        """Delete one table entity."""
        raise NotImplementedError

    def query_entities(
        self,
        query_filter: str,
        *,
        parameters: Optional[Dict[str, Any]] = None,
    ) -> Iterable[Any]:
        """Query table entities."""
        raise NotImplementedError
