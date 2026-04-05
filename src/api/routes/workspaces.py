# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Workspaces API routes."""

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
import yaml
from fastapi import APIRouter, HTTPException
from src.core.observability import get_logger
from src.core.models.workspace import WorkspaceInfo, WorkspaceListResponse
from src.core.services.workspace_discovery import load_workspaces_from_directory

logger = get_logger(__name__)
router = APIRouter(prefix="/workspaces", tags=["workspaces"])
_workspace_loader: Optional[Callable[[str], Dict[str, Any]]] = None


def set_workspace_loader(loader: Callable[[str], Dict[str, Any]]) -> None:
    """Set the workspace loader function.

    :param loader: Callable that loads workspace config by ID.
    :type loader: Callable[[str], Dict[str, Any]]
    """
    global _workspace_loader
    _workspace_loader = loader


def _load_workspaces_from_directory(base_dir: str = "WORKSPACES/SYSTEM") -> List[WorkspaceInfo]:
    """Load workspaces from WORKSPACES/SYSTEM directory structure.

    .. deprecated:: Use :func:`src.core.services.workspace_discovery.load_workspaces_from_directory`.

    :param base_dir: Base directory containing workspace subdirectories.
    :type base_dir: str
    :returns: List of discovered workspace information.
    :rtype: List[WorkspaceInfo]
    """
    return load_workspaces_from_directory(base_dir)


@router.get("", response_model=WorkspaceListResponse)
async def list_workspaces() -> WorkspaceListResponse:
    """List all available workspaces.

    :returns: Response containing list of workspaces and total count.
    :rtype: WorkspaceListResponse
    """
    workspaces = _load_workspaces_from_directory()
    return WorkspaceListResponse(workspaces=workspaces, total=len(workspaces))


@router.get("/{workspace_id}", response_model=WorkspaceInfo)
async def get_workspace(workspace_id: str) -> WorkspaceInfo:
    """Get a specific workspace.

    :param workspace_id: ID of the workspace to retrieve.
    :type workspace_id: str
    :returns: Workspace information.
    :rtype: WorkspaceInfo
    :raises HTTPException: If workspace not found (404 error).
    """
    workspaces = _load_workspaces_from_directory()

    for ws in workspaces:
        if ws.id == workspace_id:
            return ws

    raise HTTPException(status_code=404, detail=f"Workspace {workspace_id} not found")


def default_workspace_loader(workspace_id: str) -> Dict[str, Any]:
    """Default workspace config loader.

    :param workspace_id: ID of the workspace to load.
    :type workspace_id: str
    :returns: Workspace configuration dictionary.
    :rtype: Dict[str, Any]
    """
    workspace_dir = Path("WORKSPACES/SYSTEM") / workspace_id

    if not workspace_dir.exists():
        return {}

    hosts_file = workspace_dir / "hosts.yaml"
    params_file = workspace_dir / "sap-parameters.yaml"

    if not hosts_file.exists():
        return {}

    config: Dict[str, Any] = {
        "inventory_path": str(hosts_file),
    }

    if params_file.exists():
        try:
            with open(params_file) as f:
                params = yaml.safe_load(f) or {}
            config["sap_sid"] = params.get("sap_sid", "")
            config["db_sid"] = params.get("db_sid", "")
            config["database_high_availability"] = params.get("database_high_availability", False)
            config["scs_high_availability"] = params.get("scs_high_availability", False)
            config["extra_vars"] = params
        except Exception as e:
            logger.warning(f"Failed to load sap-parameters for {workspace_id}: {e}")

    return config
