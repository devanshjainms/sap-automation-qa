# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for Azure identity provider and credential injection."""

from unittest.mock import MagicMock, patch
import pytest
from src.core.auth import DefaultIdentityProvider
from src.core.contracts.azure_identity import AzureIdentityProvider


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
