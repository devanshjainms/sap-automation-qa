# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Workspace storage backends: filesystem (default) or Azure Blob Storage."""

from src.core.storage.workspace.blob import BlobWorkspaceBackend
from src.core.storage.workspace.factory import create_workspace_backend
from src.core.storage.workspace.filesystem import FilesystemWorkspaceBackend
from src.core.storage.workspace.validation import (
    WORKSPACE_MANIFEST_FILE,
    parse_hosts_yaml,
    parse_sap_parameters,
    validate_workspace_id,
)

__all__ = [
    "BlobWorkspaceBackend",
    "FilesystemWorkspaceBackend",
    "WORKSPACE_MANIFEST_FILE",
    "create_workspace_backend",
    "parse_hosts_yaml",
    "parse_sap_parameters",
    "validate_workspace_id",
]
