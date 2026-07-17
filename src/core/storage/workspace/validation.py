# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Workspace ID/path validation and shared parsing helpers."""

from __future__ import annotations
import os
import re
from typing import Any
import yaml
from src.core.exceptions import WorkspaceConfigError, WorkspaceValidationError

VALID_WORKSPACE_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")
MAX_WORKSPACE_ID_LEN = 128
MAX_CONFIG_FILE_SIZE = 1024 * 1024
WORKSPACE_CONFIG_FILES = ("hosts.yaml", "sap-parameters.yaml")
WORKSPACE_MANIFEST_FILE = "workspace-manifest.json"
BLOB_CONTAINER = "workspaces"


def validate_workspace_id(workspace_id: str) -> str:
    """Validate a workspace ID for safety.

    :param workspace_id: Raw workspace identifier to validate.
    :returns: The validated workspace_id (unchanged).
    :raises WorkspaceValidationError: For invalid IDs.
    """
    if not workspace_id:
        raise WorkspaceValidationError("Workspace ID must not be empty")

    if "\x00" in workspace_id:
        raise WorkspaceValidationError("Workspace ID contains null byte")

    if len(workspace_id) > MAX_WORKSPACE_ID_LEN:
        raise WorkspaceValidationError(f"Workspace ID exceeds {MAX_WORKSPACE_ID_LEN} characters")

    if not VALID_WORKSPACE_ID.match(workspace_id):
        raise WorkspaceValidationError(
            f"Workspace ID contains invalid characters: {workspace_id!r}"
        )

    if ".." in workspace_id.split(os.sep) or ".." in workspace_id.split("/"):
        raise WorkspaceValidationError("Workspace ID contains path traversal")

    return workspace_id


def extract_environment(workspace_id: str) -> str:
    """Extract environment prefix from workspace ID.

    :param workspace_id: Workspace identifier
    :type workspace_id: str
    :return: Prefix before the first hyphen, or an empty string
    :rtype: str
    """
    return workspace_id.split("-")[0] if "-" in workspace_id else ""


def _load_yaml_mapping(
    content: bytes, file_name: str, *, require_non_empty: bool
) -> dict[str, Any]:
    """Parse YAML content and require a mapping result."""
    if len(content) > MAX_CONFIG_FILE_SIZE:
        raise WorkspaceConfigError(f"{file_name} exceeds {MAX_CONFIG_FILE_SIZE} byte limit")

    try:
        parsed = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        raise WorkspaceConfigError(f"Malformed {file_name}: {exc}") from exc

    if not isinstance(parsed, dict):
        raise WorkspaceConfigError(f"{file_name} must contain a YAML mapping")

    if require_non_empty and not parsed:
        raise WorkspaceConfigError(f"{file_name} must not be empty")

    return parsed


def parse_sap_parameters(content: bytes) -> dict[str, Any]:
    """Parse sap-parameters.yaml content with strict mapping validation.

    :param content: Raw YAML bytes.
    :returns: Parsed parameter mapping.
    """
    return _load_yaml_mapping(content, "sap-parameters.yaml", require_non_empty=False)


def parse_hosts_yaml(content: bytes) -> dict[str, Any]:
    """Parse hosts.yaml content with strict non-empty mapping validation.

    :param content: Raw YAML bytes.
    :returns: Parsed inventory mapping.
    """
    return _load_yaml_mapping(content, "hosts.yaml", require_non_empty=True)
