# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Workspace discovery — supports filesystem and Azure Blob Storage backends.

Delegates all I/O to a :class:`~src.core.services.workspace_backend.WorkspaceBackend`
instance that is lazily created from environment variables on first use.
"""

import logging
from typing import List

from src.core.models.workspace import WorkspaceInfo
from src.core.services.workspace_backend import (
    FilesystemBackend,
    WorkspaceBackend,
    create_workspace_backend,
)

logger = logging.getLogger(__name__)

_backend: WorkspaceBackend | None = None


def get_workspace_backend() -> WorkspaceBackend:
    """Get or create the singleton workspace backend.

    The backend is lazily initialised from environment variables on
    first call and then cached for the lifetime of the process.

    :returns: The active workspace backend.
    :rtype: WorkspaceBackend
    """
    global _backend
    if _backend is None:
        _backend = create_workspace_backend()
    return _backend


def set_workspace_backend(backend: WorkspaceBackend) -> None:
    """Override the workspace backend (for testing).

    :param backend: Backend instance to use.
    :type backend: WorkspaceBackend
    """
    global _backend
    _backend = backend


def load_workspaces_from_directory(
    base_dir: str = "WORKSPACES/SYSTEM",
) -> List[WorkspaceInfo]:
    """Load workspaces using the configured backend.

    The *base_dir* parameter is accepted for backward compatibility
    with call-sites that pass a directory path.  When the backend is
    ``blob``, configuration comes from environment variables and
    *base_dir* is ignored.  When the backend is ``filesystem`` and
    *base_dir* differs from the singleton's base, a one-off
    :class:`FilesystemBackend` is used for the call.

    :param base_dir: Base directory (used only by filesystem backend).
    :type base_dir: str
    :returns: List of discovered workspace information.
    :rtype: List[WorkspaceInfo]
    """
    backend = get_workspace_backend()

    if isinstance(backend, FilesystemBackend):
        if str(backend._base) != base_dir:
            return FilesystemBackend(base_dir=base_dir).list_workspaces()

    return backend.list_workspaces()
