# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Workspaces API routes."""

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import yaml
from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from src.core.observability import get_logger
from src.core.models.workspace import (
    WorkspaceConfig,
    WorkspaceInfo,
    WorkspaceListResponse,
    TestReport,
)
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


def _resolve_workspace_path(workspace_id: str) -> Path:
    """Resolve and validate a workspace directory path.

    :param workspace_id: ID of the workspace.
    :type workspace_id: str
    :returns: Validated workspace directory path.
    :rtype: Path
    :raises HTTPException: If workspace directory not found or path is invalid.
    """
    base = Path("WORKSPACES/SYSTEM").resolve()
    workspace_dir = (base / workspace_id).resolve()

    if not str(workspace_dir).startswith(str(base)):
        raise HTTPException(status_code=400, detail="Invalid workspace ID")
    if not workspace_dir.is_dir():
        raise HTTPException(
            status_code=404,
            detail=f"Workspace {workspace_id} not found",
        )
    return workspace_dir


_CONFIG_WHITELIST = {
    "sap_sid",
    "db_sid",
    "platform",
    "db_instance_number",
    "scs_instance_number",
    "ers_instance_number",
    "database_high_availability",
    "scs_high_availability",
    "database_cluster_type",
    "scs_cluster_type",
    "database_scale_out",
    "NFS_provider",
}


@router.get("/{workspace_id}/config", response_model=WorkspaceConfig)
async def get_workspace_config(workspace_id: str) -> WorkspaceConfig:
    """Get whitelisted configuration for a workspace.

    :param workspace_id: ID of the workspace.
    :type workspace_id: str
    :returns: Whitelisted workspace configuration fields.
    :rtype: WorkspaceConfig
    :raises HTTPException: If workspace or config file not found.
    """
    workspace_dir = _resolve_workspace_path(workspace_id)
    params_file = workspace_dir / "sap-parameters.yaml"
    hosts_file = workspace_dir / "hosts.yaml"

    if not params_file.exists():
        raise HTTPException(
            status_code=404,
            detail="sap-parameters.yaml not found",
        )

    try:
        with open(params_file) as f:
            params = yaml.safe_load(f) or {}
    except Exception as exc:
        logger.warning("Failed to read config for %s: %s", workspace_id, exc)
        raise HTTPException(
            status_code=500,
            detail="Failed to read workspace configuration",
        ) from exc

    hosts: List[str] = []
    if hosts_file.exists():
        try:
            with open(hosts_file) as f:
                inventory = yaml.safe_load(f) or {}
            for group in inventory.values():
                if isinstance(group, dict) and "hosts" in group:
                    hosts.extend(group["hosts"].keys())
        except Exception as exc:
            logger.warning("Failed to parse hosts for %s: %s", workspace_id, exc)

    return WorkspaceConfig(
        sap_sid=str(params.get("sap_sid", "")),
        db_sid=str(params.get("db_sid", "")),
        platform=str(params.get("platform", "")),
        db_instance_number=str(params.get("db_instance_number", "")),
        scs_instance_number=str(params.get("scs_instance_number", "")),
        ers_instance_number=str(params.get("ers_instance_number", "")),
        database_high_availability=bool(params.get("database_high_availability", False)),
        scs_high_availability=bool(params.get("scs_high_availability", False)),
        database_cluster_type=str(params.get("database_cluster_type", "")),
        scs_cluster_type=str(params.get("scs_cluster_type", "")),
        database_scale_out=bool(params.get("database_scale_out", False)),
        nfs_provider=str(params.get("NFS_provider", "")),
        hosts=hosts,
    )


@router.get("/{workspace_id}/reports", response_model=List[TestReport])
async def list_workspace_reports(workspace_id: str) -> List[TestReport]:
    """List the most recent HTML test reports for a workspace.

    :param workspace_id: ID of the workspace.
    :type workspace_id: str
    :returns: List of up to 10 most recent test reports.
    :rtype: List[TestReport]
    """
    workspace_dir = _resolve_workspace_path(workspace_id)
    qa_dir = workspace_dir / "quality_assurance"

    if not qa_dir.is_dir():
        return []

    reports: List[TestReport] = []
    for html_file in qa_dir.glob("*.html"):
        if not html_file.is_file():
            continue
        stat = html_file.stat()
        reports.append(
            TestReport(
                filename=html_file.name,
                modified_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                size_bytes=stat.st_size,
            )
        )

    reports.sort(key=lambda r: r.modified_at, reverse=True)
    return reports[:10]


@router.get("/{workspace_id}/reports/{filename}")
async def get_workspace_report(workspace_id: str, filename: str) -> HTMLResponse:
    """Get the HTML content of a specific test report.

    :param workspace_id: ID of the workspace.
    :type workspace_id: str
    :param filename: Name of the HTML report file.
    :type filename: str
    :returns: HTML content of the report.
    :rtype: HTMLResponse
    :raises HTTPException: If file not found or invalid filename.
    """
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    if not filename.endswith(".html"):
        raise HTTPException(status_code=400, detail="Only .html files are allowed")

    workspace_dir = _resolve_workspace_path(workspace_id)
    report_path = (workspace_dir / "quality_assurance" / filename).resolve()

    qa_dir = (workspace_dir / "quality_assurance").resolve()
    if not str(report_path).startswith(str(qa_dir)):
        raise HTTPException(status_code=400, detail="Invalid filename")

    if not report_path.is_file():
        raise HTTPException(status_code=404, detail="Report not found")

    content = report_path.read_text(encoding="utf-8")
    return HTMLResponse(
        content=content,
        headers={
            "Content-Security-Policy": (
                "default-src 'none'; " "style-src 'unsafe-inline'; " "img-src data:;"
            ),
        },
    )


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
