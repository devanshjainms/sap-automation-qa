# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for SshCredentialCache."""

from __future__ import annotations
import time
import pytest
from pytest_mock import MockerFixture
from src.core.execution.ssh_cache import SshCredentialCache, _DEFAULT_TTL_SECONDS
from src.core.models.ssh import AuthType, SshCredential


def _make_credential(workspace: str = "WS1") -> SshCredential:
    """Build a minimal ``SshCredential``."""
    return SshCredential(
        auth_type=AuthType.SSHKEY,
        private_key_path=f"/tmp/{workspace}.key",
    )


def _make_provider(
    mocker: MockerFixture,
    side_effect: list[SshCredential | None] | None = None,
):
    """Build a mock ``SshCredentialProvider``."""
    provider = mocker.MagicMock()
    if side_effect is not None:
        provider.provision.side_effect = side_effect
    else:
        provider.provision.side_effect = lambda ws, ev: _make_credential(ws)
    return provider


class TestSshCredentialCache:
    """Tests for SSH credential caching with TTL."""

    def test_provision_delegates_to_provider(self, mocker: MockerFixture) -> None:
        provider = _make_provider(mocker)
        cache = SshCredentialCache(provider)

        cred = cache.provision("WS1", {"key": "val"})

        assert cred is not None
        assert cred.auth_type == AuthType.SSHKEY
        provider.provision.assert_called_once_with("WS1", {"key": "val"})

    def test_cache_hit_avoids_reprovision(self, mocker: MockerFixture) -> None:
        provider = _make_provider(mocker)
        cache = SshCredentialCache(provider)

        cred1 = cache.provision("WS1", {})
        cred2 = cache.provision("WS1", {})

        assert cred1 is cred2
        assert provider.provision.call_count == 1

    def test_different_workspaces_cached_separately(self, mocker: MockerFixture) -> None:
        provider = _make_provider(mocker)
        cache = SshCredentialCache(provider)

        cred1 = cache.provision("WS1", {})
        cred2 = cache.provision("WS2", {})

        assert cred1 is not cred2
        assert provider.provision.call_count == 2

    def test_expired_entry_reprovisions(self, mocker: MockerFixture) -> None:
        provider = _make_provider(mocker)
        cache = SshCredentialCache(provider, ttl_seconds=1)

        cred1 = cache.provision("WS1", {})

        # Simulate time passing beyond TTL
        entry = cache._cache["WS1"]
        entry.expires_at = time.monotonic() - 1

        cred2 = cache.provision("WS1", {})

        assert cred2 is not cred1
        assert provider.provision.call_count == 2

    def test_expired_entry_cleanup_called(self, mocker: MockerFixture) -> None:
        cred1 = _make_credential("WS1")
        cred1.cleanup = mocker.MagicMock()
        provider = _make_provider(mocker, side_effect=[cred1, _make_credential("WS1")])
        cache = SshCredentialCache(provider, ttl_seconds=1)

        cache.provision("WS1", {})

        # Expire the entry
        entry = cache._cache["WS1"]
        entry.expires_at = time.monotonic() - 1

        cache.provision("WS1", {})
        cred1.cleanup.assert_called_once()

    def test_invalidate_removes_entry(self, mocker: MockerFixture) -> None:
        provider = _make_provider(mocker)
        cache = SshCredentialCache(provider)

        cred = cache.provision("WS1", {})
        cred.cleanup = mocker.MagicMock()

        cache.invalidate("WS1")

        assert cache.size == 0
        cred.cleanup.assert_called_once()

    def test_invalidate_nonexistent_is_noop(self, mocker: MockerFixture) -> None:
        provider = _make_provider(mocker)
        cache = SshCredentialCache(provider)
        cache.invalidate("NONEXISTENT")
        assert cache.size == 0

    def test_clear_removes_all(self, mocker: MockerFixture) -> None:
        provider = _make_provider(mocker)
        cache = SshCredentialCache(provider)

        cred1 = cache.provision("WS1", {})
        cred2 = cache.provision("WS2", {})
        cred1.cleanup = mocker.MagicMock()
        cred2.cleanup = mocker.MagicMock()

        cache._cache["WS1"].credential = cred1
        cache._cache["WS2"].credential = cred2

        cache.clear()

        assert cache.size == 0
        cred1.cleanup.assert_called_once()
        cred2.cleanup.assert_called_once()

    def test_size_property(self, mocker: MockerFixture) -> None:
        provider = _make_provider(mocker)
        cache = SshCredentialCache(provider)

        assert cache.size == 0
        cache.provision("WS1", {})
        assert cache.size == 1
        cache.provision("WS2", {})
        assert cache.size == 2

    def test_provision_returns_none_on_failure(self, mocker: MockerFixture) -> None:
        provider = _make_provider(mocker, side_effect=[None])
        cache = SshCredentialCache(provider)

        cred = cache.provision("WS1", {})

        assert cred is None
        assert cache.size == 0

    def test_default_ttl(self, mocker: MockerFixture) -> None:
        provider = _make_provider(mocker)
        cache = SshCredentialCache(provider)
        assert cache._ttl == _DEFAULT_TTL_SECONDS
