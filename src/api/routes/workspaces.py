# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Workspaces API routes."""

from typing import List
from fastapi import APIRouter, HTTPException
from src.core.contracts.workspace import WorkspaceReader
from src.core.exceptions import (
    WorkspaceBackendError,
    WorkspaceConfigError,
    WorkspaceNotFoundError,
    WorkspaceValidationError,
)
from src.core.models.workspace import WorkspaceInfo, WorkspaceListResponse, WorkspaceSummary

router = APIRouter(prefix="/workspaces", tags=["workspaces"])
_workspace_backend: WorkspaceReader | None = None


def set_workspace_backend(backend: WorkspaceReader | None) -> None:
    """Set the workspace backend for route operations.

    :param backend: Workspace reader to inject, or ``None`` to clear it.
    :type backend: WorkspaceReader | None
    """
    global _workspace_backend
    _workspace_backend = backend


def get_workspace_reader() -> WorkspaceReader:
    """Return the configured workspace reader.

    :return: Configured workspace reader.
    :rtype: WorkspaceReader
    :raises HTTPException: If the workspace backend has not been initialized.
    """
    if _workspace_backend is None:
        raise HTTPException(status_code=503, detail="Workspace backend not initialized")
    return _workspace_backend


def _validate_workspace_id_http(workspace_id: str) -> str:
    """Validate a workspace identifier for an HTTP request.

    :param workspace_id: Workspace identifier to validate.
    :type workspace_id: str
    :return: Validated workspace identifier.
    :rtype: str
    :raises HTTPException: If the workspace identifier is invalid.
    """
    from src.core.storage.workspace import validate_workspace_id

    try:
        return validate_workspace_id(workspace_id)
    except WorkspaceValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _to_workspace_info(summary: WorkspaceSummary) -> WorkspaceInfo:
    """Convert a workspace summary to the API model.

    :param summary: Workspace summary returned by the backend.
    :type summary: WorkspaceSummary
    :return: Workspace information for the API response.
    :rtype: WorkspaceInfo
    """
    return WorkspaceInfo(
        id=summary.workspace_id,
        name=summary.name,
        environment=summary.environment,
        path=summary.path,
    )


def _load_workspaces_from_directory() -> List[WorkspaceInfo]:
    """Load workspaces through the injected backend.

    The name is retained for sibling route modules that already import it.

    :return: Workspace information returned by the configured backend.
    :rtype: List[WorkspaceInfo]
    """
    return [_to_workspace_info(summary) for summary in get_workspace_reader().list_workspaces()]


@router.get("", response_model=WorkspaceListResponse)
async def list_workspaces() -> WorkspaceListResponse:
    """List all available workspaces.

    :return: Available workspaces and their total count.
    :rtype: WorkspaceListResponse
    :raises HTTPException: If the backend is unavailable or not initialized.
    """
    try:
        workspaces = _load_workspaces_from_directory()
    except HTTPException:
        raise
    except WorkspaceBackendError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return WorkspaceListResponse(workspaces=workspaces, total=len(workspaces))


@router.get("/{workspace_id}", response_model=WorkspaceInfo)
async def get_workspace(workspace_id: str) -> WorkspaceInfo:
    """Get a specific workspace.

    :param workspace_id: Identifier of the workspace to retrieve.
    :type workspace_id: str
    :return: Requested workspace information.
    :rtype: WorkspaceInfo
    :raises HTTPException: If validation fails, the workspace does not exist,
        its configuration is invalid, or the backend is unavailable.
    """
    validated_workspace_id = _validate_workspace_id_http(workspace_id)

    try:
        config = get_workspace_reader().get_workspace_config(validated_workspace_id)
    except WorkspaceValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except WorkspaceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except WorkspaceConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except WorkspaceBackendError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return WorkspaceInfo(
        id=config.workspace_id,
        name=config.sap_sid or config.workspace_id,
        environment=(config.workspace_id.split("-")[0] if "-" in config.workspace_id else ""),
        path=config.path,
    )
