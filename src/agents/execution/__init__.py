# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Async execution infrastructure for SAP QA tests.

This package provides:
- Job models for tracking execution state (from models.job)
- Job storage for persistence
- Async worker for background execution
- Event streaming for real-time updates
- Custom exceptions for error handling
- Guard layer for safety constraints
"""

from src.agents.models.job import ExecutionJob, JobStatus, JobEvent, JobEventType
from src.agents.models.execution import GuardReason, GuardResult
from src.agents.execution.store import JobStore
from src.agents.execution.worker import JobWorker
from src.agents.execution.exceptions import (
    ExecutionError,
    WorkspaceLockError,
    JobNotFoundError,
    JobCancellationError,
)
from src.agents.execution.guards import (
    GuardLayer,
    GuardFilter,
)

__all__ = [
    "ExecutionJob",
    "JobStatus",
    "JobEvent",
    "JobEventType",
    "JobStore",
    "JobWorker",
    "ExecutionError",
    "WorkspaceLockError",
    "JobNotFoundError",
    "JobCancellationError",
    "GuardLayer",
    "GuardResult",
    "GuardReason",
    "GuardFilter",
]
