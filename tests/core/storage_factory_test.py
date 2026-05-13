# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for storage factory — Azure Table vs SQLite selection."""

from __future__ import annotations
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from src.core.storage.factory import create_job_store, create_schedule_store


class TestCreateJobStore:
    """Tests for create_job_store factory."""

    def test_returns_sqlite_when_no_endpoint(self, tmp_path: Path) -> None:
        """Without AZURE_TABLE_ENDPOINT, returns SQLite JobStore."""
        with patch.dict("os.environ", {}, clear=False):
            if "AZURE_TABLE_ENDPOINT" in __import__("os").environ:
                __import__("os").environ.pop("AZURE_TABLE_ENDPOINT")
            store = create_job_store(tmp_path)

        from src.core.storage.job_store import JobStore

        assert isinstance(store, JobStore)
        store.close()

    def test_returns_sqlite_when_endpoint_empty(self, tmp_path: Path) -> None:
        """Empty AZURE_TABLE_ENDPOINT falls back to SQLite."""
        with patch.dict("os.environ", {"AZURE_TABLE_ENDPOINT": ""}, clear=False):
            store = create_job_store(tmp_path)

        from src.core.storage.job_store import JobStore

        assert isinstance(store, JobStore)
        store.close()

    def test_returns_azure_table_when_endpoint_set(self, tmp_path: Path) -> None:
        """With AZURE_TABLE_ENDPOINT, returns AzureTableJobStore."""
        mock_service = MagicMock()
        mock_service.get_table_client.return_value = MagicMock()

        with patch.dict(
            "os.environ",
            {"AZURE_TABLE_ENDPOINT": "https://test.table.core.windows.net"},
        ), patch(
            "src.core.storage.azure_table.TableServiceClient",
            return_value=mock_service,
        ), patch(
            "src.core.storage.azure_table.DefaultAzureCredential",
        ):
            store = create_job_store(tmp_path)

        from src.core.storage.azure_table import AzureTableJobStore

        assert isinstance(store, AzureTableJobStore)

    def test_uses_custom_table_name(self, tmp_path: Path) -> None:
        """AZURE_TABLE_JOBS overrides the default table name."""
        mock_service = MagicMock()
        mock_service.get_table_client.return_value = MagicMock()

        with patch.dict(
            "os.environ",
            {
                "AZURE_TABLE_ENDPOINT": "https://test.table.core.windows.net",
                "AZURE_TABLE_JOBS": "custom_jobs",
            },
        ), patch(
            "src.core.storage.azure_table.TableServiceClient",
            return_value=mock_service,
        ), patch(
            "src.core.storage.azure_table.DefaultAzureCredential",
        ):
            create_job_store(tmp_path)

        mock_service.create_table_if_not_exists.assert_called_with("custom_jobs")
        mock_service.get_table_client.assert_called_with("custom_jobs")


class TestCreateScheduleStore:
    """Tests for create_schedule_store factory."""

    def test_returns_sqlite_when_no_endpoint(self, tmp_path: Path) -> None:
        """Without AZURE_TABLE_ENDPOINT, returns SQLite ScheduleStore."""
        with patch.dict("os.environ", {}, clear=False):
            if "AZURE_TABLE_ENDPOINT" in __import__("os").environ:
                __import__("os").environ.pop("AZURE_TABLE_ENDPOINT")
            store = create_schedule_store(tmp_path)

        from src.core.storage.schedule_store import ScheduleStore

        assert isinstance(store, ScheduleStore)
        store.close()

    def test_returns_azure_table_when_endpoint_set(self, tmp_path: Path) -> None:
        """With AZURE_TABLE_ENDPOINT, returns AzureTableScheduleStore."""
        mock_service = MagicMock()
        mock_service.get_table_client.return_value = MagicMock()

        with patch.dict(
            "os.environ",
            {"AZURE_TABLE_ENDPOINT": "https://test.table.core.windows.net"},
        ), patch(
            "src.core.storage.azure_table.TableServiceClient",
            return_value=mock_service,
        ), patch(
            "src.core.storage.azure_table.DefaultAzureCredential",
        ):
            store = create_schedule_store(tmp_path)

        from src.core.storage.azure_table import AzureTableScheduleStore

        assert isinstance(store, AzureTableScheduleStore)

    def test_uses_custom_table_name(self, tmp_path: Path) -> None:
        """AZURE_TABLE_SCHEDULES overrides the default table name."""
        mock_service = MagicMock()
        mock_service.get_table_client.return_value = MagicMock()

        with patch.dict(
            "os.environ",
            {
                "AZURE_TABLE_ENDPOINT": "https://test.table.core.windows.net",
                "AZURE_TABLE_SCHEDULES": "my_schedules",
            },
        ), patch(
            "src.core.storage.azure_table.TableServiceClient",
            return_value=mock_service,
        ), patch(
            "src.core.storage.azure_table.DefaultAzureCredential",
        ):
            create_schedule_store(tmp_path)

        mock_service.create_table_if_not_exists.assert_called_with("my_schedules")

    def test_shares_staf_db_when_provided(self, tmp_path: Path) -> None:
        """Passing staf_db reuses the existing database connection."""
        from src.core.storage.staf_store import StafStore

        db = StafStore(tmp_path / "shared.db")
        with patch.dict("os.environ", {}, clear=False):
            if "AZURE_TABLE_ENDPOINT" in __import__("os").environ:
                __import__("os").environ.pop("AZURE_TABLE_ENDPOINT")
            store = create_schedule_store(tmp_path, staf_db=db)

        from src.core.storage.schedule_store import ScheduleStore

        assert isinstance(store, ScheduleStore)
        db.close()
