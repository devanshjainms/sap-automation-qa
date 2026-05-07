# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Shared fixtures for MCP server tests."""

from __future__ import annotations

from typing import Generator

import pytest

from src.core.services.workspace_backend import FilesystemBackend
from src.core.services.workspace_discovery import set_workspace_backend


@pytest.fixture(autouse=True)
def _reset_workspace_backend() -> Generator[None, None, None]:
    """Reset the workspace backend singleton after each test."""
    yield
    set_workspace_backend(None)  # type: ignore[arg-type]
