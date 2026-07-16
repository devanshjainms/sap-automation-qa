# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for Azure identity provider and credential injection."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.core.auth import DefaultIdentityProvider
from src.core.contracts.azure_identity import AzureIdentityProvider
from src.core.storage.azure_context import create_azure_storage_context
from src.core.storage.azure_table_store import AzureTableJobStore, AzureTableScheduleStore
from src.core.storage.factory import create_storage_context


class TestAzureIdentityProviderProtocol:
    """Verify DefaultIdentityProvider satisfies the protocol."""

    @patch("src.core.auth.azure_identity.DefaultAzureCredential")
    def test_isinstance_conformance(self, mock_cred_cls: MagicMock) -> None:
        mock_cred_cls.return_value = MagicMock()
        provider = DefaultIdentityProvider()
        assert isinstance(provider, AzureIdentityProvider)
        provider.close()

    @patch("src.core.auth.azure_identity.DefaultAzureCredential")
    def test_get_credential_returns_token_credential(self, mock_cred_cls: MagicMock) -> None:
        mock_cred = MagicMock()
        mock_cred_cls.return_value = mock_cred
        provider = DefaultIdentityProvider()
        assert provider.get_credential() is mock_cred
        provider.close()

    @patch("src.core.auth.azure_identity.DefaultAzureCredential")
    def test_close_releases_credential(self, mock_cred_cls: MagicMock) -> None:
        mock_cred = MagicMock()
        mock_cred_cls.return_value = mock_cred
        provider = DefaultIdentityProvider()
        provider.close()
        with pytest.raises(RuntimeError, match="closed"):
            provider.get_credential()

    @patch("src.core.auth.azure_identity.DefaultAzureCredential")
    def test_close_calls_credential_close_directly(self, mock_cred_cls: MagicMock) -> None:
        mock_cred = MagicMock()
        mock_cred_cls.return_value = mock_cred
        provider = DefaultIdentityProvider()
        provider.close()
        mock_cred.close.assert_called_once()


class TestAzureStoresDoNotConstructCredentials:
    """Verify Azure store consumers receive credentials; they never create them."""

    def test_job_store_requires_credential_with_endpoint(self) -> None:
        with pytest.raises(ValueError, match="credential is required"):
            AzureTableJobStore(endpoint="https://example.table.core.windows.net")

    def test_schedule_store_requires_credential_with_endpoint(self) -> None:
        with pytest.raises(ValueError, match="credential is required"):
            AzureTableScheduleStore(endpoint="https://example.table.core.windows.net")

    def test_injected_table_clients_are_non_owning(self) -> None:
        job_client = MagicMock()
        schedule_client = MagicMock()
        AzureTableJobStore(table_client=job_client).close()
        AzureTableScheduleStore(table_client=schedule_client).close()
        job_client.close.assert_not_called()
        schedule_client.close.assert_not_called()


class TestSharedContextFactoryFlow:
    """Verify context creation and storage factory use shared identity resources."""

    @patch("src.core.storage.azure_context.TableServiceClient")
    @patch("src.core.storage.azure_context.DefaultIdentityProvider")
    def test_create_azure_context_owns_internal_provider(
        self, mock_provider_cls: MagicMock, mock_table_cls: MagicMock
    ) -> None:
        provider = MagicMock()
        provider.get_credential.return_value = MagicMock()
        mock_provider_cls.return_value = provider
        mock_table_cls.return_value = MagicMock()

        context = create_azure_storage_context(
            env={"AZURE_TABLE_ENDPOINT": "https://acct.table.core.windows.net"}
        )
        assert context is not None
        assert context.identity_provider is provider
        context.close()
        provider.close.assert_called_once()

    def test_create_storage_context_uses_shared_azure_context(self, tmp_path: Path) -> None:
        azure_context = MagicMock()
        azure_context.has_table = True
        jobs_client = MagicMock()
        schedules_client = MagicMock()
        azure_context.get_table_client.side_effect = [jobs_client, schedules_client]

        context = create_storage_context(
            db_path=tmp_path / "unused.db",
            env={"AZURE_TABLE_ENDPOINT": "https://acct.table.core.windows.net"},
            azure_context=azure_context,
        )

        assert context.backend == "azure_table"
        assert context.job_store._client is jobs_client
        assert context.schedule_store._client is schedules_client
        context.close()
        azure_context.close.assert_not_called()
