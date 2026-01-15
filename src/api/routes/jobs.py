# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Jobs API routes for execution job management.

This module provides REST endpoints for:
- Listing execution jobs with filters
- Getting job details with full output
- Job management operations
"""

from typing import Optional
from uuid import UUID
from fastapi import APIRouter, HTTPException, Query
from src.agents.execution.store import JobStore
from src.agents.models.job import ExecutionJob, JobStatus, JobListResponse
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


@router.get("", response_model=JobListResponse)
async def list_jobs(
    workspace_id: Optional[str] = Query(None, description="Filter by workspace ID"),
    status: Optional[str] = Query(None, description="Filter by status"),
    conversation_id: Optional[str] = Query(None, description="Filter by conversation ID"),
    limit: int = Query(50, ge=1, le=1000, description="Maximum results to return"),
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

    total = len(jobs)

    logger.info(f"Listed {len(jobs)} jobs (workspace={workspace_id}, status={status})")

    return JobListResponse(
        jobs=jobs,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{job_id}", response_model=ExecutionJob)
async def get_job(job_id: str) -> ExecutionJob:
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

    return job


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
