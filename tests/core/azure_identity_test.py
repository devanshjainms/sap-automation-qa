# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for Azure identity provider and credential injection."""

from pathlib import Path
import pytest
from pytest_mock import MockerFixture
from src.core.auth import DefaultIdentityProvider
from src.core.contracts.azure_identity import AzureIdentityProvider
from src.core.storage.azure_context import create_azure_storage_context
from src.core.storage.azure_table_store import AzureTableJobStore, AzureTableScheduleStore
from src.core.storage.factory import create_storage_context


class TestAzureIdentity:
    """Verify DefaultIdentityProvider satisfies the protocol."""

    def test_isinstance_conformance(self, mocker: MockerFixture) -> None:
        mock_cred_cls = mocker.patch("src.core.auth.azure_identity.DefaultAzureCredential")
        mock_cred_cls.return_value = mocker.MagicMock()
        provider = DefaultIdentityProvider()
        assert isinstance(provider, AzureIdentityProvider)
        provider.close()

    def test_get_credential_returns_token_credential(self, mocker: MockerFixture) -> None:
        mock_cred_cls = mocker.patch("src.core.auth.azure_identity.DefaultAzureCredential")
        mock_cred = mocker.MagicMock()
        mock_cred_cls.return_value = mock_cred
        provider = DefaultIdentityProvider()
        assert provider.get_credential() is mock_cred
        provider.close()

    def test_close_releases_credential(self, mocker: MockerFixture) -> None:
        mock_cred_cls = mocker.patch("src.core.auth.azure_identity.DefaultAzureCredential")
        mock_cred = mocker.MagicMock()
        mock_cred_cls.return_value = mock_cred
        provider = DefaultIdentityProvider()
        provider.close()
        with pytest.raises(RuntimeError, match="closed"):
            provider.get_credential()

    def test_close_calls_credential_close_directly(self, mocker: MockerFixture) -> None:
        mock_cred_cls = mocker.patch("src.core.auth.azure_identity.DefaultAzureCredential")
        mock_cred = mocker.MagicMock()
        mock_cred_cls.return_value = mock_cred
        provider = DefaultIdentityProvider()
        provider.close()
        mock_cred.close.assert_called_once()

    def test_job_store_requires_credential_with_endpoint(self) -> None:
        with pytest.raises(ValueError, match="credential is required"):
            AzureTableJobStore(endpoint="https://example.table.core.windows.net")

    def test_schedule_store_requires_credential_with_endpoint(self) -> None:
        with pytest.raises(ValueError, match="credential is required"):
            AzureTableScheduleStore(endpoint="https://example.table.core.windows.net")

    def test_injected_table_clients_are_non_owning(self, mocker: MockerFixture) -> None:
        job_client = mocker.MagicMock()
        schedule_client = mocker.MagicMock()
        AzureTableJobStore(table_client=job_client).close()
        AzureTableScheduleStore(table_client=schedule_client).close()
        job_client.close.assert_not_called()
        schedule_client.close.assert_not_called()

    def test_create_azure_context_owns_internal_provider(self, mocker: MockerFixture) -> None:
        mock_table_cls = mocker.patch("src.core.storage.azure_context.TableServiceClient")
        mock_provider_cls = mocker.patch("src.core.storage.azure_context.DefaultIdentityProvider")
        provider = mocker.MagicMock()
        provider.get_credential.return_value = mocker.MagicMock()
        mock_provider_cls.return_value = provider
        mock_table_cls.return_value = mocker.MagicMock()

        context = create_azure_storage_context(
            env={"AZURE_TABLE_ENDPOINT": "https://acct.table.core.windows.net"}
        )
        assert context is not None
        assert context.identity_provider is provider
        context.close()
        provider.close.assert_called_once()

    def test_create_storage_context_uses_shared_azure_context(
        self, tmp_path: Path, mocker: MockerFixture
    ) -> None:
        azure_context = mocker.MagicMock()
        azure_context.has_table = True
        jobs_client = mocker.MagicMock()
        schedules_client = mocker.MagicMock()
        azure_context.get_table_client.side_effect = [jobs_client, schedules_client]

        context = create_storage_context(
            db_path=tmp_path / "unused.db",
            env={"AZURE_TABLE_ENDPOINT": "https://acct.table.core.windows.net"},
            azure_context=azure_context,
        )

        assert context.backend == "azure_table"
        assert isinstance(context.job_store, AzureTableJobStore)
        assert isinstance(context.schedule_store, AzureTableScheduleStore)
        context.close()
        azure_context.close.assert_not_called()
