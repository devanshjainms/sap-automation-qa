# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Azure Table Storage backend for jobs and schedules.
"""

from __future__ import annotations
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, List, Optional
from uuid import UUID
from azure.data.tables import TableServiceClient, TableClient
from azure.identity import DefaultAzureCredential
from src.core.models.job import Job, JobStatus
from src.core.models.schedule import Schedule

logger = logging.getLogger(__name__)

_PARTITION_KEY = "staf"


def _dt_to_str(dt: Optional[datetime]) -> str:
    """Convert datetime to ISO string, empty string if None."""
    return dt.isoformat() if dt else ""


def _str_to_dt(value: str) -> Optional[datetime]:
    """Convert ISO string to datetime, None if empty."""
    return datetime.fromisoformat(value) if value else None


class AzureTableJobStore:
    """Job storage backed by Azure Table Storage.

    :param endpoint: Azure Table Storage endpoint URL.
    :param table_name: Table name for jobs.
    """

    def __init__(self, endpoint: str, table_name: str = "jobs") -> None:
        credential = DefaultAzureCredential()
        service = TableServiceClient(endpoint=endpoint, credential=credential)
        service.create_table_if_not_exists(table_name)
        self._client: TableClient = service.get_table_client(table_name)
        logger.info("Azure Table job storage: %s/%s", endpoint, table_name)

    def close(self) -> None:
        """No-op — Azure Table uses stateless HTTP."""

    def _to_entity(self, job: Job) -> dict[str, Any]:
        """Serialize a Job to a table entity."""
        status = str(job.status)
        return {
            "PartitionKey": _PARTITION_KEY,
            "RowKey": str(job.id),
            "workspace_id": job.workspace_id,
            "schedule_id": job.schedule_id or "",
            "test_group": job.test_group or "",
            "test_ids": json.dumps(job.test_ids),
            "status": status,
            "created_at": _dt_to_str(job.created_at),
            "started_at": _dt_to_str(job.started_at),
            "completed_at": _dt_to_str(job.completed_at),
            "error": job.error or "",
            "result": json.dumps(job.result, default=str) if job.result else "",
            "log_file": job.log_file or "",
            "events": json.dumps(
                [e.model_dump(mode="json") for e in job.events],
                default=str,
            ),
            "metadata": json.dumps(job.metadata, default=str),
        }

    @staticmethod
    def _to_job(entity: dict[str, Any]) -> Job:
        """Deserialize a table entity to a Job."""
        data: dict[str, Any] = {
            "id": entity["RowKey"],
            "workspace_id": entity["workspace_id"],
            "schedule_id": entity.get("schedule_id") or None,
            "test_group": entity.get("test_group") or None,
            "test_ids": json.loads(entity.get("test_ids", "[]")),
            "status": entity["status"],
            "started_at": _str_to_dt(entity.get("started_at", "")),
            "completed_at": _str_to_dt(entity.get("completed_at", "")),
            "error": entity.get("error") or None,
            "result": json.loads(entity["result"]) if entity.get("result") else None,
            "log_file": entity.get("log_file") or None,
            "events": json.loads(entity.get("events", "[]")),
            "metadata": json.loads(entity.get("metadata", "{}")),
        }
        created = _str_to_dt(entity.get("created_at", ""))
        if created is not None:
            data["created_at"] = created
        return Job.model_validate(data)

    def create(self, job: Job) -> Job:
        """Create a new job."""
        self._client.create_entity(self._to_entity(job))
        logger.info("Created job %s for workspace %s", job.id, job.workspace_id)
        return job

    def get(self, job_id: UUID | str) -> Optional[Job]:
        """Get a job by ID."""
        try:
            entity = self._client.get_entity(_PARTITION_KEY, str(job_id))
            return self._to_job(entity)
        except Exception as exc:
            logger.warning("Failed to get job %s: %s", job_id, exc)
            return None

    def update(self, job: Job) -> None:
        """Update an existing job."""
        self._client.upsert_entity(self._to_entity(job))
        logger.debug("Updated job %s (status=%s)", job.id, job.status)

    def get_active(self, workspace_id: Optional[str] = None) -> List[Job]:
        """Get active (non-terminal) jobs."""
        terminal = {
            JobStatus.COMPLETED.value,
            JobStatus.FAILED.value,
            JobStatus.CANCELLED.value,
        }
        filt = f"PartitionKey eq '{_PARTITION_KEY}'"
        if workspace_id:
            filt += f" and workspace_id eq '{workspace_id}'"
        jobs = [self._to_job(e) for e in self._client.query_entities(filt)]
        return [j for j in jobs if j.status not in terminal]

    def get_active_for_workspace(self, workspace_id: str) -> Optional[Job]:
        """Get the active job for a workspace."""
        active = self.get_active(workspace_id)
        return active[0] if active else None

    def has_active_job(self, workspace_id: str) -> bool:
        """Check if workspace has an active job."""
        return self.get_active_for_workspace(workspace_id) is not None

    def get_history(
        self,
        workspace_id: Optional[str] = None,
        schedule_id: Optional[str] = None,
        status: Optional[JobStatus] = None,
        days: int = 7,
        limit: int = 100,
    ) -> List[Job]:
        """Get job history."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        filt = f"PartitionKey eq '{_PARTITION_KEY}' and created_at ge '{cutoff}'"
        if workspace_id:
            filt += f" and workspace_id eq '{workspace_id}'"
        if schedule_id:
            filt += f" and schedule_id eq '{schedule_id}'"

        jobs = [self._to_job(e) for e in self._client.query_entities(filt)]
        if status:
            status_val = status.value if hasattr(status, "value") else status
            jobs = [j for j in jobs if j.status == status_val]
        jobs.sort(key=lambda j: j.created_at, reverse=True)
        return jobs[:limit]

    def get_jobs_for_schedule(
        self,
        schedule_id: str,
        limit: int = 10,
    ) -> List[Job]:
        """Get recent jobs for a schedule."""
        filt = f"PartitionKey eq '{_PARTITION_KEY}' " f"and schedule_id eq '{schedule_id}'"
        jobs = [self._to_job(e) for e in self._client.query_entities(filt)]
        jobs.sort(key=lambda j: j.created_at, reverse=True)
        return jobs[:limit]


