# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Custom exceptions for the execution module.

This module defines domain-specific exceptions for job execution,
providing clear error semantics for callers.
"""

from typing import Optional


class ExecutionError(Exception):
    """Base exception for execution-related errors."""


class WorkspaceLockError(ExecutionError):
    """Raised when attempting to run a job on a workspace with an active job.

    Only one job can run per workspace at a time to prevent:
    - Resource conflicts on target SAP systems
    - Overlapping cluster operations that could cause issues
    - Ambiguous state tracking for concurrent jobs
    """

    def __init__(
        self,
        workspace_id: str,
        active_job_id: Optional[str] = None,
        message: Optional[str] = None,
    ) -> None:
        """Initialize WorkspaceLockError.

        :param workspace_id: The workspace that is locked
        :type workspace_id: str
        :param active_job_id: The ID of the currently running job
        :type active_job_id: Optional[str]
        :param message: Optional custom message
        :type message: Optional[str]
        """
        self.workspace_id = workspace_id
        self.active_job_id = active_job_id

        if message:
            self.message = message
        elif active_job_id:
            self.message = (
                f"Workspace '{workspace_id}' already has an active job "
                f"(job_id={active_job_id}). Only one job per workspace is allowed."
            )
        else:
            self.message = (
                f"Workspace '{workspace_id}' already has an active job. "
                "Only one job per workspace is allowed."
            )

        super().__init__(self.message)


class JobNotFoundError(ExecutionError):
    """Raised when a requested job does not exist."""

    def __init__(self, job_id: str) -> None:
        """Initialize JobNotFoundError.

        :param job_id: The job ID that was not found
        :type job_id: str
        """
        self.job_id = job_id
        self.message = f"Job '{job_id}' not found."
        super().__init__(self.message)


class JobCancellationError(ExecutionError):
    """Raised when a job cancellation fails."""

    def __init__(self, job_id: str, reason: str) -> None:
        """Initialize JobCancellationError.

        :param job_id: The job ID that could not be cancelled
        :type job_id: str
        :param reason: Reason for failure
        :type reason: str
        """
        self.job_id = job_id
        self.reason = reason
        self.message = f"Failed to cancel job '{job_id}': {reason}"
        super().__init__(self.message)
