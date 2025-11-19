# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tool functions for managing SAP QA workspaces.

These functions are designed to be called by LLM-driven agents
and return JSON-serializable dictionaries.
"""

from pathlib import Path
from typing import Optional
from src.agents.workspace.workspace_store import WorkspaceStore


def tool_list_workspaces(store: WorkspaceStore) -> dict:
    """List all workspace IDs.

    :param store: WorkspaceStore instance
    :type store: WorkspaceStore
    :returns: Dictionary with list of workspace IDs
    :rtype: dict

    Example:
        {"workspaces": ["DEV-WEEU-SAP01-X00", "QA-WEEU-SAP01-X01"]}
    """
    workspaces = store.list_workspaces()
    return {"workspaces": [ws.workspace_id for ws in workspaces]}


def tool_find_workspace_by_sid_env(store: WorkspaceStore, sid: str, env: str) -> dict:
    """Find workspaces matching SID and environment.

    :param store: WorkspaceStore instance
    :type store: WorkspaceStore
    :param sid: SAP System ID
    :type sid: str
    :param env: Environment (DEV, QA, PROD)
    :type env: str
    :returns: Dictionary with matching workspace metadata
    :rtype: dict

    Example:
        {
            "matches": [
                {
                    "workspace_id": "DEV-WEEU-SAP01-X00",
                    "env": "DEV",
                    "region": "WEEU",
                    "deployment_code": "SAP01",
                    "sid": "X00"
                }
            ]
        }
    """
    matches = store.find_by_sid_env(sid, env)
    return {"matches": [ws.to_dict() for ws in matches]}


def tool_get_workspace(store: WorkspaceStore, workspace_id: str) -> dict:
    """Get full metadata for a workspace.

    :param store: WorkspaceStore instance
    :type store: WorkspaceStore
    :param workspace_id: Workspace identifier
    :type workspace_id: str
    :returns: Dictionary with workspace metadata or error
    :rtype: dict

    Example:
        {
            "workspace_id": "DEV-WEEU-SAP01-X00",
            "env": "DEV",
            "region": "WEEU",
            "deployment_code": "SAP01",
            "sid": "X00",
            "path": "/path/to/workspace"
        }
    """
    workspace = store.get_workspace(workspace_id)
    if workspace is None:
        return {"error": f"Workspace '{workspace_id}' not found"}

    return workspace.to_dict()


def tool_create_workspace(
    store: WorkspaceStore,
    env: str,
    region: str,
    deployment_code: str,
    sid: str,
    template_dir: Optional[str] = None,
) -> dict:
    """Create a new workspace directory.

    Workspace ID is derived as: {ENV}-{REGION}-{DEPLOYMENT_CODE}-{SID} (uppercase).
    If workspace already exists, returns existing metadata with exists=True.

    :param store: WorkspaceStore instance
    :type store: WorkspaceStore
    :param env: Environment (DEV, QA, PROD)
    :type env: str
    :param region: Region code (WEEU, EAUS, etc.)
    :type region: str
    :param deployment_code: Deployment code (SAP01, SAP02, etc.)
    :type deployment_code: str
    :param sid: SAP System ID
    :type sid: str
    :param template_dir: Optional path to template directory to copy from
    :type template_dir: Optional[str]
    :returns: Dictionary with workspace metadata and creation status
    :rtype: dict

    Example:
        {
            "workspace_id": "DEV-WEEU-SAP01-X00",
            "env": "DEV",
            "region": "WEEU",
            "deployment_code": "SAP01",
            "sid": "X00",
            "path": "/path/to/workspace",
            "created": true,
            "exists": false
        }
    """
    template_path = Path(template_dir) if template_dir else None

    metadata, created = store.create_workspace(
        env=env,
        region=region,
        deployment_code=deployment_code,
        sid=sid,
        template_dir=template_path,
    )

    result = metadata.to_dict()
    result["created"] = created
    result["exists"] = not created

    return result
