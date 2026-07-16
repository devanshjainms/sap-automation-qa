# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for storage factory selection and ownership."""

from pathlib import Path
import pytest
from pytest_mock import MockerFixture
from src.core.models.storage import StorageContext
from src.core.contracts.storage import JobStoreProtocol, ScheduleStoreProtocol
from src.core.storage.factory import (
    DEFAULT_AZURE_JOBS_TABLE,
    DEFAULT_AZURE_SCHEDULES_TABLE,
    create_storage_context,
)
from src.core.models.job import Job
from src.core.storage.staf_store import StafStore

_TEST_ENDPOINT = "https://acct.table.core.windows.net"


class TestStorageFactory:
    """Verify storage factory backend selection, ownership, and close semantics."""

    def test_selects_sqlite_by_default(self, temp_dir: Path) -> None:
        """Select sqlite backend when no Azure endpoint is configured."""
        ctx = create_storage_context(db_path=temp_dir / "staf.db")
        job = Job(workspace_id="WS-001")
        assert ctx.backend == "sqlite"
        assert isinstance(ctx.db, StafStore)
        ctx.job_store.create(job)
        assert ctx.db.conn.execute(
            "SELECT workspace_id FROM jobs WHERE id = ?", (str(job.id),)
        ).fetchone() == (job.workspace_id,)
        ctx.close()

    def test_explicit_empty_env_keeps_sqlite(self, temp_dir: Path) -> None:
        """Fall back to sqlite when env dict is empty and has no Azure endpoint."""
        ctx = create_storage_context(db_path=temp_dir / "staf.db", env={})
        assert ctx.backend == "sqlite"
        ctx.close()

    def test_requires_azure_context_when_endpoint_is_configured(self) -> None:
        """Raise RuntimeError when table endpoint is set but no AzureStorageContext is provided."""
        with pytest.raises(RuntimeError, match="AzureStorageContext"):
            create_storage_context(env={"AZURE_TABLE_ENDPOINT": _TEST_ENDPOINT})

    def test_uses_default_table_names_from_shared_context(self, mocker: MockerFixture) -> None:
        """Create azure_table backend using default table names when env overrides are absent."""
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
        azure_context.get_table_client.assert_any_call(DEFAULT_AZURE_JOBS_TABLE)
        azure_context.get_table_client.assert_any_call(DEFAULT_AZURE_SCHEDULES_TABLE)
        ctx.job_store.create(Job(workspace_id="WS-001"))
        ctx.schedule_store.list()
        assert jobs_client.create_entity.called
        schedules_client.query_entities.assert_called_once()

    def test_uses_custom_table_names_from_shared_context(self, mocker: MockerFixture) -> None:
        """Override default table names with AZURE_TABLE_JOBS and AZURE_TABLE_SCHEDULES env vars."""
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
        """Ensure no sqlite file is created on disk when factory raises for missing Azure context."""
        db_path = temp_dir / "should-not-exist.db"
        with pytest.raises(RuntimeError):
            create_storage_context(
                db_path=db_path,
                env={"AZURE_TABLE_ENDPOINT": _TEST_ENDPOINT},
            )
        assert not db_path.exists()

    def test_azure_context_without_table_raises(self, mocker: MockerFixture) -> None:
        """Raise RuntimeError when AzureStorageContext lacks table service capability."""
        azure_context = mocker.MagicMock()
        azure_context.has_table = False
        with pytest.raises(RuntimeError, match="AzureStorageContext"):
            create_storage_context(
                env={"AZURE_TABLE_ENDPOINT": _TEST_ENDPOINT},
                azure_context=azure_context,
            )

    def test_whitespace_only_endpoint_uses_sqlite(self, temp_dir: Path) -> None:
        """Treat whitespace-only AZURE_TABLE_ENDPOINT as absent and select sqlite."""
        ctx = create_storage_context(
            db_path=temp_dir / "staf.db",
            env={"AZURE_TABLE_ENDPOINT": "   "},
        )
        assert ctx.backend == "sqlite"
        ctx.close()

    def test_sqlite_close_closes_db_once(self, mocker: MockerFixture) -> None:
        """Close sqlite database exactly once even when close is called twice."""
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
        """Close owned azure stores exactly once without closing the shared context."""
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
        """Attempt closing both stores when the first fails and allow a successful retry."""
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
        """Allow a second close attempt after the database close raises on the first call."""
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
        """Close both the database and an independently owned store listed in owned_resources."""
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

    def test_sqlite_roundtrip_preserves_operational_metadata(self, temp_dir: Path) -> None:
        """Round-trip a job through sqlite and verify actor, approval_ref, incident_ticket, offline."""
        ctx = create_storage_context(db_path=temp_dir / "staf.db", env={})
        job = Job(
            workspace_id="WS-001",
            actor="operator@example.com",
            approval_ref="CHG-123",
            incident_ticket="INC-456",
            offline=True,
        )
        ctx.job_store.create(job)

        restored = ctx.job_store.get(job.id)
        ctx.close()

        assert restored is not None
        assert restored.actor == job.actor
        assert restored.approval_ref == job.approval_ref
        assert restored.incident_ticket == job.incident_ticket
        assert restored.offline is True

    def test_sqlite_roundtrip_preserves_empty_result(self, temp_dir: Path) -> None:
        """Persist and restore a job with an empty result dict without it becoming None."""
        ctx = create_storage_context(db_path=temp_dir / "staf.db", env={})
        job = Job(workspace_id="WS-001", result={})
        ctx.job_store.create(job)

        restored = ctx.job_store.get(job.id)
        ctx.close()

        assert restored is not None
        assert restored.result == {}

    def test_created_stores_satisfy_storage_protocols(self, temp_dir: Path) -> None:
        """Confirm job_store and schedule_store satisfy their respective Protocol interfaces."""
        ctx = create_storage_context(db_path=temp_dir / "staf.db", env={})

        assert isinstance(ctx.job_store, JobStoreProtocol)
        assert isinstance(ctx.schedule_store, ScheduleStoreProtocol)

        ctx.close()
