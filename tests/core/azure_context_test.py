# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for Azure storage context lifecycle and ownership."""

from types import SimpleNamespace
import pytest
from fastapi import FastAPI
from pytest_mock import MockerFixture
import src.api.app as app_module
from src.core.storage.azure_context import AzureStorageContext, create_azure_storage_context
from src.core.storage.azure_table_store import AzureTableJobStore, AzureTableScheduleStore
from src.core.storage.factory import create_storage_context


class TestAzureContext:
    """Tests for AzureStorageContext lifecycle and resource ownership."""

    def test_returns_none_when_no_endpoints(self) -> None:
        assert create_azure_storage_context(env={}) is None

    def test_returns_none_for_blank_endpoints(self) -> None:
        assert (
            create_azure_storage_context(
                env={"AZURE_TABLE_ENDPOINT": "  ", "AZURE_BLOB_ENDPOINT": ""}
            )
            is None
        )

    def test_owned_identity_closed_exactly_once(self, mocker: MockerFixture) -> None:
        mock_table_cls = mocker.patch("src.core.storage.azure_context.TableServiceClient")
        mock_blob_cls = mocker.patch("src.core.storage.azure_context.BlobServiceClient")
        provider = mocker.MagicMock()
        provider.get_credential.return_value = mocker.MagicMock()
        table_service = mocker.MagicMock()
        blob_service = mocker.MagicMock()
        mock_table_cls.return_value = table_service
        mock_blob_cls.return_value = blob_service

        context = create_azure_storage_context(
            env={
                "AZURE_TABLE_ENDPOINT": "https://acct.table.core.windows.net",
                "AZURE_BLOB_ENDPOINT": "https://acct.blob.core.windows.net",
            },
            identity_provider=None,
        )

        assert context is not None
        context.close()
        context.close()

        table_service.close.assert_called_once()
        blob_service.close.assert_called_once()
        assert mock_table_cls.call_count == 1
        assert mock_blob_cls.call_count == 1

    def test_external_identity_not_closed_by_context(self, mocker: MockerFixture) -> None:
        mock_provider_cls = mocker.patch("src.core.storage.azure_context.DefaultIdentityProvider")
        external_provider = mocker.MagicMock()
        external_provider.get_credential.return_value = mocker.MagicMock()
        context = AzureStorageContext(identity_provider=external_provider, owns_identity=False)
        context.close()
        external_provider.close.assert_not_called()
        mock_provider_cls.assert_not_called()

    def test_partial_initialization_failure_closes_owned_resources(
        self, mocker: MockerFixture
    ) -> None:
        mock_provider_cls = mocker.patch("src.core.storage.azure_context.DefaultIdentityProvider")
        mock_table_cls = mocker.patch("src.core.storage.azure_context.TableServiceClient")
        mock_blob_cls = mocker.patch("src.core.storage.azure_context.BlobServiceClient")
        provider = mocker.MagicMock()
        provider.get_credential.return_value = mocker.MagicMock()
        mock_provider_cls.return_value = provider
        table_service = mocker.MagicMock()
        mock_table_cls.return_value = table_service
        mock_blob_cls.side_effect = RuntimeError("blob failed")

        with pytest.raises(RuntimeError, match="blob failed"):
            create_azure_storage_context(
                env={
                    "AZURE_TABLE_ENDPOINT": "https://acct.table.core.windows.net",
                    "AZURE_BLOB_ENDPOINT": "https://acct.blob.core.windows.net",
                }
            )

        table_service.close.assert_called_once()
        provider.close.assert_called_once()

    def test_get_table_client_returns_non_owning_child(self, mocker: MockerFixture) -> None:
        mock_table_cls = mocker.patch("src.core.storage.azure_context.TableServiceClient")
        table_service = mocker.MagicMock()
        table_client = mocker.MagicMock()
        table_service.get_table_client.return_value = table_client
        mock_table_cls.return_value = table_service
        provider = mocker.MagicMock()
        provider.get_credential.return_value = mocker.MagicMock()

        context = create_azure_storage_context(
            env={"AZURE_TABLE_ENDPOINT": "https://acct.table.core.windows.net"},
            identity_provider=provider,
        )

        assert context is not None
        client = context.get_table_client("Jobs")
        assert client is table_client
        table_service.create_table_if_not_exists.assert_called_once_with("Jobs")

    def test_get_container_client_returns_non_owning_child(self, mocker: MockerFixture) -> None:
        mock_blob_cls = mocker.patch("src.core.storage.azure_context.BlobServiceClient")
        blob_service = mocker.MagicMock()
        container = mocker.MagicMock()
        blob_service.get_container_client.return_value = container
        mock_blob_cls.return_value = blob_service
        provider = mocker.MagicMock()
        provider.get_credential.return_value = mocker.MagicMock()

        context = create_azure_storage_context(
            env={"AZURE_BLOB_ENDPOINT": "https://acct.blob.core.windows.net"},
            identity_provider=provider,
        )

        assert context is not None
        assert context.get_container_client("workspaces") is container
        blob_service.get_container_client.assert_called_once_with("workspaces")

    def test_create_storage_context_requires_azure_context_for_table_backend(self) -> None:
        with pytest.raises(RuntimeError, match="AzureStorageContext"):
            create_storage_context(
                env={"AZURE_TABLE_ENDPOINT": "https://acct.table.core.windows.net"}
            )

    def test_storage_context_close_does_not_close_injected_azure_context(
        self, mocker: MockerFixture
    ) -> None:
        azure_context = mocker.MagicMock()
        azure_context.has_table = True
        jobs_client = mocker.MagicMock()
        schedules_client = mocker.MagicMock()
        azure_context.get_table_client.side_effect = [jobs_client, schedules_client]

        context = create_storage_context(
            env={"AZURE_TABLE_ENDPOINT": "https://acct.table.core.windows.net"},
            azure_context=azure_context,
        )
        context.close()

        azure_context.close.assert_not_called()
        jobs_client.close.assert_not_called()
        schedules_client.close.assert_not_called()

    def test_injected_table_clients_are_non_owning(self, mocker: MockerFixture) -> None:
        jobs_client = mocker.MagicMock()
        schedules_client = mocker.MagicMock()

        AzureTableJobStore(table_client=jobs_client).close()
        AzureTableScheduleStore(table_client=schedules_client).close()

        jobs_client.close.assert_not_called()
        schedules_client.close.assert_not_called()

    @pytest.mark.asyncio
    async def test_lifespan_closes_azure_context_once(
        self, monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture
    ) -> None:
        import src.api.app as app_module

        azure_context = mocker.MagicMock()
        storage_context = SimpleNamespace(
            backend="sqlite",
            job_store=mocker.MagicMock(),
            schedule_store=mocker.MagicMock(),
            close=mocker.MagicMock(),
        )
        workspace_backend = SimpleNamespace(backend_name="filesystem", close=mocker.MagicMock())

        class FakeWorker:
            def recover_crashed_jobs(self) -> int:
                return 0

            async def shutdown(self) -> None:
                return None

        class FakeScheduler:
            async def start(self) -> None:
                return None

            async def stop(self) -> None:
                return None

        monkeypatch.setattr(app_module, "create_azure_storage_context", lambda: azure_context)
        monkeypatch.setattr(app_module, "create_storage_context", lambda **_: storage_context)
        monkeypatch.setattr(app_module, "create_workspace_backend", lambda **_: workspace_backend)
        monkeypatch.setattr(app_module, "JobWorker", lambda **_: FakeWorker())
        monkeypatch.setattr(app_module, "SchedulerService", lambda **_: FakeScheduler())
        monkeypatch.setattr(app_module, "AnsibleExecutor", lambda **_: mocker.MagicMock())

        async with app_module.lifespan(FastAPI()):
            pass

        storage_context.close.assert_called_once()
        workspace_backend.close.assert_called_once()
        azure_context.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_lifespan_closes_azure_context_after_prior_cleanup_failures(
        self, monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture
    ) -> None:

        azure_context = mocker.MagicMock()
        storage_context = SimpleNamespace(
            backend="sqlite",
            job_store=mocker.MagicMock(),
            schedule_store=mocker.MagicMock(),
            close=mocker.MagicMock(side_effect=RuntimeError("storage close failed")),
        )
        workspace_backend = SimpleNamespace(
            backend_name="filesystem",
            close=mocker.MagicMock(side_effect=RuntimeError("backend close failed")),
        )

        class FakeWorker:
            def recover_crashed_jobs(self) -> int:
                return 0

            async def shutdown(self) -> None:
                raise RuntimeError("worker shutdown failed")

        class FakeScheduler:
            async def start(self) -> None:
                return None

            async def stop(self) -> None:
                raise RuntimeError("scheduler stop failed")

        monkeypatch.setattr(app_module, "create_azure_storage_context", lambda: azure_context)
        monkeypatch.setattr(app_module, "create_storage_context", lambda **_: storage_context)
        monkeypatch.setattr(app_module, "create_workspace_backend", lambda **_: workspace_backend)
        monkeypatch.setattr(app_module, "JobWorker", lambda **_: FakeWorker())
        monkeypatch.setattr(app_module, "SchedulerService", lambda **_: FakeScheduler())
        monkeypatch.setattr(app_module, "AnsibleExecutor", lambda **_: mocker.MagicMock())

        async with app_module.lifespan(FastAPI()):
            pass

        storage_context.close.assert_called_once()
        workspace_backend.close.assert_called_once()
        azure_context.close.assert_called_once()
