# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for AzureTableJobStore and AzureTableScheduleStore."""

import inspect
from datetime import datetime, timedelta, timezone
from collections.abc import Callable
from uuid import uuid4
import pytest
from pytest_mock import MockerFixture, MockType
from azure.core import MatchConditions
from azure.core.exceptions import HttpResponseError, ResourceExistsError, ResourceNotFoundError
from azure.data.tables import TableEntity
from src.core.exceptions import ConcurrencyConflictError, EntityTooLargeError
from src.core.models.job import Job, JobEvent, JobEventType, JobHistoryQuery, JobStatus
from src.core.models.schedule import Schedule
from src.core.storage.azure_table_store import (
    AzureTableJobStore,
    AzureTableScheduleStore,
    _validate_entity_size,
)


def _entity_with_etag(
    entity: dict,
    etag: str = 'W/"etag-1"',
    *,
    mock_factory: Callable[[], MockType],
) -> MockType:
    """Wrap a plain dict entity with a ``.metadata`` attribute like the SDK."""
    wrapped = mock_factory()
    wrapped.__getitem__.side_effect = entity.__getitem__
    wrapped.__contains__.side_effect = entity.__contains__
    wrapped.get.side_effect = entity.get
    wrapped.metadata = {"etag": etag}
    return wrapped


