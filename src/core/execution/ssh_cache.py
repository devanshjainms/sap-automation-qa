# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
SSH credential cache — avoids re-provisioning on every tool call.

The :class:`SshCredentialCache` wraps an :class:`SshCredentialProvider`
and caches provisioned credentials per workspace with a configurable
TTL.  Expired or unused credentials are cleaned up automatically.

Thread-safety: the cache uses a simple dict with no locking.  This is
safe because FastMCP handles one request at a time per session, and
the cache is only accessed from the async MCP tool handlers.
"""

from __future__ import annotations
import logging
import time
from dataclasses import dataclass
from typing import Any, Optional
from src.core.execution.ssh_provider import SshCredentialProvider
from src.core.models.ssh import SshCredential

logger = logging.getLogger(__name__)

_DEFAULT_TTL_SECONDS = 300


@dataclass
class _CacheEntry:
    """Internal cache entry with expiry timestamp.

    :param credential: Provisioned SSH credential.
    :param expires_at: Monotonic time when this entry expires.
    """

    credential: SshCredential
    expires_at: float


class SshCredentialCache:
    """TTL-based cache around :class:`SshCredentialProvider`.

    :param provider: Underlying SSH credential provider.
    :param ttl_seconds: How long cached credentials remain valid.
    """

    def __init__(
        self,
        provider: SshCredentialProvider,
        *,
        ttl_seconds: int = _DEFAULT_TTL_SECONDS,
    ) -> None:
        self._provider = provider
        self._ttl = ttl_seconds
        self._cache: dict[str, _CacheEntry] = {}

    def provision(
        self,
        workspace_id: str,
        extra_vars: dict[str, Any],
    ) -> Optional[SshCredential]:
        """Return a cached credential or provision a new one.

        :param workspace_id: Target workspace identifier.
        :param extra_vars: Extra variables for SSH provisioning.
        :returns: SSH credential, or ``None`` on failure.
        """
        now = time.monotonic()
        entry = self._cache.get(workspace_id)

        if entry is not None and entry.expires_at > now:
            logger.debug("SSH cache hit for workspace %s", workspace_id)
            return entry.credential

        if entry is not None:
            logger.debug("SSH cache expired for workspace %s", workspace_id)
            entry.credential.cleanup()
            del self._cache[workspace_id]

        credential = self._provider.provision(workspace_id, extra_vars)
        if credential is not None:
            self._cache[workspace_id] = _CacheEntry(
                credential=credential,
                expires_at=now + self._ttl,
            )
            logger.info("Cached SSH credential for workspace %s", workspace_id)
        return credential

    def invalidate(self, workspace_id: str) -> None:
        """Remove a cached credential.

        :param workspace_id: Workspace to invalidate.
        """
        entry = self._cache.pop(workspace_id, None)
        if entry is not None:
            entry.credential.cleanup()
            logger.info("Invalidated SSH cache for workspace %s", workspace_id)

    def clear(self) -> None:
        """Remove all cached credentials."""
        for entry in self._cache.values():
            entry.credential.cleanup()
        self._cache.clear()
        logger.info("Cleared SSH credential cache")

    @property
    def size(self) -> int:
        """Number of cached credentials."""
        return len(self._cache)
