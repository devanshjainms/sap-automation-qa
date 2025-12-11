# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""Workspaces API routes."""

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from src.agents.workspace.workspace_store import WorkspaceStore
from src.agents.observability import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/workspaces", tags=["workspaces"])

_workspace_store: Optional[WorkspaceStore] = None


def get_workspace_store() -> WorkspaceStore:
    """Get or create workspace store singleton.

    :returns: WorkspaceStore instance
    :rtype: WorkspaceStore
    """
    global _workspace_store
    if _workspace_store is None:
        root_path = Path("WORKSPACES/SYSTEM")
        _workspace_store = WorkspaceStore(root_path=root_path)
        logger.info(f"WorkspaceStore initialized at {root_path}")
    return _workspace_store


def set_workspace_store(store: WorkspaceStore) -> None:
    """Set the workspace store instance.

    :param store: WorkspaceStore instance to use
    :type store: WorkspaceStore
    """
    global _workspace_store
    _workspace_store = store
    logger.info("WorkspaceStore injected via set_workspace_store")


class WorkspaceInfo(BaseModel):
    """Workspace information model."""

    workspace_id: str
    env: Optional[str] = None
    region: Optional[str] = None
    deployment_code: Optional[str] = None
    sid: Optional[str] = None
    path: Optional[str] = None


class WorkspaceListResponse(BaseModel):
    """Response model for workspace list."""

    workspaces: list[WorkspaceInfo]
    count: int


class WorkspaceDetailResponse(BaseModel):
    """Response model for workspace details."""

    workspace_id: str
    env: str
    region: str
    deployment_code: str
    sid: str
    path: str
    scs_hosts: Optional[list[str]] = None
    db_hosts: Optional[list[str]] = None


@router.get("", response_model=WorkspaceListResponse)
async def list_workspaces(
    sid: Optional[str] = Query(None, description="Filter by SAP System ID (e.g., X00)"),
    env: Optional[str] = Query(None, description="Filter by environment (e.g., DEV, QA, PROD)"),
) -> WorkspaceListResponse:
    """List all available workspaces.

    :param sid: Optional SID filter
    :type sid: Optional[str]
    :param env: Optional environment filter
    :type env: Optional[str]
    :returns: List of workspaces
    :rtype: WorkspaceListResponse
    """
    store = get_workspace_store()

    try:
        workspaces = store.list_workspaces()

        if sid:
            workspaces = [w for w in workspaces if w.sid.upper() == sid.upper()]
        if env:
            workspaces = [w for w in workspaces if w.env.upper() == env.upper()]

        workspace_infos = [
            WorkspaceInfo(
                workspace_id=w.workspace_id,
                env=w.env,
                region=w.region,
                deployment_code=w.deployment_code,
                sid=w.sid,
                path=str(w.path) if w.path else None,
            )
            for w in workspaces
        ]

        logger.info(f"Listed {len(workspace_infos)} workspaces (sid={sid}, env={env})")

        return WorkspaceListResponse(
            workspaces=workspace_infos,
            count=len(workspace_infos),
        )
    except Exception as e:
        logger.error(f"Failed to list workspaces: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to list workspaces: {e}")


@router.get("/{workspace_id}", response_model=WorkspaceDetailResponse)
async def get_workspace(workspace_id: str) -> WorkspaceDetailResponse:
    """Get detailed information about a specific workspace.

    :param workspace_id: Workspace ID (e.g., DEV-WEEU-SAP01-X00)
    :type workspace_id: str
    :returns: Workspace details
    :rtype: WorkspaceDetailResponse
    """
    store = get_workspace_store()

    try:
        workspace = store.get_workspace(workspace_id)

        if workspace is None:
            raise HTTPException(status_code=404, detail=f"Workspace {workspace_id} not found")

        scs_hosts = None
        db_hosts = None

        if workspace.path:
            hosts_file = workspace.path / "hosts.yaml"
            if hosts_file.exists():
                import yaml

                try:
                    with open(hosts_file) as f:
                        hosts_data = yaml.safe_load(f)
                    scs_hosts = hosts_data.get("scs_hosts", [])
                    db_hosts = hosts_data.get("db_hosts", [])
                except Exception as e:
                    logger.warning(f"Failed to load hosts from {hosts_file}: {e}")

        logger.info(f"Retrieved workspace {workspace_id}")

        return WorkspaceDetailResponse(
            workspace_id=workspace.workspace_id,
            env=workspace.env,
            region=workspace.region,
            deployment_code=workspace.deployment_code,
            sid=workspace.sid,
            path=str(workspace.path) if workspace.path else "",
            scs_hosts=scs_hosts,
            db_hosts=db_hosts,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get workspace {workspace_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get workspace: {e}")
