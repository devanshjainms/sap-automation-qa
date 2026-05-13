# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for WorkspaceLockManager."""

from __future__ import annotations
import asyncio
import pytest
from src.core.execution.workspace_lock import WorkspaceLockError, WorkspaceLockManager


class TestWorkspaceLockManager:
    """Tests for in-process workspace locking."""

    @pytest.mark.asyncio
    async def test_acquire_and_release(self) -> None:
        """Lock acquires and releases cleanly."""
        mgr = WorkspaceLockManager()
        async with mgr.acquire("WS-A"):
            pass

    @pytest.mark.asyncio
    async def test_reentrant_after_release(self) -> None:
        """Same workspace can be locked again after release."""
        mgr = WorkspaceLockManager()
        async with mgr.acquire("WS-A"):
            pass
        async with mgr.acquire("WS-A"):
            pass

    @pytest.mark.asyncio
    async def test_concurrent_different_workspaces(self) -> None:
        """Different workspaces can be locked concurrently."""
        mgr = WorkspaceLockManager()

        async def lock_ws(ws: str) -> None:
            async with mgr.acquire(ws):
                await asyncio.sleep(0.01)

        await asyncio.gather(lock_ws("WS-A"), lock_ws("WS-B"))

    @pytest.mark.asyncio
    async def test_raises_when_already_locked(self) -> None:
        """Attempting to lock an already-locked workspace raises."""
        mgr = WorkspaceLockManager()
        acquired = asyncio.Event()
        done = asyncio.Event()

        async def hold_lock() -> None:
            async with mgr.acquire("WS-A"):
                acquired.set()
                await done.wait()

        task = asyncio.create_task(hold_lock())
        await acquired.wait()

        with pytest.raises(WorkspaceLockError, match="busy"):
            async with mgr.acquire("WS-A"):
                pass

        done.set()
        await task

    @pytest.mark.asyncio
    async def test_release_on_exception(self) -> None:
        """Lock is released even when body raises."""
        mgr = WorkspaceLockManager()
        with pytest.raises(ValueError):
            async with mgr.acquire("WS-A"):
                raise ValueError("boom")

        async with mgr.acquire("WS-A"):
            pass
