# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Workspace lock — ensures only one operation runs per workspace."""

from __future__ import annotations
import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

logger = logging.getLogger(__name__)


class WorkspaceLockError(Exception):
    """Raised when a workspace lock cannot be acquired."""


class WorkspaceLockManager:
    """In-process async lock per workspace ID.

    Prevents concurrent evidence collection, test execution, or
    triage on the same workspace. Each workspace gets its own
    ``asyncio.Lock``.
    """

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}

    @asynccontextmanager
    async def acquire(self, workspace_id: str) -> AsyncIterator[None]:
        """Acquire exclusive access to a workspace.

        :param workspace_id: Workspace to lock.
        :yields: Nothing — use as ``async with lock.acquire(ws_id):``.
        :raises WorkspaceLockError: If already locked.
        """
        if workspace_id not in self._locks:
            self._locks[workspace_id] = asyncio.Lock()

        lock = self._locks[workspace_id]
        if lock.locked():
            raise WorkspaceLockError(
                f"Workspace '{workspace_id}' is busy — " f"another operation is in progress"
            )

        async with lock:
            logger.info("Locked workspace %s", workspace_id)
            try:
                yield
            finally:
                logger.info("Unlocked workspace %s", workspace_id)
