# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Workspace discovery — scans the filesystem for SAP workspaces."""

import logging
from pathlib import Path
from typing import List

import yaml

from src.core.models.workspace import WorkspaceInfo

logger = logging.getLogger(__name__)


def load_workspaces_from_directory(base_dir: str = "WORKSPACES/SYSTEM") -> List[WorkspaceInfo]:
    """Load workspaces from WORKSPACES/SYSTEM directory structure.

    :param base_dir: Base directory containing workspace subdirectories.
    :type base_dir: str
    :returns: List of discovered workspace information.
    :rtype: List[WorkspaceInfo]
    """
    workspaces: list[WorkspaceInfo] = []
    base_path = Path(base_dir)

    if not base_path.exists():
        logger.warning("Workspaces directory not found: %s", base_dir)
        return workspaces

    for workspace_dir in base_path.iterdir():
        if not workspace_dir.is_dir() or workspace_dir.name.startswith("."):
            continue
        hosts_file = workspace_dir / "hosts.yaml"
        params_file = workspace_dir / "sap-parameters.yaml"

        if not hosts_file.exists() and not params_file.exists():
            continue

        sap_sid = ""

        if params_file.exists():
            try:
                with open(params_file) as f:
                    params = yaml.safe_load(f) or {}
                sap_sid = params.get("sap_sid", "")
            except Exception as exc:
                logger.warning(
                    "Failed to load sap-parameters for %s: %s",
                    workspace_dir.name,
                    exc,
                )

        workspaces.append(
            WorkspaceInfo(
                id=workspace_dir.name,
                name=sap_sid or workspace_dir.name,
                environment=(workspace_dir.name.split("-")[0] if "-" in workspace_dir.name else ""),
                path=str(workspace_dir),
                config_exists=params_file.exists(),
            )
        )

    return workspaces
