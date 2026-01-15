# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""Workspaces API routes."""

from pathlib import Path
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from src.agents.workspace.workspace_store import WorkspaceStore
from src.agents.models.workspace import (
    WorkspaceMetadata,
    WorkspaceListResponse,
    WorkspaceDetailResponse,
    ReportInfo,
    ReportsListResponse,
    CreateWorkspaceRequest,
    FileContentResponse,
    UpdateFileContentRequest,
)
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

        logger.info(f"Listed {len(workspaces)} workspaces (sid={sid}, env={env})")

        return WorkspaceListResponse(
            workspaces=workspaces,
            count=len(workspaces),
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
            workspace=workspace,
            scs_hosts=scs_hosts,
            db_hosts=db_hosts,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get workspace {workspace_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get workspace: {e}")


@router.post("", response_model=WorkspaceMetadata, status_code=201)
async def create_workspace(request: CreateWorkspaceRequest) -> WorkspaceMetadata:
    """Create a new workspace by cloning an existing one.

    :param request: Create workspace request
    :type request: CreateWorkspaceRequest
    :returns: Created workspace info
    :rtype: WorkspaceMetadata
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

        return new_workspace
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


@router.get("/{workspace_id}/reports", response_model=ReportsListResponse)
async def list_reports(workspace_id: str) -> ReportsListResponse:
    """List all HTML reports in workspace quality_assurance directory.

    :param workspace_id: Workspace ID
    :type workspace_id: str
    :returns: List of available reports
    :rtype: ReportsListResponse
    :raises HTTPException: If workspace not found
    """
    store = get_workspace_store()

    try:
        workspace = store.get_workspace(workspace_id)
        if not workspace:
            raise HTTPException(status_code=404, detail=f"Workspace {workspace_id} not found")

        if not workspace.path:
            raise HTTPException(status_code=500, detail=f"Workspace {workspace_id} has no path")

        qa_dir = workspace.path / "quality_assurance"
        logger.info(f"Looking for reports in: {qa_dir}")

        if not qa_dir.exists():
            logger.info(f"Quality assurance directory does not exist for {workspace_id}")
            return ReportsListResponse(
                workspace_id=workspace_id,
                reports=[],
                quality_assurance_dir=str(qa_dir),
            )

        # Find all HTML files recursively
        reports = []
        for html_file in qa_dir.rglob("*.html"):
            if html_file.is_file():
                relative_path = html_file.relative_to(qa_dir)
                stat = html_file.stat()
                reports.append(
                    ReportInfo(
                        name=str(relative_path),
                        path=str(relative_path),
                        size=stat.st_size,
                        modified_at=str(stat.st_mtime),
                    )
                )

        logger.info(f"Found {len(reports)} report(s) for workspace {workspace_id}")

        return ReportsListResponse(
            workspace_id=workspace_id,
            reports=sorted(reports, key=lambda r: r.modified_at, reverse=True),
            quality_assurance_dir=str(qa_dir),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to list reports for workspace {workspace_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to list reports: {e}")


@router.get("/{workspace_id}/reports/{file_path:path}")
async def get_report_file(workspace_id: str, file_path: str):
    """Serve a specific report file (HTML, CSS, JS, images, etc.).

    :param workspace_id: Workspace ID
    :type workspace_id: str
    :param file_path: Relative path to file within quality_assurance directory
    :type file_path: str
    :returns: File response
    :raises HTTPException: If file not found or invalid
    """
    store = get_workspace_store()

    try:
        workspace = store.get_workspace(workspace_id)
        if not workspace:
            raise HTTPException(status_code=404, detail=f"Workspace {workspace_id} not found")

        if not workspace.path:
            raise HTTPException(status_code=500, detail=f"Workspace {workspace_id} has no path")

        # Security: Prevent path traversal
        if ".." in file_path or file_path.startswith("/"):
            raise HTTPException(status_code=400, detail="Invalid file path")

        qa_dir = workspace.path / "quality_assurance"
        full_path = qa_dir / file_path

        # Ensure the resolved path is still within quality_assurance
        if not full_path.resolve().is_relative_to(qa_dir.resolve()):
            raise HTTPException(status_code=400, detail="Invalid file path")

        if not full_path.exists():
            raise HTTPException(status_code=404, detail=f"Report file not found: {file_path}")

        if not full_path.is_file():
            raise HTTPException(status_code=400, detail="Path is not a file")

        # Determine media type
        suffix = full_path.suffix.lower()
        media_type_map = {
            ".html": "text/html",
            ".css": "text/css",
            ".js": "application/javascript",
            ".json": "application/json",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".svg": "image/svg+xml",
        }
        media_type = media_type_map.get(suffix, "application/octet-stream")

        logger.info(f"Serving report file: {file_path} for workspace {workspace_id}")

        return FileResponse(
            path=str(full_path),
            media_type=media_type,
            filename=full_path.name,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to serve report file {file_path} for workspace {workspace_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to serve report file: {e}")
