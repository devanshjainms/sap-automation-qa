# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Jobs API routes — thin adapter over ``JobApplicationService`` (P1-WP-005B)."""

from pathlib import Path
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse
from src.core.execution.exceptions import WorkspaceLockError
from src.core.models.job import (
    CancelJobRequest,
    CancelJobResponse,
    CreateJobRequest,
    Job,
    JobEventsResponse,
    JobListResponse,
)
from src.core.observability import get_logger
from src.core.services.job_service import JobApplicationService

logger = get_logger(__name__)
router = APIRouter(prefix="/jobs", tags=["jobs"])
_job_service: Optional[JobApplicationService] = None


def set_job_service(service: Optional[JobApplicationService]) -> None:
    """Set the job application service instance.

    :param service: Application service, or ``None`` to clear it.
    :type service: Optional[JobApplicationService]
    """
    global _job_service
    _job_service = service


def get_job_service() -> JobApplicationService:
    """Get the job application service instance.

    :returns: The configured service.
    :rtype: JobApplicationService
    :raises HTTPException: If service not initialized (503 error).
    """
    if _job_service is None:
        raise HTTPException(status_code=503, detail="Job service not initialized")
    return _job_service


@router.get("", response_model=JobListResponse)
async def list_jobs(
    workspace_id: Optional[str] = Query(None, description="Filter by workspace"),
    status: Optional[str] = Query(None, description="Filter by status"),
    active_only: bool = Query(False, description="Only show active jobs"),
    limit: int = Query(50, ge=1, le=200, description="Maximum results"),
) -> JobListResponse:
    """List execution jobs.

    :param workspace_id: Filter jobs by workspace ID.
    :type workspace_id: Optional[str]
    :param status: Filter jobs by status.
    :type status: Optional[str]
    :param active_only: If True, only return active (non-terminal) jobs.
    :type active_only: bool
    :param limit: Maximum number of jobs to return.
    :type limit: int
    :returns: Response containing list of jobs and total count.
    :rtype: JobListResponse
    """
    svc = get_job_service()
    try:
        return svc.list_jobs(
            workspace_id=workspace_id,
            status=status,
            active_only=active_only,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{job_id}", response_model=Job)
async def get_job(job_id: str) -> Job:
    """Get a specific job by ID.

    :param job_id: Unique identifier of the job.
    :type job_id: str
    :returns: The requested job.
    :rtype: Job
    :raises HTTPException: If job not found (404 error).
    """
    job = get_job_service().get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return job


@router.post("", response_model=Job, status_code=201)
async def create_job(request: CreateJobRequest) -> Job:
    """Create and submit a new job.

    :param request: Job creation request with workspace and test details.
    :type request: CreateJobRequest
    :returns: The created and submitted job.
    :rtype: Job
    :raises HTTPException: 404 if workspace not found, 400 on invalid test_group
        or ineligible offline execution, and 409 if the workspace is active.
    """
    svc = get_job_service()
    try:
        return await svc.submit_job(request)
    except ValueError as exc:
        detail = str(exc)
        code = 404 if "not found" in detail else 400
        raise HTTPException(status_code=code, detail=detail) from exc
    except WorkspaceLockError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{job_id}/cancel", response_model=CancelJobResponse)
async def cancel_job(job_id: str, request: CancelJobRequest) -> CancelJobResponse:
    """Cancel a running job.

    :param job_id: ID of the job to cancel.
    :type job_id: str
    :param request: Cancellation request with optional reason.
    :type request: CancelJobRequest
    :returns: Cancellation confirmation.
    :rtype: CancelJobResponse
    :raises HTTPException: If job not found or not running (404 error).
    """
    success = await get_job_service().cancel_job(job_id, request.reason)
    if not success:
        raise HTTPException(
            status_code=404,
            detail=f"Job {job_id} not found or not running",
        )
    return CancelJobResponse(status="cancelled", job_id=job_id)


@router.get("/{job_id}/events", response_model=JobEventsResponse)
async def get_job_events(job_id: str) -> JobEventsResponse:
    """Get the events recorded for a job.

    :param job_id: Identifier of the job.
    :type job_id: str
    :return: Job identifier and persisted event records.
    :rtype: JobEventsResponse
    :raises HTTPException: If the job does not exist.
    """
    events = get_job_service().get_job_events(job_id)
    if events is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return JobEventsResponse(job_id=job_id, events=events)


@router.get("/{job_id}/log")
async def get_job_log(
    job_id: str,
    tail: Optional[int] = Query(
        None,
        ge=1,
        description="Return only the last N lines",
    ),
) -> PlainTextResponse:
    """Return the Ansible process log for a job.

    :param job_id: ID of the job.
    :type job_id: str
    :param tail: Optional: return only the last N lines.
    :type tail: Optional[int]
    :returns: Plain-text log content.
    :rtype: PlainTextResponse
    :raises HTTPException: 404 if job or log file not found.
    """
    job = get_job_service().get_job(job_id)
    if not job:
        raise HTTPException(
            status_code=404,
            detail=f"Job {job_id} not found",
        )

    if not job.log_file:
        raise HTTPException(
            status_code=404,
            detail=f"No log file recorded for job {job_id}",
        )

    log_path = Path(job.log_file)
    if not log_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Log file not found on disk: {log_path}",
        )

    try:
        content = log_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to read log: {exc}",
        ) from exc

    if tail is not None:
        lines = content.splitlines()
        content = "\n".join(lines[-tail:])

    return PlainTextResponse(content)
