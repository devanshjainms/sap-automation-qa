# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Jobs API routes for execution job management.

This module provides REST endpoints for:
- Listing execution jobs with filters
- Getting job details with full output
- Job management operations
"""

from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from src.agents.execution.store import JobStore
from src.agents.models.job import JobStatus
from src.agents.observability import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/jobs", tags=["jobs"])

_job_store: Optional[JobStore] = None


def set_job_store(store: JobStore) -> None:
    """Set the global job store instance.

    :param store: JobStore instance
    :type store: JobStore
    """
    global _job_store
    _job_store = store


def get_job_store() -> Optional[JobStore]:
    """Get the global job store instance."""
    return _job_store


class JobListItem(BaseModel):
    """Lightweight job item for list responses."""

    job_id: str
    workspace_id: str
    test_id: Optional[str] = None
    test_group: Optional[str] = None
    status: str
    target_node: Optional[str] = None
    created_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error_message: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class JobDetail(BaseModel):
    """Full job details including raw output."""

    job_id: str
    conversation_id: Optional[str] = None
    user_id: Optional[str] = None
    workspace_id: str
    test_id: Optional[str] = None
    test_group: Optional[str] = None
    test_ids: list[str] = Field(default_factory=list)
    status: str
    progress_percent: float = 0.0
    current_step: Optional[str] = None
    target_node: Optional[str] = None
    target_nodes: list[str] = Field(default_factory=list)
    created_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    raw_stdout: Optional[str] = None
    raw_stderr: Optional[str] = None
    result: Optional[dict[str, Any]] = None
    error_message: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class JobListResponse(BaseModel):
    """Response for job list endpoint."""

    jobs: list[JobListItem]
    total: int
    limit: int
    offset: int


@router.get("", response_model=JobListResponse)
async def list_jobs(
    workspace_id: Optional[str] = Query(None, description="Filter by workspace ID"),
    status: Optional[str] = Query(None, description="Filter by status"),
    conversation_id: Optional[str] = Query(None, description="Filter by conversation ID"),
    limit: int = Query(50, ge=1, le=200, description="Maximum results to return"),
    offset: int = Query(0, ge=0, description="Number of results to skip"),
) -> JobListResponse:
    """List execution jobs with optional filters.

    :param workspace_id: Optional workspace ID filter
    :param status: Optional status filter (pending, running, completed, failed, cancelled)
    :param conversation_id: Optional conversation ID filter
    :param limit: Maximum number of jobs to return
    :param offset: Pagination offset
    :returns: List of jobs with pagination info
    """
    if not _job_store:
        raise HTTPException(status_code=503, detail="Job store not initialized")

    try:
        job_status = JobStatus(status) if status else None
    except ValueError:
        job_status = None

    jobs = _job_store.get_job_history(
        workspace_id=workspace_id,
        status=job_status,
        limit=limit,
        offset=offset,
    )

    if conversation_id:
        jobs = [j for j in jobs if j.conversation_id == conversation_id]

    job_items = [
        JobListItem(
            job_id=str(job.id),
            workspace_id=job.workspace_id,
            test_id=job.test_id,
            test_group=job.test_group,
            status=job.status.value,
            target_node=job.target_node,
            created_at=job.created_at.isoformat(),
            started_at=job.started_at.isoformat() if job.started_at else None,
            completed_at=job.completed_at.isoformat() if job.completed_at else None,
            error_message=job.error_message,
            metadata=job.metadata,
        )
        for job in jobs
    ]
    total = len(job_items)

    logger.info(f"Listed {len(job_items)} jobs (workspace={workspace_id}, status={status})")

    return JobListResponse(
        jobs=job_items,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{job_id}", response_model=JobDetail)
async def get_job(job_id: str) -> JobDetail:
    """Get full job details including raw output.

    :param job_id: Job ID
    :returns: Full job details with raw stdout/stderr
    """
    if not _job_store:
        raise HTTPException(status_code=503, detail="Job store not initialized")

    try:
        job = _job_store.get_job(UUID(job_id))
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid job ID format")

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    logger.info(f"Retrieved job details for {job_id}")

    return JobDetail(
        job_id=str(job.id),
        conversation_id=job.conversation_id,
        user_id=job.user_id,
        workspace_id=job.workspace_id,
        test_id=job.test_id,
        test_group=job.test_group,
        test_ids=job.test_ids,
        status=job.status.value,
        progress_percent=job.progress_percent,
        current_step=job.current_step,
        target_node=job.target_node,
        target_nodes=job.target_nodes,
        created_at=job.created_at.isoformat(),
        started_at=job.started_at.isoformat() if job.started_at else None,
        completed_at=job.completed_at.isoformat() if job.completed_at else None,
        raw_stdout=job.raw_stdout,
        raw_stderr=job.raw_stderr,
        result=job.result,
        error_message=job.error_message,
        metadata=job.metadata,
    )


@router.get("/workspaces/list")
async def list_workspaces_with_jobs() -> list[str]:
    """Get list of workspace IDs that have jobs.

    Useful for populating workspace filter dropdown.

    :returns: List of unique workspace IDs
    """
    if not _job_store:
        raise HTTPException(status_code=503, detail="Job store not initialized")
    jobs = _job_store.get_job_history(limit=1000)
    workspace_ids = sorted(set(job.workspace_id for job in jobs if job.workspace_id))

    logger.info(f"Found {len(workspace_ids)} workspaces with jobs")

    return workspace_ids