class AzureTableScheduleStore:
    """Schedule storage backed by Azure Table Storage.

    :param endpoint: Azure Table Storage endpoint URL.
    :param table_name: Table name for schedules.
    """

    def __init__(self, endpoint: str, table_name: str = "schedules") -> None:
        credential = DefaultAzureCredential()
        service = TableServiceClient(endpoint=endpoint, credential=credential)
        service.create_table_if_not_exists(table_name)
        self._client: TableClient = service.get_table_client(table_name)
        logger.info("Azure Table schedule storage: %s/%s", endpoint, table_name)

    def close(self) -> None:
        """No-op — Azure Table uses stateless HTTP."""

    def _to_entity(self, schedule: Schedule) -> dict[str, Any]:
        """Serialize a Schedule to a table entity."""
        return {
            "PartitionKey": _PARTITION_KEY,
            "RowKey": schedule.id,
            "name": schedule.name,
            "description": schedule.description,
            "cron_expression": schedule.cron_expression,
            "timezone": schedule.timezone,
            "workspace_ids": json.dumps(schedule.workspace_ids),
            "test_group": schedule.test_group or "",
            "test_ids": json.dumps(schedule.test_ids),
            "enabled": schedule.enabled,
            "next_run_time": _dt_to_str(schedule.next_run_time),
            "last_run_time": _dt_to_str(schedule.last_run_time),
            "last_run_job_ids": json.dumps(schedule.last_run_job_ids),
            "total_runs": schedule.total_runs,
            "created_at": _dt_to_str(schedule.created_at),
            "updated_at": _dt_to_str(schedule.updated_at),
        }

    @staticmethod
    def _to_schedule(entity: dict[str, Any]) -> Schedule:
        """Deserialize a table entity to a Schedule."""
        data: dict[str, Any] = {
            "id": entity["RowKey"],
            "name": entity.get("name", ""),
            "description": entity.get("description", ""),
            "cron_expression": entity["cron_expression"],
            "timezone": entity.get("timezone", "UTC"),
            "workspace_ids": json.loads(entity.get("workspace_ids", "[]")),
            "test_group": entity.get("test_group") or None,
            "test_ids": json.loads(entity.get("test_ids", "[]")),
            "enabled": entity.get("enabled", True),
            "last_run_job_ids": json.loads(entity.get("last_run_job_ids", "[]")),
            "total_runs": entity.get("total_runs", 0),
        }
        for dt_field in ("next_run_time", "last_run_time", "created_at", "updated_at"):
            val = _str_to_dt(entity.get(dt_field, ""))
            if val is not None:
                data[dt_field] = val
        return Schedule.model_validate(data)

    def create(self, schedule: Schedule) -> Schedule:
        """Create a new schedule."""
        self._client.create_entity(self._to_entity(schedule))
        logger.info("Created schedule %s", schedule.id)
        return schedule

    def get(self, schedule_id: str) -> Optional[Schedule]:
        """Get a schedule by ID."""
        try:
            entity = self._client.get_entity(_PARTITION_KEY, schedule_id)
            return self._to_schedule(entity)
        except Exception:
            return None

    def list(self, enabled_only: bool = False) -> List[Schedule]:
        """List all schedules."""
        filt = f"PartitionKey eq '{_PARTITION_KEY}'"
        schedules = [self._to_schedule(e) for e in self._client.query_entities(filt)]
        if enabled_only:
            schedules = [s for s in schedules if s.enabled]
        return schedules

    def update(self, schedule: Schedule) -> Schedule:
        """Update an existing schedule."""
        self._client.upsert_entity(self._to_entity(schedule))
        logger.debug("Updated schedule %s", schedule.id)
        return schedule

    def delete(self, schedule_id: str) -> bool:
        """Delete a schedule."""
        try:
            self._client.delete_entity(_PARTITION_KEY, schedule_id)
            return True
        except Exception:
            return False

    def get_enabled(self) -> List[Schedule]:
        """Get all enabled schedules."""
        return self.list(enabled_only=True)
