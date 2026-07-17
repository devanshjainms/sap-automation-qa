# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for storage factory selection and ownership."""

from pathlib import Path
import pytest
from pytest_mock import MockerFixture
from src.core.models.storage import StorageContext
from src.core.storage.azure_table_store import AzureTableJobStore, AzureTableScheduleStore
from src.core.storage.factory import (
    DEFAULT_AZURE_JOBS_TABLE,
    DEFAULT_AZURE_SCHEDULES_TABLE,
    create_storage_context,
)
from src.core.storage.job_store import JobStore
from src.core.storage.schedule_store import ScheduleStore

_TEST_ENDPOINT = "https://acct.table.core.windows.net"


class TestStorageFactory:
    def test_selects_sqlite_by_default(self, temp_dir: Path) -> None:
        ctx = create_storage_context(db_path=temp_dir / "staf.db")
        assert ctx.backend == "sqlite"
        assert ctx.db is not None
        assert isinstance(ctx.job_store, JobStore)
        assert isinstance(ctx.schedule_store, ScheduleStore)
        assert ctx.owned_resources == (ctx.db,)
        ctx.close()

    def test_explicit_empty_env_keeps_sqlite(self, temp_dir: Path) -> None:
        ctx = create_storage_context(db_path=temp_dir / "staf.db", env={})
        assert ctx.backend == "sqlite"
        ctx.close()

    def test_requires_azure_context_when_endpoint_is_configured(self) -> None:
        with pytest.raises(RuntimeError, match="AzureStorageContext"):
            create_storage_context(env={"AZURE_TABLE_ENDPOINT": _TEST_ENDPOINT})

    def test_uses_default_table_names_from_shared_context(self, mocker: MockerFixture) -> None:
        azure_context = mocker.MagicMock()
        azure_context.has_table = True
        jobs_client = mocker.MagicMock()
        schedules_client = mocker.MagicMock()
        azure_context.get_table_client.side_effect = [jobs_client, schedules_client]

        ctx = create_storage_context(
            env={"AZURE_TABLE_ENDPOINT": _TEST_ENDPOINT},
            azure_context=azure_context,
        )

        assert ctx.backend == "azure_table"
        assert ctx.db is None
        assert isinstance(ctx.job_store, AzureTableJobStore)
        assert isinstance(ctx.schedule_store, AzureTableScheduleStore)
        azure_context.get_table_client.assert_any_call(DEFAULT_AZURE_JOBS_TABLE)
        azure_context.get_table_client.assert_any_call(DEFAULT_AZURE_SCHEDULES_TABLE)

    def test_uses_custom_table_names_from_shared_context(self, mocker: MockerFixture) -> None:
        azure_context = mocker.MagicMock()
        azure_context.has_table = True
        azure_context.get_table_client.side_effect = [mocker.MagicMock(), mocker.MagicMock()]

        create_storage_context(
            env={
                "AZURE_TABLE_ENDPOINT": _TEST_ENDPOINT,
                "AZURE_TABLE_JOBS": "CustomJobs",
                "AZURE_TABLE_SCHEDULES": "CustomSchedules",
            },
            azure_context=azure_context,
        )

        azure_context.get_table_client.assert_any_call("CustomJobs")
        azure_context.get_table_client.assert_any_call("CustomSchedules")

    def test_no_sqlite_file_created_when_azure_context_missing(self, temp_dir: Path) -> None:
        db_path = temp_dir / "should-not-exist.db"
        with pytest.raises(RuntimeError):
            create_storage_context(
                db_path=db_path,
                env={"AZURE_TABLE_ENDPOINT": _TEST_ENDPOINT},
            )
        assert not db_path.exists()

    def test_sqlite_close_closes_db_once(self, mocker: MockerFixture) -> None:
        db = mocker.MagicMock()
        ctx = StorageContext(
            backend="sqlite",
            db=db,
            job_store=mocker.MagicMock(),
            schedule_store=mocker.MagicMock(),
            owned_resources=(db,),
        )
        ctx.close()
        ctx.close()
        db.close.assert_called_once()

    def test_azure_close_closes_stores_but_not_shared_context(self, mocker: MockerFixture) -> None:
        job_store = mocker.MagicMock()
        schedule_store = mocker.MagicMock()
        ctx = StorageContext(
            backend="azure_table",
            db=None,
            job_store=job_store,
            schedule_store=schedule_store,
            owned_resources=(job_store, schedule_store),
        )
        ctx.close()
        ctx.close()
        job_store.close.assert_called_once()
        schedule_store.close.assert_called_once()

    def test_store_close_failure_attempts_both_and_allows_retry(
        self, mocker: MockerFixture
    ) -> None:
        job_store = mocker.MagicMock()
        schedule_store = mocker.MagicMock()
        job_store.close.side_effect = [RuntimeError("job close failed"), None]
        ctx = StorageContext(
            backend="azure_table",
            db=None,
            job_store=job_store,
            schedule_store=schedule_store,
            owned_resources=(job_store, schedule_store),
        )

        with pytest.raises(RuntimeError, match="job close failed"):
            ctx.close()
        schedule_store.close.assert_called_once()

        ctx.close()
        assert job_store.close.call_count == 2
        assert schedule_store.close.call_count == 2

    def test_database_close_failure_allows_retry(self, mocker: MockerFixture) -> None:
        db = mocker.MagicMock()
        db.close.side_effect = [RuntimeError("database close failed"), None]
        ctx = StorageContext(
            backend="sqlite",
            db=db,
            job_store=mocker.MagicMock(),
            schedule_store=mocker.MagicMock(),
            owned_resources=(db,),
        )

        with pytest.raises(RuntimeError, match="database close failed"):
            ctx.close()
        ctx.close()
        assert db.close.call_count == 2

    def test_explicit_ownership_closes_independent_store_even_with_database(
        self, mocker: MockerFixture
    ) -> None:
        """Ownership is defined by owned_resources, not inferred from db presence."""
        db = mocker.MagicMock()
        independent_store = mocker.MagicMock()
        ctx = StorageContext(
            backend="mixed",
            db=db,
            job_store=mocker.MagicMock(),
            schedule_store=independent_store,
            owned_resources=(db, independent_store),
        )

        ctx.close()

        db.close.assert_called_once()
        independent_store.close.assert_called_once()
