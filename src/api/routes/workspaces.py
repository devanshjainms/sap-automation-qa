# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""Workspaces API routes."""

from pathlib import Path
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from src.agents.workspace.workspace_store import WorkspaceStore
from src.agents.execution.store import JobStore
from src.agents.execution.worker import JobWorker
from src.agents.execution.exceptions import WorkspaceLockError
from src.agents.models.job import ExecutionJob
from src.agents.models.workspace import (
    WorkspaceMetadata,
    WorkspaceListResponse,
    WorkspaceDetailResponse,
    ReportInfo,
    ReportsListResponse,
    CreateWorkspaceRequest,
    FileContentResponse,
    UpdateFileContentRequest,
    TriggerTestExecutionRequest,
    TriggerTestExecutionResponse,
)
from src.agents.observability import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/workspaces", tags=["workspaces"])

_workspace_store: Optional[WorkspaceStore] = None
_job_store: Optional[JobStore] = None
_job_worker: Optional[JobWorker] = None


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


def set_job_store_for_workspaces(store: JobStore) -> None:
    """Set the job store instance for workspaces.

    :param store: JobStore instance to use
    :type store: JobStore
    """
    global _job_store
    _job_store = store
    logger.info("JobStore injected for workspaces router")


def set_job_worker_for_workspaces(worker: JobWorker) -> None:
    """Set the job worker instance for workspaces.

    :param worker: JobWorker instance to use
    :type worker: JobWorker
    """
    global _job_worker
    _job_worker = worker
    logger.info("JobWorker injected for workspaces router")


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
        if ".." in file_path or file_path.startswith("/"):
            raise HTTPException(status_code=400, detail="Invalid file path")

        qa_dir = workspace.path / "quality_assurance"
        full_path = qa_dir / file_path

        if not full_path.resolve().is_relative_to(qa_dir.resolve()):
            raise HTTPException(status_code=400, detail="Invalid file path")

        if not full_path.exists():
            raise HTTPException(status_code=404, detail=f"Report file not found: {file_path}")

        if not full_path.is_file():
            raise HTTPException(status_code=400, detail="Path is not a file")
        media_type_map = {
            ".html": "text/html",
        }
        media_type = media_type_map.get(full_path.suffix.lower(), "application/octet-stream")

        logger.info(f"Serving report file: {file_path} for workspace {workspace_id}")
        return FileResponse(
            path=str(full_path),
            media_type=media_type,
            headers={
                "Content-Disposition": "inline",
                "Cache-Control": "no-cache",
                "X-Content-Type-Options": "nosniff",
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to serve report file {file_path} for workspace {workspace_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to serve report file: {e}")


@router.post(
    "/{workspace_id}/execute", response_model=TriggerTestExecutionResponse, status_code=202
)
async def trigger_test_execution(
    workspace_id: str, request: TriggerTestExecutionRequest
) -> TriggerTestExecutionResponse:
    """Trigger test execution for a workspace using AnsibleRunner.

    Creates a background job and returns immediately with job ID.
    Use SSE endpoint /jobs/{job_id}/events to monitor real-time progress.

    :param workspace_id: Workspace ID (e.g., DEV-WEEU-SAP01-X00)
    :type workspace_id: str
    :param request: Test execution configuration
    :type request: TriggerTestExecutionRequest
    :returns: Job information with ID for tracking
    :rtype: TriggerTestExecutionResponse
    :raises HTTPException: 404 if workspace not found, 409 if workspace locked, 400 for invalid params
    """
    if not _job_store:
        raise HTTPException(status_code=503, detail="Job store not initialized")

    if not _job_worker:
        raise HTTPException(status_code=503, detail="Job worker not initialized")

    store = get_workspace_store()

    try:
        workspace = store.get_workspace(workspace_id)
        if not workspace:
            raise HTTPException(status_code=404, detail=f"Workspace '{workspace_id}' not found")
        valid_test_groups = ["HA_DB_HANA", "HA_SCS", "HA_OFFLINE", "CONFIG_CHECKS"]
        if request.test_group not in valid_test_groups:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid test_group '{request.test_group}'. "
                f"Valid groups: {', '.join(valid_test_groups)}",
            )
        hosts_file = workspace.path / "hosts.yaml"
        params_file = workspace.path / "sap-parameters.yaml"

        if not hosts_file.exists():
            raise HTTPException(
                status_code=422,
                detail=f"Workspace missing required file: hosts.yaml",
            )

        if not params_file.exists():
            raise HTTPException(
                status_code=422,
                detail=f"Workspace missing required file: sap-parameters.yaml",
            )
        if request.offline:
            offline_dir = workspace.path / "offline_validation"
            if not offline_dir.exists():
                raise HTTPException(
                    status_code=422,
                    detail="Offline mode requires CIB data in offline_validation directory. "
                    "Run online tests first to collect CIB data.",
                )
        test_ids = request.test_cases or []
        job = _job_store.create_job(
            workspace_id=workspace_id,
            test_ids=test_ids,
            test_group=request.test_group,
            metadata={
                "environment": workspace.env,
                "initiated_via": "workspace_trigger",
                "offline_mode": request.offline,
                "extra_vars": request.extra_vars or {},
            },
        )
        logger.info(
            f"Created job {job.id} for workspace {workspace_id}, "
            f"test_group={request.test_group}, test_ids={test_ids}"
        )
        try:
            await _job_worker.submit_job(job)
            logger.info(f"Submitted job {job.id} to background worker")
        except WorkspaceLockError as e:
            raise HTTPException(
                status_code=409,
                detail=f"Workspace {workspace_id} already has an active job. "
                f"Wait for job {e.active_job_id} to complete.",
            )

        return TriggerTestExecutionResponse(
            job_id=str(job.id),
            workspace_id=workspace_id,
            test_group=request.test_group,
            status=job.status.value,
            test_ids=test_ids,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to trigger test execution for workspace {workspace_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to trigger test execution: {str(e)}")
