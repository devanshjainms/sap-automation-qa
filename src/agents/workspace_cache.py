# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Conversation-scoped context cache for workspace execution data.

This module prevents repeated workspace resolution by caching:
- Workspace ID (resolved from SID)
- Execution context (hosts, SSH key, OS, parameters)
- Last accessed timestamp

Reduces redundant API calls and improves response time.
"""

from contextvars import ContextVar
from typing import Optional, Any
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from src.agents.observability import get_logger

logger = get_logger(__name__)

_workspace_cache: ContextVar[Optional["WorkspaceCache"]] = ContextVar(
    "workspace_cache", default=None
)


@dataclass
class WorkspaceCache:
    """Cached workspace execution context for a conversation.

    Prevents repeated resolution of:
    - SID → workspace_id mapping
    - Workspace files (hosts.yaml, sap-parameters.yaml)
    - SSH key discovery

    """

    conversation_id: str
    resolved_workspace_id: Optional[str] = None
    resolved_sid: Optional[str] = None
    execution_context: Optional[dict[str, Any]] = None
    last_updated: datetime = field(default_factory=datetime.utcnow)
    ttl_seconds: int = 300

    def is_expired(self) -> bool:
        """Check if cache is older than TTL.

        :returns: True if cache should be refreshed
        """
        age = datetime.utcnow() - self.last_updated
        return age > timedelta(seconds=self.ttl_seconds)

    def set_workspace(self, workspace_id: str, sid: Optional[str] = None) -> None:
        """Cache workspace resolution.

        :param workspace_id: Resolved workspace ID
        :param sid: SAP SID associated with workspace
        """
        self.resolved_workspace_id = workspace_id
        if sid:
            self.resolved_sid = sid
        self.last_updated = datetime.utcnow()
        logger.info(f"Cached workspace resolution: {sid} → {workspace_id}")

    def set_execution_context(self, context: dict[str, Any]) -> None:
        """Cache full execution context.

        :param context: Execution context from get_execution_context()
        """
        self.execution_context = context
        self.last_updated = datetime.utcnow()

        logger.info(f"Cached execution context for {context.get('workspace_id')}")

    def get_workspace_id(self) -> Optional[str]:
        """Get cached workspace ID if not expired.

        :returns: Workspace ID or None
        """
        if self.is_expired():
            logger.debug("Workspace cache expired, will refresh")
            return None
        return self.resolved_workspace_id

    def get_execution_context(self) -> Optional[dict[str, Any]]:
        """Get cached execution context if not expired.

        :returns: Execution context dict or None
        """
        if self.is_expired():
            logger.debug("Execution context cache expired, will refresh")
            return None
        return self.execution_context

    def invalidate(self) -> None:
        """Force cache refresh on next access."""
        self.last_updated = datetime.utcnow() - timedelta(seconds=self.ttl_seconds + 1)
        logger.info(f"Invalidated workspace cache for conversation {self.conversation_id}")


class WorkspaceCacheManager:
    """Manages workspace cache for conversations."""

    @staticmethod
    def set(cache: WorkspaceCache) -> None:
        """Set workspace cache for current context.

        :param cache: WorkspaceCache instance
        """
        _workspace_cache.set(cache)

    @staticmethod
    def get() -> Optional[WorkspaceCache]:
        """Get current workspace cache.

        :returns: WorkspaceCache if set, None otherwise
        """
        return _workspace_cache.get()

    @staticmethod
    def clear() -> None:
        """Clear workspace cache for current context."""
        _workspace_cache.set(None)

    @staticmethod
    def get_or_create(conversation_id: str) -> WorkspaceCache:
        """Get existing workspace cache or create new one.

        :param conversation_id: Conversation ID
        :returns: WorkspaceCache instance
        """
        cache = _workspace_cache.get()
        if cache and cache.conversation_id == conversation_id:
            return cache

        new_cache = WorkspaceCache(conversation_id=conversation_id)
        _workspace_cache.set(new_cache)
        logger.info(f"Created new workspace cache for conversation {conversation_id}")
        return new_cache
