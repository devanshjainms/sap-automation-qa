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


class CreateWorkspaceRequest(BaseModel):
    """Request model for creating a workspace."""

    workspace_id: str
    clone_from: Optional[str] = "X00"


class FileContentResponse(BaseModel):
    """Response model for file content."""

    content: str


class UpdateFileContentRequest(BaseModel):
    """Request model for updating file content."""

    content: str


@router.post("", response_model=WorkspaceInfo, status_code=201)
async def create_workspace(request: CreateWorkspaceRequest) -> WorkspaceInfo:
    """Create a new workspace by cloning an existing one.

    :param request: Create workspace request
    :type request: CreateWorkspaceRequest
    :returns: Created workspace info
    :rtype: WorkspaceInfo
    """
    import shutil
    import yaml

    store = get_workspace_store()

    try:
        existing = store.get_workspace(request.workspace_id)
        if existing:
            raise HTTPException(
                status_code=400, detail=f"Workspace {request.workspace_id} already exists"
            )

        clone_from = request.clone_from or "X00"
        source_workspace = store.get_workspace(clone_from)
        if not source_workspace:
            raise HTTPException(status_code=404, detail=f"Source workspace {clone_from} not found")
        new_workspace_path = store.root_path / request.workspace_id
        new_workspace_path.mkdir(parents=True, exist_ok=False)
        if source_workspace.path:
            for file_name in ["sap-parameters.yaml", "hosts.yaml"]:
                source_file = source_workspace.path / file_name
                if source_file.exists():
                    dest_file = new_workspace_path / file_name
                    shutil.copy2(source_file, dest_file)
                    logger.info(f"Copied {file_name} from {clone_from} to {request.workspace_id}")
        new_workspace = store.get_workspace(request.workspace_id)
        if not new_workspace:
            raise HTTPException(
                status_code=500, detail=f"Failed to create workspace {request.workspace_id}"
            )

        logger.info(f"Created workspace {request.workspace_id} from {request.clone_from}")

        return WorkspaceInfo(
            workspace_id=new_workspace.workspace_id,
            env=new_workspace.env,
            region=new_workspace.region,
            deployment_code=new_workspace.deployment_code,
            sid=new_workspace.sid,
            path=str(new_workspace.path) if new_workspace.path else None,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create workspace: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create workspace: {e}")


@router.delete("/{workspace_id}", status_code=204)
async def delete_workspace(workspace_id: str) -> None:
    """Delete a workspace.

    :param workspace_id: Workspace ID to delete
    :type workspace_id: str
    """
    import shutil

    store = get_workspace_store()

    try:
        workspace = store.get_workspace(workspace_id)
        if not workspace:
            raise HTTPException(status_code=404, detail=f"Workspace {workspace_id} not found")
        if workspace.path and workspace.path.exists():
            shutil.rmtree(workspace.path)
            logger.info(f"Deleted workspace directory: {workspace.path}")

        logger.info(f"Deleted workspace {workspace_id}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete workspace {workspace_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete workspace: {e}")


@router.get("/{workspace_id}/files/{file_name}", response_model=FileContentResponse)
async def get_file_content(workspace_id: str, file_name: str) -> FileContentResponse:
    """Get content of a workspace file.

    :param workspace_id: Workspace ID
    :type workspace_id: str
    :param file_name: File name (e.g., sap-parameters.yaml, hosts.yaml)
    :type file_name: str
    :returns: File content
    :rtype: FileContentResponse
    """
    store = get_workspace_store()

    try:
        workspace = store.get_workspace(workspace_id)
        if not workspace:
            raise HTTPException(status_code=404, detail=f"Workspace {workspace_id} not found")

        if not workspace.path:
            raise HTTPException(status_code=500, detail=f"Workspace {workspace_id} has no path")
        allowed_files = ["sap-parameters.yaml", "hosts.yaml"]
        if file_name not in allowed_files:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid file name. Allowed files: {', '.join(allowed_files)}",
            )

        file_path = workspace.path / file_name
        if not file_path.exists():
            raise HTTPException(status_code=404, detail=f"File {file_name} not found")

        with open(file_path, "r") as f:
            content = f.read()

        logger.info(f"Retrieved file {file_name} from workspace {workspace_id}")

        return FileContentResponse(content=content)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get file {file_name} from workspace {workspace_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get file content: {e}")


@router.put("/{workspace_id}/files/{file_name}", status_code=204)
async def update_file_content(
    workspace_id: str, file_name: str, request: UpdateFileContentRequest
) -> None:
    """Update content of a workspace file.

    :param workspace_id: Workspace ID
    :type workspace_id: str
    :param file_name: File name (e.g., sap-parameters.yaml, hosts.yaml)
    :type file_name: str
    :param request: Update file content request
    :type request: UpdateFileContentRequest
    """
    import yaml

    store = get_workspace_store()

    try:
        workspace = store.get_workspace(workspace_id)
        if not workspace:
            raise HTTPException(status_code=404, detail=f"Workspace {workspace_id} not found")

        if not workspace.path:
            raise HTTPException(status_code=500, detail=f"Workspace {workspace_id} has no path")
        allowed_files = ["sap-parameters.yaml", "hosts.yaml"]
        if file_name not in allowed_files:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid file name. Allowed files: {', '.join(allowed_files)}",
            )
        try:
            yaml.safe_load(request.content)
        except yaml.YAMLError as e:
            raise HTTPException(status_code=400, detail=f"Invalid YAML syntax: {str(e)}")

        file_path = workspace.path / file_name
        if file_path.exists():
            backup_path = workspace.path / f"{file_name}.bak"
            import shutil

            shutil.copy2(file_path, backup_path)
        with open(file_path, "w") as f:
            f.write(request.content)

        logger.info(f"Updated file {file_name} in workspace {workspace_id}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update file {file_name} in workspace {workspace_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to update file content: {e}")
