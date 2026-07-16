# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Workspace backend factory — selects filesystem or blob based on configuration."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping
from src.core.exceptions import WorkspaceBackendError
from src.core.storage.azure_context import AzureStorageContext
from src.core.storage.workspace.blob import BlobWorkspaceBackend
from src.core.storage.workspace.filesystem import FilesystemWorkspaceBackend
from src.core.storage.workspace.validation import BLOB_CONTAINER


def create_workspace_backend(
    *,
    env: Mapping[str, str] | None = None,
    azure_context: AzureStorageContext | None = None,
    workspaces_base: Path | None = None,
    data_dir: Path | None = None,
) -> FilesystemWorkspaceBackend | BlobWorkspaceBackend:
    """Create the appropriate workspace backend based on configuration."""
    resolved_env = env if env is not None else os.environ
    endpoint = (resolved_env.get("AZURE_BLOB_ENDPOINT") or "").strip()

    if not endpoint:
        base = workspaces_base or Path(resolved_env.get("WORKSPACES_BASE", "WORKSPACES/SYSTEM"))
        return FilesystemWorkspaceBackend(workspaces_base=base, data_dir=data_dir)

    if azure_context is None or not azure_context.has_blob:
        raise WorkspaceBackendError(
            "AZURE_BLOB_ENDPOINT is set but no AzureStorageContext with Blob Storage is available"
        )

    container = (resolved_env.get("AZURE_BLOB_CONTAINER") or "").strip() or BLOB_CONTAINER
    resolved_data_dir = data_dir or Path(resolved_env.get("DATA_DIR", "data"))
    return BlobWorkspaceBackend(
        container_client=azure_context.get_container_client(container),
        data_dir=resolved_data_dir,
    )