class TestAzureTableStore:
    """Direct unit tests for the ``_validate_entity_size`` helper."""

    @pytest.fixture
    def mock_table_client(self, mocker: MockerFixture) -> MockType:
        """Provide a MagicMock standing in for an Azure TableClient."""
        client = mocker.MagicMock()
        client.update_entity.return_value = {}
        return client

    @pytest.fixture
    def job_store(self, mock_table_client: MockType) -> AzureTableJobStore:
        """Create an AzureTableJobStore backed by the mock table client."""
        return AzureTableJobStore(table_client=mock_table_client, table_name="Jobs")

    @pytest.fixture
    def schedule_store(self, mock_table_client: MockType) -> AzureTableScheduleStore:
        """Create an AzureTableScheduleStore backed by the mock table client."""
        return AzureTableScheduleStore(table_client=mock_table_client, table_name="Schedules")

    def test_string_property_over_64kib_is_rejected(self) -> None:
        """Reject a single string property exceeding the 64 KiB Azure Table limit."""
        entity = {"PartitionKey": "staf", "RowKey": "id-1", "big": "x" * (64 * 1024 + 1)}
        with pytest.raises(EntityTooLargeError, match="big"):
            _validate_entity_size(entity, "job")

    def test_ascii_property_over_utf16_limit_is_rejected(self) -> None:
        """Reject an ASCII string property whose UTF-16 encoded size exceeds the limit."""
        entity = {"PartitionKey": "staf", "RowKey": "id-1", "big": "x" * 40_000}
        with pytest.raises(EntityTooLargeError, match="big"):
            _validate_entity_size(entity, "job")

    def test_total_entity_over_1mib_is_rejected(self) -> None:
        """Reject an entity whose total estimated size exceeds the 1 MiB limit."""
        entity = {"PartitionKey": "staf", "RowKey": "id-1"}
        for i in range(40):
            entity[f"field_{i}"] = "y" * (30 * 1024)
        with pytest.raises(EntityTooLargeError, match="1 MiB"):
            _validate_entity_size(entity, "job")

    def test_boundary_safe_entity_passes(self) -> None:
        """Accept an entity well within size limits without raising."""
        entity = {
            "PartitionKey": "staf",
            "RowKey": "id-1",
            "workspace_id": "WS-A",
            "notes": "n" * 1024,
        }
        _validate_entity_size(entity, "job")

    def test_requires_endpoint_or_table_client(self) -> None:
        """Raise ValueError when neither endpoint nor table_client is supplied."""
        with pytest.raises(ValueError, match="endpoint is required"):
            AzureTableJobStore()

    def test_requires_credential_when_endpoint_given(self) -> None:
        """Raise ValueError when endpoint is provided without a credential."""
        with pytest.raises(ValueError, match="credential is required"):
            AzureTableJobStore(endpoint="https://acct.table.core.windows.net")

    def test_constructs_from_endpoint_with_credential(self, mocker: MockerFixture) -> None:
        """Construct a job store from endpoint and credential, creating the table if needed."""
        mock_svc_cls = mocker.patch("src.core.storage.azure_table_store.TableServiceClient")
        mock_svc = mocker.MagicMock()
        mock_client = mocker.MagicMock()
        mock_svc.get_table_client.return_value = mock_client
        mock_svc_cls.return_value = mock_svc
        mock_cred = mocker.MagicMock()

        store = AzureTableJobStore(
            endpoint="https://acct.table.core.windows.net",
            table_name="CustomJobs",
            credential=mock_cred,
        )

        mock_svc_cls.assert_called_once_with(
            endpoint="https://acct.table.core.windows.net",
            credential=mock_cred,
        )
        mock_svc.create_table_if_not_exists.assert_called_once_with("CustomJobs")
        mock_svc.get_table_client.assert_called_once_with("CustomJobs")
        assert store.table_name == "CustomJobs"

    def test_no_connection_string_or_account_key_used(self) -> None:
        """Verify init signature does not accept connection_string or account_key parameters."""
        sig = inspect.signature(AzureTableJobStore.__init__)
        assert "account_key" not in sig.parameters
        assert "connection_string" not in sig.parameters

    def test_close_closes_owned_service_exactly_once(self, mocker: MockerFixture) -> None:
        """Close the owned TableServiceClient exactly once on repeated close calls."""
        mock_svc_cls = mocker.patch("src.core.storage.azure_table_store.TableServiceClient")
        mock_svc = mocker.MagicMock()
        mock_client = mocker.MagicMock()
        mock_svc.get_table_client.return_value = mock_client
        mock_svc_cls.return_value = mock_svc
        mock_cred = mocker.MagicMock()

        store = AzureTableJobStore(
            endpoint="https://acct.table.core.windows.net", credential=mock_cred
        )
        store.close()
        store.close()

        mock_svc.close.assert_called_once()
        mock_cred.close.assert_not_called()

    def test_injected_client_close_does_not_own_service(self, mocker: MockerFixture) -> None:
        """Skip service close when an injected table client is used without owned service."""
        mock_client = mocker.MagicMock()
        store = AzureTableJobStore(table_client=mock_client, table_name="Jobs")
        assert store._service is None
        store.close()
        mock_client.close.assert_not_called()

    def test_get_table_client_failure_closes_service(self, mocker: MockerFixture) -> None:
        """Close the service when get_table_client raises during store construction."""
        mock_svc_cls = mocker.patch("src.core.storage.azure_table_store.TableServiceClient")
        mock_service = mocker.MagicMock()
        mock_service.get_table_client.side_effect = RuntimeError("client failure")
        mock_svc_cls.return_value = mock_service

        with pytest.raises(RuntimeError, match="client failure"):
            AzureTableJobStore(
                endpoint="https://acct.table.core.windows.net",
                credential=mocker.MagicMock(),
            )
        mock_service.close.assert_called_once()

    def test_create_calls_create_entity_with_partition_and_row_key(
        self, job_store: AzureTableJobStore, mock_table_client
    ) -> None:
        """Persist a job entity with PartitionKey 'staf' and RowKey equal to job id."""
        job = Job(workspace_id="WS-A", test_group="DatabaseHighAvailability")
        result = job_store.create(job)
        assert mock_table_client.create_entity.call_count == 2
        entity = mock_table_client.create_entity.call_args_list[1].args[0]
        assert entity["PartitionKey"] == "staf"
        assert entity["RowKey"] == str(job.id)
        assert result is job

    def test_create_duplicate_propagates_unwrapped(
        self, job_store: AzureTableJobStore, mock_table_client
    ) -> None:
        """Propagate ResourceExistsError without wrapping when creating a duplicate job."""
        job = Job(workspace_id="WS-A")
        job.start()
        job.complete({})
        mock_table_client.create_entity.side_effect = ResourceExistsError("duplicate")
        with pytest.raises(ResourceExistsError):
            job_store.create(job)

    def test_get_returns_none_when_missing(
        self, job_store: AzureTableJobStore, mock_table_client
    ) -> None:
        """Return None when the requested job entity does not exist in the table."""
        mock_table_client.get_entity.side_effect = ResourceNotFoundError("missing")
        assert job_store.get(uuid4()) is None

    def test_get_roundtrips_full_job(
        self, job_store: AzureTableJobStore, mock_table_client
    ) -> None:
        """Round-trip a fully populated job through entity serialization and deserialization."""
        job = Job(
            workspace_id="WS-A",
            test_group="DatabaseHighAvailability",
            test_ids=["ha-config", "azure-lb"],
            metadata={"foo": "bar", "n": 3},
            actor="mcp-agent",
            approval_ref="CHG-42",
            incident_ticket="INC-42",
            offline=True,
        )
        job.start()
        job.complete({"passed": 5, "failed": 0})
        entity = job_store._to_entity(job)
        mock_table_client.get_entity.return_value = entity

        restored = job_store.get(job.id)

        assert restored is not None
        assert str(restored.id) == str(job.id)
        assert restored.workspace_id == "WS-A"
        assert restored.test_group == "DatabaseHighAvailability"
        assert restored.test_ids == ["ha-config", "azure-lb"]
        assert restored.metadata == {"foo": "bar", "n": 3}
        assert restored.actor == "mcp-agent"
        assert restored.approval_ref == "CHG-42"
        assert restored.incident_ticket == "INC-42"
        assert restored.offline is True
        assert restored.status == JobStatus.COMPLETED.value
        assert restored.result == {"passed": 5, "failed": 0}
        assert restored.started_at is not None
        assert restored.completed_at is not None
        assert len(restored.events) == 2

    def test_optional_datetimes_roundtrip_as_none(
        self, job_store: AzureTableJobStore, mock_table_client
    ) -> None:
        """Preserve None for started_at and completed_at through entity round-trip."""
        job = Job(workspace_id="WS-A")
        entity = job_store._to_entity(job)
        mock_table_client.get_entity.return_value = entity
        restored = job_store.get(job.id)
        assert restored is not None
        assert restored.started_at is None
        assert restored.completed_at is None

    def test_empty_result_and_error_roundtrip_without_becoming_none(
        self, job_store: AzureTableJobStore
    ) -> None:
        """Preserve empty dict result and empty string error through entity round-trip."""
        completed = Job(workspace_id="WS-A")
        completed.start()
        completed.complete({})
        failed = Job(workspace_id="WS-B")
        failed.start()
        failed.fail("")

        restored_completed = job_store._to_job(job_store._to_entity(completed))
        restored_failed = job_store._to_job(job_store._to_entity(failed))

        assert restored_completed.result == {}
        assert restored_failed.error == ""

    def test_all_statuses_roundtrip(
        self, job_store: AzureTableJobStore, mocker: MockerFixture
    ) -> None:
        """Serialize and deserialize every JobStatus enum value through entity conversion."""
        for status in JobStatus:
            job = Job(workspace_id="WS-A")
            job.status = status
            entity = job_store._to_entity(job)
            assert entity["status"] == status.value
            restored = job_store._to_job(entity)
            assert restored.status == status.value

    def test_get_malformed_entity_missing_required_field_raises(
        self, job_store: AzureTableJobStore, mock_table_client
    ) -> None:
        """Raise ValueError when a retrieved entity is missing the required workspace_id field."""
        entity = {"RowKey": str(uuid4()), "status": "pending"}
        mock_table_client.get_entity.return_value = entity
        with pytest.raises(ValueError, match="workspace_id"):
            job_store.get(entity["RowKey"])

    def test_get_malformed_entity_invalid_json_raises(
        self, job_store: AzureTableJobStore, mock_table_client
    ) -> None:
        """Raise ValueError when the metadata field contains invalid JSON."""
        job = Job(workspace_id="WS-A")
        entity = job_store._to_entity(job)
        entity["metadata"] = "{not-json"
        mock_table_client.get_entity.return_value = entity
        with pytest.raises(ValueError, match="Malformed job entity"):
            job_store.get(job.id)

    def test_update_missing_job_is_noop(
        self, job_store: AzureTableJobStore, mock_table_client
    ) -> None:
        """Skip update_entity call when the job does not exist in the table."""
        mock_table_client.get_entity.side_effect = ResourceNotFoundError("missing")
        job_store.update(Job(workspace_id="WS-A"))
        mock_table_client.update_entity.assert_not_called()

    def test_update_existing_uses_etag_optimistic_concurrency(
        self, job_store: AzureTableJobStore, mock_table_client
    ) -> None:
        """Send the stored etag with IfNotModified match condition on update."""
        job = Job(workspace_id="WS-A")
        job._storage_etag = 'W/"etag-123"'
        job.start()
        job_store.update(job)
        mock_table_client.update_entity.assert_called_once()
        _, kwargs = mock_table_client.update_entity.call_args
        assert kwargs["etag"] == 'W/"etag-123"'
        assert kwargs["match_condition"].name == "IfNotModified"

    def test_job_update_uses_returned_etag(
        self, job_store: AzureTableJobStore, mock_table_client
    ) -> None:
        """Retain the SDK metadata ETag for subsequent updates."""
        job = Job(workspace_id="WS-A")
        job._storage_etag = 'W/"etag-1"'
        mock_table_client.update_entity.return_value = {"etag": 'W/"etag-2"'}
        job_store.update(job)
        job_store.update(job)

        assert job._storage_etag == 'W/"etag-2"'
        assert mock_table_client.update_entity.call_args_list[1].kwargs["etag"] == 'W/"etag-2"'
        assert "raw_response_hook" not in mock_table_client.update_entity.call_args.kwargs

    def test_update_conflict_raises_concurrency_error(
        self, job_store: AzureTableJobStore, mock_table_client
    ) -> None:
        """Wrap a 412 Precondition Failed response into ConcurrencyConflictError."""
        job = Job(workspace_id="WS-A")
        job._storage_etag = 'W/"etag-1"'
        conflict = HttpResponseError(message="Precondition Failed")
        conflict.status_code = 412
        mock_table_client.update_entity.side_effect = conflict
        with pytest.raises(ConcurrencyConflictError):
            job_store.update(job)

    def test_update_non_conflict_http_error_propagates(
        self, job_store: AzureTableJobStore, mock_table_client
    ) -> None:
        """Propagate non-412 HttpResponseError without wrapping into ConcurrencyConflictError."""
        job = Job(workspace_id="WS-A")
        job._storage_etag = 'W/"etag-1"'
        server_error = HttpResponseError(message="Server error")
        server_error.status_code = 500
        mock_table_client.update_entity.side_effect = server_error
        with pytest.raises(HttpResponseError):
            job_store.update(job)

    def test_update_without_etag_raises_concurrency_error_when_entity_exists(
        self, job_store: AzureTableJobStore, mock_table_client
    ) -> None:
        """Raise ConcurrencyConflictError when updating without etag while entity exists."""
        job = Job(workspace_id="WS-A")
        mock_table_client.get_entity.return_value = {"PartitionKey": "staf", "RowKey": str(job.id)}
        with pytest.raises(ConcurrencyConflictError, match="no expected storage version"):
            job_store.update(job)

    def test_get_active_filters_terminal_statuses(
        self, job_store: AzureTableJobStore, mock_table_client
    ) -> None:
        """Return only non-terminal jobs when filtering active jobs for a workspace."""
        running = Job(workspace_id="WS-A")
        running.start()
        completed = Job(workspace_id="WS-A")
        completed.start()
        completed.complete({})
        mock_table_client.query_entities.return_value = [
            job_store._to_entity(running),
            job_store._to_entity(completed),
        ]
        active = job_store.get_active(workspace_id="WS-A")
        assert len(active) == 1
        assert str(active[0].id) == str(running.id)

    def test_get_active_passes_workspace_filter_to_query(
        self, job_store: AzureTableJobStore, mock_table_client
    ) -> None:
        """Include the workspace_id parameter in the OData filter query for active jobs."""
        mock_table_client.query_entities.return_value = []
        job_store.get_active(workspace_id="WS-A")
        args, kwargs = mock_table_client.query_entities.call_args
        assert "workspace_id eq @ws" in args[0]
        assert kwargs["parameters"]["ws"] == "WS-A"

    def test_get_active_for_workspace_and_has_active_job(
        self, job_store: AzureTableJobStore, mock_table_client
    ) -> None:
        """Return None and False when no active job exists, then a job and True when one does."""
        mock_table_client.query_entities.return_value = []
        assert job_store.get_active_for_workspace("WS-A") is None
        assert job_store.has_active_job("WS-A") is False

        running = Job(workspace_id="WS-A")
        running.start()
        mock_table_client.query_entities.return_value = [job_store._to_entity(running)]
        assert job_store.get_active_for_workspace("WS-A") is not None
        assert job_store.has_active_job("WS-A") is True

    def test_get_history_filters_sorts_and_limits(
        self, job_store: AzureTableJobStore, mock_table_client
    ) -> None:
        """Sort history results by created_at descending and respect the limit parameter."""
        entities = []
        for i in range(5):
            job = Job(workspace_id="WS-A")
            job.start()
            job.complete({})
            job.created_at = datetime.now(timezone.utc) - timedelta(hours=i)
            entities.append(job_store._to_entity(job))
        mock_table_client.query_entities.return_value = entities
        result = job_store.get_history(JobHistoryQuery(workspace_id="WS-A", limit=3))
        assert len(result) == 3
        assert result[0].created_at >= result[1].created_at >= result[2].created_at

    def test_get_history_excludes_jobs_outside_window(
        self, job_store: AzureTableJobStore, mock_table_client
    ) -> None:
        """Pass a cutoff parameter to the query when filtering history by days."""
        job_store.get_history(JobHistoryQuery(days=3))
        _, kwargs = mock_table_client.query_entities.call_args
        assert "cutoff" in kwargs["parameters"]

    def test_get_history_status_filter(
        self, job_store: AzureTableJobStore, mock_table_client
    ) -> None:
        """Filter history results to only return jobs with the requested status."""
        failed = Job(workspace_id="WS-A")
        failed.start()
        failed.fail("boom")
        completed = Job(workspace_id="WS-A")
        completed.start()
        completed.complete({})
        mock_table_client.query_entities.return_value = [
            job_store._to_entity(failed),
            job_store._to_entity(completed),
        ]
        result = job_store.get_history(JobHistoryQuery(status=JobStatus.FAILED))
        assert len(result) == 1
        assert result[0].status == JobStatus.FAILED.value

    def test_get_jobs_for_schedule_delegates_to_history(
        self, job_store: AzureTableJobStore, mock_table_client
    ) -> None:
        """Query job history filtered by schedule_id and return matching jobs."""
        job = Job(workspace_id="WS-A", schedule_id="SCH-1")
        job.start()
        job.complete({})
        mock_table_client.query_entities.return_value = [job_store._to_entity(job)]
        result = job_store.get_jobs_for_schedule("SCH-1", limit=10)
        assert len(result) == 1
        assert result[0].schedule_id == "SCH-1"
        _, kwargs = mock_table_client.query_entities.call_args
        assert kwargs["parameters"]["sid"] == "SCH-1"

    def test_close_is_idempotent(self, job_store: AzureTableJobStore, mock_table_client) -> None:
        """Allow multiple close calls without closing the injected table client."""
        job_store.close()
        job_store.close()
        mock_table_client.close.assert_not_called()

    def test_create_rejects_oversized_events(
        self, job_store: AzureTableJobStore, mock_table_client
    ) -> None:
        """Reject job creation when the serialized events field exceeds the property size limit."""
        job = Job(
            workspace_id="WS-A",
            events=[
                JobEvent(
                    event_type=JobEventType.CREATED,
                    message="oversized",
                    data={"payload": "e" * (65 * 1024)},
                )
            ],
        )
        with pytest.raises(EntityTooLargeError, match="events"):
            job_store.create(job)
        mock_table_client.create_entity.assert_not_called()

    def test_create_rejects_oversized_result(
        self, job_store: AzureTableJobStore, mock_table_client
    ) -> None:
        """Reject job creation when the serialized result field exceeds the property size limit."""
        job = Job(workspace_id="WS-A")
        job.start()
        job.complete({"payload": "r" * (65 * 1024)})
        with pytest.raises(EntityTooLargeError, match="result"):
            job_store.create(job)
        mock_table_client.create_entity.assert_not_called()

    def test_create_rejects_oversized_metadata(
        self, job_store: AzureTableJobStore, mock_table_client
    ) -> None:
        """Reject job creation when the serialized metadata field exceeds the property size limit."""
        job = Job(workspace_id="WS-A")
        job.metadata["blob"] = "m" * (65 * 1024)
        with pytest.raises(EntityTooLargeError, match="metadata"):
            job_store.create(job)
        mock_table_client.create_entity.assert_not_called()

    def test_update_rejects_oversized_entity_before_writing(
        self, job_store: AzureTableJobStore, mock_table_client
    ) -> None:
        """Reject an oversized entity during update before any write is attempted."""
        job = Job(workspace_id="WS-A")
        job._storage_etag = 'W/"etag-1"'
        job.metadata["blob"] = "m" * (65 * 1024)
        with pytest.raises(EntityTooLargeError):
            job_store.update(job)
        mock_table_client.update_entity.assert_not_called()

    def test_create_succeeds_for_boundary_safe_normal_entity(
        self, job_store: AzureTableJobStore, mock_table_client
    ) -> None:
        """Successfully create a job entity that is within Azure Table size limits."""
        job = Job(workspace_id="WS-A", test_group="DatabaseHighAvailability")
        job.start()
        job.complete({"ok": True, "details": "n" * 1024})
        result = job_store.create(job)
        mock_table_client.create_entity.assert_called_once()
        assert result is job

    def test_schedule_requires_endpoint_or_table_client(self) -> None:
        """Raise ValueError when neither endpoint nor table_client is supplied for schedules."""
        with pytest.raises(ValueError, match="endpoint is required"):
            AzureTableScheduleStore()

    def test_schedule_requires_credential_when_endpoint_given(self) -> None:
        """Raise ValueError when endpoint is provided without credential for schedule store."""
        with pytest.raises(ValueError, match="credential is required"):
            AzureTableScheduleStore(endpoint="https://acct.table.core.windows.net")

    def test_constructs_from_endpoint_with_custom_table_name(self, mocker: MockerFixture) -> None:
        """Construct a schedule store with a custom table name from endpoint and credential."""
        mock_svc_cls = mocker.patch("src.core.storage.azure_table_store.TableServiceClient")
        mock_svc = mocker.MagicMock()
        mock_client = mocker.MagicMock()
        mock_svc.get_table_client.return_value = mock_client
        mock_svc_cls.return_value = mock_svc
        mock_cred = mocker.MagicMock()

        store = AzureTableScheduleStore(
            endpoint="https://acct.table.core.windows.net",
            table_name="CustomSchedules",
            credential=mock_cred,
        )
        mock_svc.create_table_if_not_exists.assert_called_once_with("CustomSchedules")
        mock_svc.get_table_client.assert_called_once_with("CustomSchedules")
        assert store.table_name == "CustomSchedules"

    def test_schedule_close_closes_owned_service_exactly_once(self, mocker: MockerFixture) -> None:
        """Close the owned schedule service exactly once on repeated close calls."""
        mock_svc_cls = mocker.patch("src.core.storage.azure_table_store.TableServiceClient")
        mock_svc = mocker.MagicMock()
        mock_client = mocker.MagicMock()
        mock_svc.get_table_client.return_value = mock_client
        mock_svc_cls.return_value = mock_svc
        mock_cred = mocker.MagicMock()

        store = AzureTableScheduleStore(
            endpoint="https://acct.table.core.windows.net", credential=mock_cred
        )
        store.close()
        store.close()
        mock_svc.close.assert_called_once()
        mock_cred.close.assert_not_called()

    def test_schedule_injected_client_close_does_not_own_service(
        self, mocker: MockerFixture
    ) -> None:
        """Skip service close when an injected client is used for the schedule store."""
        mock_client = mocker.MagicMock()
        store = AzureTableScheduleStore(table_client=mock_client, table_name="Schedules")
        assert store._service is None
        store.close()
        mock_client.close.assert_not_called()

    def test_create_calls_create_entity(
        self, schedule_store: AzureTableScheduleStore, mock_table_client
    ) -> None:
        """Persist a schedule entity with PartitionKey 'staf' and RowKey equal to schedule id."""
        schedule = Schedule(name="daily", cron_expression="0 0 * * *", workspace_ids=["WS-A"])
        result = schedule_store.create(schedule)
        mock_table_client.create_entity.assert_called_once()
        entity = mock_table_client.create_entity.call_args[0][0]
        assert entity["PartitionKey"] == "staf"
        assert entity["RowKey"] == schedule.id
        assert result is schedule

    def test_create_duplicate_raises_value_error(
        self, schedule_store: AzureTableScheduleStore, mock_table_client
    ) -> None:
        """Wrap ResourceExistsError into ValueError when creating a duplicate schedule."""
        mock_table_client.create_entity.side_effect = ResourceExistsError("duplicate")
        with pytest.raises(ValueError, match="already exists"):
            schedule_store.create(Schedule(name="daily", cron_expression="0 0 * * *"))

    def test_schedule_get_returns_none_when_missing(
        self, schedule_store: AzureTableScheduleStore, mock_table_client
    ) -> None:
        """Return None when the requested schedule entity does not exist."""
        mock_table_client.get_entity.side_effect = ResourceNotFoundError("missing")
        assert schedule_store.get("missing-id") is None

    def test_get_roundtrips_full_schedule(
        self, schedule_store: AzureTableScheduleStore, mock_table_client
    ) -> None:
        """Round-trip a fully populated schedule through entity serialization and deserialization."""
        now = datetime.now(timezone.utc)
        schedule = Schedule(
            name="nightly",
            description="desc",
            cron_expression="0 2 * * *",
            workspace_ids=["WS-A", "WS-B"],
            test_group="ConfigurationChecks",
            test_ids=["c1", "c2"],
            enabled=True,
            next_run_time=now,
            last_run_time=now,
            last_run_job_ids=["J1", "J2"],
            total_runs=7,
        )
        entity = schedule_store._to_entity(schedule)
        mock_table_client.get_entity.return_value = entity
        restored = schedule_store.get(schedule.id)

        assert restored is not None
        assert restored.id == schedule.id
        assert restored.name == "nightly"
        assert restored.cron_expression == "0 2 * * *"
        assert restored.workspace_ids == ["WS-A", "WS-B"]
        assert restored.test_group == "ConfigurationChecks"
        assert restored.test_ids == ["c1", "c2"]
        assert restored.enabled is True
        assert restored.next_run_time is not None
        assert restored.last_run_time is not None
        assert restored.last_run_job_ids == ["J1", "J2"]
        assert restored.total_runs == 7

    def test_schedule_get_malformed_entity_missing_required_field_raises(
        self, schedule_store: AzureTableScheduleStore, mock_table_client
    ) -> None:
        """Raise ValueError when a retrieved schedule entity is missing cron_expression."""
        entity = {"RowKey": "SCH-1", "name": "x"}
        mock_table_client.get_entity.return_value = entity
        with pytest.raises(ValueError, match="cron_expression"):
            schedule_store.get("SCH-1")

    def test_schedule_get_malformed_entity_invalid_json_raises(
        self, schedule_store: AzureTableScheduleStore, mock_table_client
    ) -> None:
        """Raise ValueError when workspace_ids contains invalid JSON in the schedule entity."""
        schedule = Schedule(name="x", cron_expression="* * * * *")
        entity = schedule_store._to_entity(schedule)
        entity["workspace_ids"] = "[not-json"
        mock_table_client.get_entity.return_value = entity
        with pytest.raises(ValueError, match="Malformed schedule entity"):
            schedule_store.get(schedule.id)

    def test_list_all(self, schedule_store: AzureTableScheduleStore, mock_table_client) -> None:
        """Return all schedules regardless of enabled status when listing without filter."""
        enabled = Schedule(name="a", cron_expression="* * * * *", enabled=True)
        disabled = Schedule(name="b", cron_expression="* * * * *", enabled=False)
        mock_table_client.query_entities.return_value = [
            schedule_store._to_entity(enabled),
            schedule_store._to_entity(disabled),
        ]
        assert len(schedule_store.list()) == 2

    def test_list_enabled_only_filters(
        self, schedule_store: AzureTableScheduleStore, mock_table_client
    ) -> None:
        """Include 'enabled eq true' in the OData filter when listing enabled-only schedules."""
        enabled = Schedule(name="a", cron_expression="* * * * *", enabled=True)
        mock_table_client.query_entities.return_value = [schedule_store._to_entity(enabled)]
        result = schedule_store.list(enabled_only=True)
        assert len(result) == 1
        args, _ = mock_table_client.query_entities.call_args
        assert "enabled eq true" in args[0]

    def test_get_enabled_delegates_to_list(
        self, schedule_store: AzureTableScheduleStore, mock_table_client
    ) -> None:
        """Delegate get_enabled to list with enabled_only filter applied."""
        mock_table_client.query_entities.return_value = []
        assert schedule_store.get_enabled() == []
        args, _ = mock_table_client.query_entities.call_args
        assert "enabled eq true" in args[0]

    def test_update_missing_raises_value_error(
        self, schedule_store: AzureTableScheduleStore, mock_table_client
    ) -> None:
        """Raise ValueError when updating a schedule that does not exist in the table."""
        mock_table_client.get_entity.side_effect = ResourceNotFoundError("missing")
        with pytest.raises(ValueError, match="not found"):
            schedule_store.update(Schedule(name="x", cron_expression="* * * * *"))
        mock_table_client.update_entity.assert_not_called()

    def test_update_existing_uses_etag_and_bumps_updated_at(
        self, schedule_store: AzureTableScheduleStore, mock_table_client
    ) -> None:
        """Use stored etag with IfNotModified condition and advance updated_at on schedule update."""
        schedule = Schedule(name="x", cron_expression="* * * * *")
        schedule.updated_at = datetime.now(timezone.utc) - timedelta(hours=1)
        original_updated_at = schedule.updated_at
        schedule._storage_etag = 'W/"sched-etag"'
        updated = schedule_store.update(schedule)
        mock_table_client.update_entity.assert_called_once()
        _, kwargs = mock_table_client.update_entity.call_args
        assert kwargs["etag"] == 'W/"sched-etag"'
        assert kwargs["match_condition"].name == "IfNotModified"
        assert updated.updated_at > original_updated_at
        entity = mock_table_client.update_entity.call_args.args[0]
        assert entity["updated_at"] == updated.updated_at.isoformat()

    def test_schedule_update_uses_returned_etag(
        self, schedule_store: AzureTableScheduleStore, mock_table_client
    ) -> None:
        """Retain the SDK metadata ETag for subsequent updates."""
        schedule = Schedule(name="x", cron_expression="* * * * *")
        schedule._storage_etag = 'W/"etag-1"'
        mock_table_client.update_entity.return_value = {"etag": 'W/"etag-2"'}
        schedule_store.update(schedule)
        schedule_store.update(schedule)

        assert schedule._storage_etag == 'W/"etag-2"'
        assert mock_table_client.update_entity.call_args_list[1].kwargs["etag"] == 'W/"etag-2"'
        assert "raw_response_hook" not in mock_table_client.update_entity.call_args.kwargs

    def test_schedule_update_conflict_raises_concurrency_error(
        self, schedule_store: AzureTableScheduleStore, mock_table_client
    ) -> None:
        """Wrap a 412 Precondition Failed response into ConcurrencyConflictError for schedules."""
        schedule = Schedule(name="x", cron_expression="* * * * *")
        schedule._storage_etag = 'W/"etag-1"'
        conflict = HttpResponseError(message="Precondition Failed")
        conflict.status_code = 412
        mock_table_client.update_entity.side_effect = conflict
        with pytest.raises(ConcurrencyConflictError):
            schedule_store.update(schedule)

    def test_schedule_update_without_etag_raises_concurrency_error_when_entity_exists(
        self, schedule_store: AzureTableScheduleStore, mock_table_client
    ) -> None:
        """Raise ConcurrencyConflictError when updating schedule without etag while it exists."""
        schedule = Schedule(name="x", cron_expression="* * * * *")
        mock_table_client.get_entity.return_value = {"PartitionKey": "staf", "RowKey": schedule.id}
        with pytest.raises(ConcurrencyConflictError, match="no expected storage version"):
            schedule_store.update(schedule)

    def test_delete_existing_returns_true(
        self, schedule_store: AzureTableScheduleStore, mock_table_client
    ) -> None:
        """Return True when deleting an existing schedule entity from the table."""
        assert schedule_store.delete("SCH-1") is True
        mock_table_client.delete_entity.assert_called_once_with("staf", "SCH-1")

    def test_delete_missing_returns_false(
        self, schedule_store: AzureTableScheduleStore, mock_table_client
    ) -> None:
        """Return False when deleting a schedule that does not exist in the table."""
        mock_table_client.delete_entity.side_effect = ResourceNotFoundError("missing")
        assert schedule_store.delete("missing") is False

    def test_schedule_close_is_idempotent(
        self, schedule_store: AzureTableScheduleStore, mock_table_client
    ) -> None:
        """Allow multiple close calls on schedule store without closing the injected client."""
        schedule_store.close()
        schedule_store.close()
        mock_table_client.close.assert_not_called()

    def test_create_rejects_oversized_description(
        self, schedule_store: AzureTableScheduleStore, mock_table_client
    ) -> None:
        """Reject schedule creation when the description field exceeds the property size limit."""
        schedule = Schedule(
            name="daily",
            cron_expression="0 0 * * *",
            workspace_ids=["WS-A"],
            description="d" * (65 * 1024),
        )
        with pytest.raises(EntityTooLargeError, match="description"):
            schedule_store.create(schedule)
        mock_table_client.create_entity.assert_not_called()

    def test_create_rejects_oversized_test_ids(
        self, schedule_store: AzureTableScheduleStore, mock_table_client
    ) -> None:
        """Reject schedule creation when the serialized test_ids field exceeds the size limit."""
        schedule = Schedule(
            name="daily",
            cron_expression="0 0 * * *",
            workspace_ids=["WS-A"],
            test_ids=[f"test-{i:06d}" for i in range(10_000)],
        )
        with pytest.raises(EntityTooLargeError, match="test_ids"):
            schedule_store.create(schedule)
        mock_table_client.create_entity.assert_not_called()

    def test_schedule_update_rejects_oversized_entity_before_writing(
        self, schedule_store: AzureTableScheduleStore, mock_table_client, mocker: MockerFixture
    ) -> None:
        """Reject an oversized schedule entity during update before any write is attempted."""
        schedule = Schedule(name="daily", cron_expression="0 0 * * *", workspace_ids=["WS-A"])
        schedule._storage_etag = 'W/"etag-1"'
        schedule.description = "d" * (65 * 1024)
        with pytest.raises(EntityTooLargeError):
            schedule_store.update(schedule)
        mock_table_client.update_entity.assert_not_called()

    def test_schedule_create_succeeds_for_boundary_safe_normal_entity(
        self, schedule_store: AzureTableScheduleStore, mock_table_client
    ) -> None:
        """Successfully create a schedule entity that is within Azure Table size limits."""
        schedule = Schedule(
            name="daily",
            cron_expression="0 0 * * *",
            workspace_ids=["WS-A", "WS-B"],
            description="Runs the nightly regression suite" * 10,
        )
        result = schedule_store.create(schedule)
        mock_table_client.create_entity.assert_called_once()
        assert result is schedule

    def test_service_closed_on_create_table_failure(self, mocker: MockerFixture) -> None:
        """Close the TableServiceClient when create_table_if_not_exists raises during init."""
        mock_svc_cls = mocker.patch("src.core.storage.azure_table_store.TableServiceClient")
        mock_svc = mocker.MagicMock()
        mock_svc.create_table_if_not_exists.side_effect = HttpResponseError(message="403 Forbidden")
        mock_svc_cls.return_value = mock_svc
        mock_cred = mocker.MagicMock()

        from src.core.storage.azure_table_store import _new_table_resources

        with pytest.raises(HttpResponseError, match="403 Forbidden"):
            _new_table_resources(
                endpoint="https://acct.table.core.windows.net",
                table_name="TestTable",
                credential=mock_cred,
            )
        mock_svc.close.assert_called_once()

    def test_credential_not_closed_on_create_table_failure(self, mocker: MockerFixture) -> None:
        """Leave the credential open when table creation fails during _new_table_resources."""
        mock_svc_cls = mocker.patch("src.core.storage.azure_table_store.TableServiceClient")
        mock_svc = mocker.MagicMock()
        mock_svc.create_table_if_not_exists.side_effect = RuntimeError("boom")
        mock_svc_cls.return_value = mock_svc
        mock_cred = mocker.MagicMock()

        from src.core.storage.azure_table_store import _new_table_resources

        with pytest.raises(RuntimeError, match="boom"):
            _new_table_resources(
                endpoint="https://acct.table.core.windows.net",
                table_name="TestTable",
                credential=mock_cred,
            )
        mock_cred.close.assert_not_called()

    def test_active_job_create_acquires_lock_before_entity(
        self, job_store: AzureTableJobStore, mock_table_client
    ) -> None:
        """Acquire a workspace-lock entity before creating the job entity for active jobs."""
        job = Job(workspace_id="WS-LOCK")
        job_store.create(job)
        assert mock_table_client.create_entity.call_count == 2
        lock = mock_table_client.create_entity.call_args_list[0].kwargs["entity"]
        assert isinstance(lock, TableEntity)
        assert lock["PartitionKey"] == "workspace-lock"
        assert lock["RowKey"] == "WS-LOCK"
        assert lock["job_id"] == str(job.id)

    def test_terminal_job_create_skips_lock(
        self, job_store: AzureTableJobStore, mock_table_client
    ) -> None:
        """Skip workspace-lock acquisition when the job is already in a terminal status."""
        job = Job(workspace_id="WS-TERM")
        job.start()
        job.complete({})
        job_store.create(job)
        assert mock_table_client.create_entity.call_count == 1

    def test_failed_entity_create_rolls_back_lock(
        self, job_store: AzureTableJobStore, mock_table_client
    ) -> None:
        """Delete the workspace-lock entity when the job entity creation fails."""
        job = Job(workspace_id="WS-ROLLBACK")
        mock_table_client.create_entity.side_effect = [
            None,
            RuntimeError("entity write failed"),
        ]
        mock_table_client.get_entity.return_value = _entity_with_etag(
            {
                "PartitionKey": "workspace-lock",
                "RowKey": "WS-ROLLBACK",
                "job_id": str(job.id),
            },
            mock_factory=mock_table_client,
        )
        with pytest.raises(RuntimeError, match="entity write failed"):
            job_store.create(job)
        mock_table_client.delete_entity.assert_called_once_with(
            partition_key="workspace-lock",
            row_key="WS-ROLLBACK",
            etag='W/"etag-1"',
            match_condition=MatchConditions.IfNotModified,
        )

    def test_terminal_update_releases_lock(
        self, job_store: AzureTableJobStore, mock_table_client
    ) -> None:
        """Release the workspace-lock entity when a job transitions to a terminal status."""
        job = Job(workspace_id="WS-DONE")
        job._storage_etag = 'W/"etag-1"'
        job.start()
        job.complete({})
        mock_table_client.get_entity.return_value = _entity_with_etag(
            {
                "PartitionKey": "workspace-lock",
                "RowKey": "WS-DONE",
                "job_id": str(job.id),
            },
            mock_factory=mock_table_client,
        )
        job_store.update(job)
        mock_table_client.delete_entity.assert_called_once_with(
            partition_key="workspace-lock",
            row_key="WS-DONE",
            etag='W/"etag-1"',
            match_condition=MatchConditions.IfNotModified,
        )

    def test_release_lock_ignores_missing_lock(
        self, job_store: AzureTableJobStore, mock_table_client
    ) -> None:
        """Silently skip lock release when no workspace-lock entity exists."""
        job = Job(workspace_id="WS-NOLCK")
        job._storage_etag = 'W/"etag-1"'
        job.start()
        job.complete({})
        mock_table_client.get_entity.side_effect = ResourceNotFoundError("no lock")
        job_store.update(job)

    def test_release_lock_skips_lock_owned_by_different_job(
        self, job_store: AzureTableJobStore, mock_table_client
    ) -> None:
        """Do not delete a workspace-lock entity owned by a different job id."""
        job = Job(workspace_id="WS-OTHER")
        job._storage_etag = 'W/"etag-1"'
        job.start()
        job.complete({})
        mock_table_client.get_entity.return_value = {
            "PartitionKey": "workspace-lock",
            "RowKey": "WS-OTHER",
            "job_id": str(uuid4()),
        }
        job_store.update(job)
        mock_table_client.delete_entity.assert_not_called()

    def test_create_reclaims_lock_for_missing_job(
        self, job_store: AzureTableJobStore, mock_table_client, mocker: MockerFixture
    ) -> None:
        """Reclaim a stale lock when its referenced job no longer exists."""
        job = Job(workspace_id="WS-STALE")
        stale_lock = _entity_with_etag(
            {
                "PartitionKey": "workspace-lock",
                "RowKey": job.workspace_id,
                "job_id": str(uuid4()),
            },
            mock_factory=mocker.MagicMock,
        )
        mock_table_client.create_entity.side_effect = [
            ResourceExistsError("locked"),
            None,
            None,
        ]
        mock_table_client.get_entity.side_effect = [
            stale_lock,
            ResourceNotFoundError("job missing"),
        ]

        job_store.create(job)

        mock_table_client.delete_entity.assert_called_once_with(
            partition_key="workspace-lock",
            row_key=job.workspace_id,
            etag='W/"etag-1"',
            match_condition=MatchConditions.IfNotModified,
        )

    def test_create_preserves_lock_for_active_job(
        self, job_store: AzureTableJobStore, mock_table_client, mocker: MockerFixture
    ) -> None:
        """Reject lock reclamation while the referenced job remains active."""
        job = Job(workspace_id="WS-ACTIVE")
        existing_job = Job(workspace_id=job.workspace_id)
        stale_lock = _entity_with_etag(
            {
                "PartitionKey": "workspace-lock",
                "RowKey": job.workspace_id,
                "job_id": str(existing_job.id),
            },
            mock_factory=mocker.MagicMock,
        )
        existing_entity = _entity_with_etag(
            job_store._to_entity(existing_job),
            mock_factory=mocker.MagicMock,
        )
        mock_table_client.create_entity.side_effect = ResourceExistsError("locked")
        mock_table_client.get_entity.side_effect = [stale_lock, existing_entity]

        with pytest.raises(ResourceExistsError, match="locked"):
            job_store.create(job)

        mock_table_client.delete_entity.assert_not_called()
