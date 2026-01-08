# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Semantic Kernel plugin for job management and tracking.

This plugin provides LLM-callable tools for querying job status,
history, and management. This enables the LLM to autonomously
check on running jobs without hardcoded methods in agents.

Design Philosophy:
- All job queries go through @kernel_function tools
- LLM decides when to check job status (autonomous)
- No hardcoded methods in agents that bypass LLM reasoning
"""

from __future__ import annotations
import json
from typing import Annotated, Optional, TYPE_CHECKING
from semantic_kernel.functions import kernel_function
from src.agents.observability import get_logger

if TYPE_CHECKING:
    from src.agents.execution import JobStore

logger = get_logger(__name__)


class JobManagementPlugin:
    """Semantic Kernel plugin for job tracking and management.

    Provides tools for the LLM to query job status, check active jobs,
    and retrieve job history. All operations are read-only.
    """

    def __init__(self, job_store: Optional["JobStore"] = None) -> None:
        """Initialize JobManagementPlugin.

        :param job_store: JobStore for job persistence
        :type job_store: Optional[JobStore]
        """
        self.job_store = job_store
        logger.info(f"JobManagementPlugin initialized (job_store={job_store is not None})")

    @kernel_function(
        name="get_job_status",
        description="Get the current status of a specific job by ID. "
        "Returns job status, progress, current step, and any errors.",
    )
    def get_job_status(
        self,
        job_id: Annotated[str, "The unique job ID to check"],
    ) -> Annotated[str, "JSON string with job status details"]:
        """Get status of a specific job.

        :param job_id: Job ID to check
        :type job_id: str
        :returns: JSON string with job status
        :rtype: str
        """
        if not self.job_store:
            return json.dumps({"error": "Job tracking not enabled"})

        job = self.job_store.get_job(job_id)
        if not job:
            return json.dumps({"error": f"Job '{job_id}' not found"})

        return json.dumps(
            {
                "job_id": str(job.id),
                "status": job.status.value,
                "progress_percent": job.progress_percent,
                "current_step": job.current_step,
                "current_step_index": job.current_step_index,
                "total_steps": job.total_steps,
                "workspace_id": job.workspace_id,
                "test_group": job.test_group,
                "test_ids": job.test_ids,
                "created_at": job.created_at.isoformat() if job.created_at else None,
                "started_at": job.started_at.isoformat() if job.started_at else None,
                "completed_at": job.completed_at.isoformat() if job.completed_at else None,
                "error_message": job.error_message,
            },
            indent=2,
        )

    @kernel_function(
        name="get_active_job_for_workspace",
        description="Check if there's an active (running) job for a specific workspace. "
        "Use this before starting a new test to avoid conflicts.",
    )
    def get_active_job_for_workspace(
        self,
        workspace_id: Annotated[str, "Workspace ID to check for active jobs"],
    ) -> Annotated[str, "JSON string with active job info or null if none"]:
        """Get active job for a workspace.

        :param workspace_id: Workspace ID to check
        :type workspace_id: str
        :returns: JSON string with active job info
        :rtype: str
        """
        if not self.job_store:
            return json.dumps({"error": "Job tracking not enabled"})

        job = self.job_store.get_active_job_for_workspace(workspace_id)
        if not job:
            return json.dumps(
                {
                    "workspace_id": workspace_id,
                    "has_active_job": False,
                    "message": "No active jobs for this workspace",
                }
            )

        return json.dumps(
            {
                "workspace_id": workspace_id,
                "has_active_job": True,
                "job_id": str(job.id),
                "status": job.status.value,
                "progress_percent": job.progress_percent,
                "current_step": job.current_step,
                "test_group": job.test_group,
                "started_at": job.started_at.isoformat() if job.started_at else None,
            },
            indent=2,
        )

    @kernel_function(
        name="list_active_jobs",
        description="List all currently active (running or pending) jobs. "
        "Optionally filter by user ID.",
    )
    def list_active_jobs(
        self,
        user_id: Annotated[
            Optional[str],
            "Optional user ID to filter jobs by (if None, lists all active jobs)",
        ] = None,
    ) -> Annotated[str, "JSON string with list of active jobs"]:
        """List active jobs, optionally filtered by user.

        :param user_id: Optional user ID filter
        :type user_id: Optional[str]
        :returns: JSON string with active jobs list
        :rtype: str
        """
        if not self.job_store:
            return json.dumps({"error": "Job tracking not enabled"})

        if user_id:
            jobs = self.job_store.get_active_jobs(user_id)
        else:
            jobs = self.job_store.get_active_jobs()

        job_list = []
        for job in jobs:
            job_list.append(
                {
                    "job_id": str(job.id),
                    "workspace_id": job.workspace_id,
                    "status": job.status.value,
                    "progress_percent": job.progress_percent,
                    "test_group": job.test_group,
                    "started_at": job.started_at.isoformat() if job.started_at else None,
                }
            )

        return json.dumps(
            {
                "active_jobs": job_list,
                "count": len(job_list),
                "filter": {"user_id": user_id} if user_id else None,
            },
            indent=2,
        )

    @kernel_function(
        name="get_recent_job_events",
        description="Get recent events for a specific job. "
        "Useful for checking detailed progress and activity on a job.",
    )
    def get_recent_job_events(
        self,
        job_id: Annotated[str, "Job ID to get recent events for"],
        limit: Annotated[int, "Maximum number of events to return (default 10)"] = 10,
    ) -> Annotated[str, "JSON string with recent job events"]:
        """Get recent events for a job.

        :param job_id: Job ID
        :type job_id: str
        :param limit: Max events to return
        :type limit: int
        :returns: JSON string with job events
        :rtype: str
        """
        if not self.job_store:
            return json.dumps({"error": "Job tracking not enabled"})

        job = self.job_store.get_job(job_id)
        if not job:
            return json.dumps({"error": f"Job '{job_id}' not found"})

        # Get recent events from job
        events = job.events[-limit:] if len(job.events) > limit else job.events
        event_list = [event.to_dict() for event in events]

        return json.dumps(
            {
                "job_id": str(job.id),
                "workspace_id": job.workspace_id,
                "status": job.status.value,
                "test_group": job.test_group,
                "test_ids": job.test_ids,
                "recent_events": event_list,
                "count": len(event_list),
            },
            indent=2,
        )

    @kernel_function(
        name="get_job_events",
        description="Get the event log for a specific job. "
        "Shows detailed progress including each step and any errors.",
    )
    def get_job_events(
        self,
        job_id: Annotated[str, "Job ID to get events for"],
        limit: Annotated[int, "Maximum number of events to return (default 50)"] = 50,
    ) -> Annotated[str, "JSON string with job events"]:
        """Get event log for a job.

        :param job_id: Job ID
        :type job_id: str
        :param limit: Max events to return
        :type limit: int
        :returns: JSON string with events
        :rtype: str
        """
        if not self.job_store:
            return json.dumps({"error": "Job tracking not enabled"})

        job = self.job_store.get_job(job_id)
        if not job:
            return json.dumps({"error": f"Job '{job_id}' not found"})

        events = job.events[-limit:] if len(job.events) > limit else job.events
        event_list = [event.to_dict() for event in events]

        return json.dumps(
            {
                "job_id": str(job.id),
                "status": job.status.value,
                "events": event_list,
                "total_events": len(job.events),
                "showing": len(event_list),
            },
            indent=2,
        )
