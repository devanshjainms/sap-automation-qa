# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for Azure storage context lifecycle and ownership."""

import pytest
from pytest_mock import MockerFixture
from src.core.storage.azure_context import AzureStorageContext, create_azure_storage_context
from src.core.storage.azure_table_store import AzureTableJobStore, AzureTableScheduleStore
from src.core.storage.factory import create_storage_context

_TABLE_ENDPOINT = "https://acct.table.core.windows.net"
_BLOB_ENDPOINT = "https://acct.blob.core.windows.net"


class TestAzureStorageContext:
    """Tests for AzureStorageContext lifecycle and resource ownership."""

    def test_returns_none_when_no_endpoints(self) -> None:
        """Return None when env contains no Azure endpoint variables."""
        assert create_azure_storage_context(env={}) is None

    def test_returns_none_for_blank_endpoints(self) -> None:
        """Return None when both endpoint env vars are blank or whitespace-only."""
        assert (
            create_azure_storage_context(
                env={"AZURE_TABLE_ENDPOINT": "  ", "AZURE_BLOB_ENDPOINT": ""}
            )
            is None
        )

    def test_owned_identity_closed_exactly_once(self, mocker: MockerFixture) -> None:
        """Close table and blob services exactly once on double close with owned identity."""
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
                "AZURE_TABLE_ENDPOINT": _TABLE_ENDPOINT,
                "AZURE_BLOB_ENDPOINT": _BLOB_ENDPOINT,
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
        """Skip closing an externally provided identity provider when owns_identity is False."""
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
        """Close already-created resources when blob service initialization fails."""
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
                    "AZURE_TABLE_ENDPOINT": _TABLE_ENDPOINT,
                    "AZURE_BLOB_ENDPOINT": _BLOB_ENDPOINT,
                }
            )

        table_service.close.assert_called_once()
        provider.close.assert_called_once()

    def test_get_table_client_returns_non_owning_child(self, mocker: MockerFixture) -> None:
        """Return a table client for the given table name and ensure the table is created."""
        mock_table_cls = mocker.patch("src.core.storage.azure_context.TableServiceClient")
        table_service = mocker.MagicMock()
        table_client = mocker.MagicMock()
        table_service.get_table_client.return_value = table_client
        mock_table_cls.return_value = table_service
        provider = mocker.MagicMock()
        provider.get_credential.return_value = mocker.MagicMock()

        context = create_azure_storage_context(
            env={"AZURE_TABLE_ENDPOINT": _TABLE_ENDPOINT},
            identity_provider=provider,
        )

        assert context is not None
        client = context.get_table_client("Jobs")
        assert client is table_client
        table_service.create_table_if_not_exists.assert_called_once_with("Jobs")

    def test_get_container_client_returns_non_owning_child(self, mocker: MockerFixture) -> None:
        """Return a container client for the given container name from the blob service."""
        mock_blob_cls = mocker.patch("src.core.storage.azure_context.BlobServiceClient")
        blob_service = mocker.MagicMock()
        container = mocker.MagicMock()
        blob_service.get_container_client.return_value = container
        mock_blob_cls.return_value = blob_service
        provider = mocker.MagicMock()
        provider.get_credential.return_value = mocker.MagicMock()

        context = create_azure_storage_context(
            env={"AZURE_BLOB_ENDPOINT": _BLOB_ENDPOINT},
            identity_provider=provider,
        )

        assert context is not None
        assert context.get_container_client("workspaces") is container
        blob_service.get_container_client.assert_called_once_with("workspaces")

    def test_has_table_and_has_blob_properties(self, mocker: MockerFixture) -> None:
        """Report has_table and has_blob correctly based on which services are injected."""
        provider = mocker.MagicMock()
        provider.get_credential.return_value = mocker.MagicMock()

        ctx_no_services = AzureStorageContext(identity_provider=provider)
        assert ctx_no_services.has_table is False
        assert ctx_no_services.has_blob is False

        ctx_with_table = AzureStorageContext(
            identity_provider=provider, table_service=mocker.MagicMock()
        )
        assert ctx_with_table.has_table is True
        assert ctx_with_table.has_blob is False

        ctx_with_blob = AzureStorageContext(
            identity_provider=provider, blob_service=mocker.MagicMock()
        )
        assert ctx_with_blob.has_table is False
        assert ctx_with_blob.has_blob is True

    def test_credential_raises_after_close(self, mocker: MockerFixture) -> None:
        """Raise RuntimeError when accessing credential after the context has been closed."""
        provider = mocker.MagicMock()
        provider.get_credential.return_value = mocker.MagicMock()
        context = AzureStorageContext(identity_provider=provider)
        context.close()
        with pytest.raises(RuntimeError, match="closed"):
            _ = context.credential

    def test_get_table_client_raises_when_not_configured(self, mocker: MockerFixture) -> None:
        """Raise RuntimeError when requesting a table client without table service configured."""
        provider = mocker.MagicMock()
        provider.get_credential.return_value = mocker.MagicMock()
        context = AzureStorageContext(identity_provider=provider)
        with pytest.raises(RuntimeError, match="Table Storage not configured"):
            context.get_table_client("Jobs")

    def test_get_container_client_raises_when_not_configured(self, mocker: MockerFixture) -> None:
        """Raise RuntimeError when requesting a container client without blob service configured."""
        provider = mocker.MagicMock()
        provider.get_credential.return_value = mocker.MagicMock()
        context = AzureStorageContext(identity_provider=provider)
        with pytest.raises(RuntimeError, match="Blob Storage not configured"):
            context.get_container_client("workspaces")

    def test_table_only_context_created_without_blob(self, mocker: MockerFixture) -> None:
        """Create a context with table service only and verify has_blob is False."""
        mock_table_cls = mocker.patch("src.core.storage.azure_context.TableServiceClient")
        provider = mocker.MagicMock()
        provider.get_credential.return_value = mocker.MagicMock()
        mock_table_cls.return_value = mocker.MagicMock()
        context = create_azure_storage_context(
            env={"AZURE_TABLE_ENDPOINT": _TABLE_ENDPOINT},
            identity_provider=provider,
        )
        assert context is not None
        assert context.has_table is True
        assert context.has_blob is False

    def test_blob_only_context_created_without_table(self, mocker: MockerFixture) -> None:
        """Create a context with blob service only and verify has_table is False."""
        mock_blob_cls = mocker.patch("src.core.storage.azure_context.BlobServiceClient")
        provider = mocker.MagicMock()
        provider.get_credential.return_value = mocker.MagicMock()
        mock_blob_cls.return_value = mocker.MagicMock()
        context = create_azure_storage_context(
            env={"AZURE_BLOB_ENDPOINT": _BLOB_ENDPOINT},
            identity_provider=provider,
        )
        assert context is not None
        assert context.has_table is False
        assert context.has_blob is True

    def test_close_handles_service_close_exceptions(self, mocker: MockerFixture) -> None:
        """Suppress exceptions raised during service close so the context becomes closed."""
        provider = mocker.MagicMock()
        provider.get_credential.return_value = mocker.MagicMock()
        table_service = mocker.MagicMock()
        table_service.close.side_effect = RuntimeError("close failed")
        context = AzureStorageContext(identity_provider=provider, table_service=table_service)
        context.close()
        table_service.close.assert_called_once()

    def test_create_storage_context_requires_azure_context_for_table_backend(self) -> None:
        """Raise RuntimeError when creating storage context with table endpoint but no Azure context."""
        with pytest.raises(RuntimeError, match="AzureStorageContext"):
            create_storage_context(env={"AZURE_TABLE_ENDPOINT": _TABLE_ENDPOINT})

    def test_storage_context_close_does_not_close_injected_azure_context(
        self, mocker: MockerFixture
    ) -> None:
        """Verify StorageContext.close does not close the shared Azure context or its table clients."""
        azure_context = mocker.MagicMock()
        azure_context.has_table = True
        jobs_client = mocker.MagicMock()
        schedules_client = mocker.MagicMock()
        azure_context.get_table_client.side_effect = [jobs_client, schedules_client]

        context = create_storage_context(
            env={"AZURE_TABLE_ENDPOINT": _TABLE_ENDPOINT},
            azure_context=azure_context,
        )
        context.close()

        azure_context.close.assert_not_called()
        jobs_client.close.assert_not_called()
        schedules_client.close.assert_not_called()

    def test_injected_table_clients_are_non_owning(self, mocker: MockerFixture) -> None:
        """Confirm store close does not close externally injected table clients."""
        jobs_client = mocker.MagicMock()
        schedules_client = mocker.MagicMock()

        AzureTableJobStore(table_client=jobs_client).close()
        AzureTableScheduleStore(table_client=schedules_client).close()

        jobs_client.close.assert_not_called()
        schedules_client.close.assert_not_called()
