# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for AzureTableJobStore and AzureTableScheduleStore."""

from __future__ import annotations
import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from src.core.models.job import Job, JobStatus
from src.core.models.schedule import Schedule


@pytest.fixture
def mock_table_client() -> MagicMock:
    return MagicMock()


@pytest.fixture
def job_store(mock_table_client: MagicMock):
    with patch("src.core.storage.azure_table.TableServiceClient") as mock_svc_cls, patch(
        "src.core.storage.azure_table.DefaultAzureCredential"
    ):
        mock_svc = MagicMock()
        mock_svc.get_table_client.return_value = mock_table_client
        mock_svc_cls.return_value = mock_svc
        from src.core.storage.azure_table import AzureTableJobStore

        return AzureTableJobStore(
            endpoint="https://test.table.core.windows.net",
            table_name="jobs",
        )


@pytest.fixture
def schedule_store(mock_table_client: MagicMock):
    with patch("src.core.storage.azure_table.TableServiceClient") as mock_svc_cls, patch(
        "src.core.storage.azure_table.DefaultAzureCredential"
    ):
        mock_svc = MagicMock()
        mock_svc.get_table_client.return_value = mock_table_client
        mock_svc_cls.return_value = mock_svc
        from src.core.storage.azure_table import AzureTableScheduleStore

        return AzureTableScheduleStore(
            endpoint="https://test.table.core.windows.net",
            table_name="schedules",
        )


class TestAzureTableJobStore:
    """Tests for Azure Table job store operations."""

    def test_create_calls_create_entity(self, job_store, mock_table_client) -> None:
        job = Job(workspace_id="WS-A", test_group="DatabaseHighAvailability")
        result = job_store.create(job)
        mock_table_client.create_entity.assert_called_once()
        assert result.workspace_id == "WS-A"

    def test_get_returns_job(self, job_store, mock_table_client) -> None:
        job_id = str(uuid4())
        mock_table_client.get_entity.return_value = {
            "RowKey": job_id,
            "workspace_id": "WS-A",
            "schedule_id": "",
            "test_group": "DB",
            "test_ids": "[]",
            "status": "pending",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "started_at": "",
            "completed_at": "",
            "error": "",
            "result": "",
            "log_file": "",
            "events": "[]",
            "metadata": "{}",
        }
        job = job_store.get(job_id)
        assert job is not None
        assert str(job.id) == job_id

    def test_get_returns_none_on_missing(self, job_store, mock_table_client) -> None:
        mock_table_client.get_entity.side_effect = Exception("Not found")
        assert job_store.get("missing-id") is None

    def test_update_calls_upsert(self, job_store, mock_table_client) -> None:
        job = Job(workspace_id="WS-A")
        job_store.update(job)
        mock_table_client.upsert_entity.assert_called_once()

    def test_get_active_filters_terminal(self, job_store, mock_table_client) -> None:
        now = datetime.now(timezone.utc).isoformat()
        j1 = str(uuid4())
        j2 = str(uuid4())
        mock_table_client.query_entities.return_value = [
            {
                "RowKey": j1,
                "workspace_id": "WS-A",
                "status": "running",
                "test_ids": "[]",
                "created_at": now,
                "started_at": "",
                "completed_at": "",
                "error": "",
                "result": "",
                "log_file": "",
                "events": "[]",
                "metadata": "{}",
            },
            {
                "RowKey": j2,
                "workspace_id": "WS-A",
                "status": "completed",
                "test_ids": "[]",
                "created_at": now,
                "started_at": "",
                "completed_at": "",
                "error": "",
                "result": "",
                "log_file": "",
                "events": "[]",
                "metadata": "{}",
            },
        ]
        active = job_store.get_active()
        assert len(active) == 1
        assert str(active[0].id) == j1

    def test_has_active_job(self, job_store, mock_table_client) -> None:
        mock_table_client.query_entities.return_value = []
        assert job_store.has_active_job("WS-A") is False

    def test_close_is_noop(self, job_store) -> None:
        job_store.close()

    def test_get_history(self, job_store, mock_table_client) -> None:
        mock_table_client.query_entities.return_value = []
        result = job_store.get_history(workspace_id="WS-A", days=7)
        assert result == []

    def test_get_jobs_for_schedule(self, job_store, mock_table_client) -> None:
        mock_table_client.query_entities.return_value = []
        result = job_store.get_jobs_for_schedule("SCH-1")
        assert result == []


class TestAzureTableScheduleStore:
    """Tests for Azure Table schedule store operations."""

    def test_create_calls_create_entity(self, schedule_store, mock_table_client) -> None:
        schedule = Schedule(name="daily", cron_expression="0 0 * * *")
        result = schedule_store.create(schedule)
        mock_table_client.create_entity.assert_called_once()
        assert result.name == "daily"

    def test_get_returns_schedule(self, schedule_store, mock_table_client) -> None:
        mock_table_client.get_entity.return_value = {
            "RowKey": "SCH-1",
            "name": "daily",
            "description": "",
            "cron_expression": "0 0 * * *",
            "timezone": "UTC",
            "workspace_ids": '["WS-A"]',
            "test_group": "",
            "test_ids": "[]",
            "enabled": True,
            "next_run_time": "",
            "last_run_time": "",
            "last_run_job_ids": "[]",
            "total_runs": 0,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": "",
        }
        schedule = schedule_store.get("SCH-1")
        assert schedule is not None
        assert schedule.name == "daily"

    def test_get_returns_none_on_missing(self, schedule_store, mock_table_client) -> None:
        mock_table_client.get_entity.side_effect = Exception("Not found")
        assert schedule_store.get("missing") is None

    def test_list_returns_all(self, schedule_store, mock_table_client) -> None:
        mock_table_client.query_entities.return_value = []
        assert schedule_store.list() == []

    def test_list_enabled_only(self, schedule_store, mock_table_client) -> None:
        now = datetime.now(timezone.utc).isoformat()
        mock_table_client.query_entities.return_value = [
            {
                "RowKey": "S1",
                "name": "a",
                "cron_expression": "* * * * *",
                "enabled": True,
                "workspace_ids": "[]",
                "test_ids": "[]",
                "created_at": now,
                "updated_at": "",
                "next_run_time": "",
                "last_run_time": "",
                "last_run_job_ids": "[]",
                "total_runs": 0,
            },
            {
                "RowKey": "S2",
                "name": "b",
                "cron_expression": "* * * * *",
                "enabled": False,
                "workspace_ids": "[]",
                "test_ids": "[]",
                "created_at": now,
                "updated_at": "",
                "next_run_time": "",
                "last_run_time": "",
                "last_run_job_ids": "[]",
                "total_runs": 0,
            },
        ]
        result = schedule_store.list(enabled_only=True)
        assert len(result) == 1

    def test_update_calls_upsert(self, schedule_store, mock_table_client) -> None:
        schedule = Schedule(name="weekly", cron_expression="0 0 * * 0")
        schedule_store.update(schedule)
        mock_table_client.upsert_entity.assert_called_once()

    def test_delete_returns_true(self, schedule_store, mock_table_client) -> None:
        assert schedule_store.delete("SCH-1") is True
        mock_table_client.delete_entity.assert_called_once()

    def test_delete_returns_false_on_error(self, schedule_store, mock_table_client) -> None:
        mock_table_client.delete_entity.side_effect = Exception("fail")
        assert schedule_store.delete("missing") is False

    def test_get_enabled(self, schedule_store, mock_table_client) -> None:
        mock_table_client.query_entities.return_value = []
        assert schedule_store.get_enabled() == []

    def test_close_is_noop(self, schedule_store) -> None:
        schedule_store.close()
