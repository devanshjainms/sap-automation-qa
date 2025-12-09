# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Execution job models for async test execution.

This module defines the data structures for tracking asynchronous
test execution jobs, including status, progress, and events.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional
from uuid import UUID, uuid4


class JobStatus(str, Enum):
    """Status of an execution job."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobEventType(str, Enum):
    """Types of events that can occur during job execution."""

    STARTED = "started"
    PROGRESS = "progress"
    STEP_STARTED = "step_started"
    STEP_COMPLETED = "step_completed"
    STEP_FAILED = "step_failed"
    LOG = "log"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class JobEvent:
    """An event that occurred during job execution.

    Events are streamed to clients via SSE for real-time updates.
    """

    event_type: JobEventType
    message: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    step_index: Optional[int] = None
    total_steps: Optional[int] = None
    progress_percent: Optional[float] = None
    details: Optional[dict[str, Any]] = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "event_type": self.event_type.value,
            "message": self.message,
            "timestamp": self.timestamp.isoformat(),
            "step_index": self.step_index,
            "total_steps": self.total_steps,
            "progress_percent": self.progress_percent,
            "details": self.details,
        }


@dataclass
class ExecutionJob:
    """Represents an async test execution job.

    Jobs are created when a user requests test execution via chat,
    executed in the background, and their status is tracked for
    real-time updates.
    """

    id: UUID = field(default_factory=uuid4)
    conversation_id: Optional[str] = None
    user_id: Optional[str] = None
    workspace_id: str = ""
    test_id: Optional[str] = None
    test_group: Optional[str] = None
    test_ids: list[str] = field(default_factory=list)
    status: JobStatus = JobStatus.PENDING
    progress_percent: float = 0.0
    current_step: Optional[str] = None
    current_step_index: int = 0
    total_steps: int = 0
    created_at: datetime = field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    result: Optional[dict[str, Any]] = None
    error_message: Optional[str] = None
    events: list[JobEvent] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def add_event(self, event: JobEvent) -> None:
        """Add an event to the job history."""
        self.events.append(event)

    def start(self) -> JobEvent:
        """Mark job as started."""
        self.status = JobStatus.RUNNING
        self.started_at = datetime.utcnow()
        event = JobEvent(
            event_type=JobEventType.STARTED,
            message=f"Starting execution for workspace {self.workspace_id}",
            details={"workspace_id": self.workspace_id, "test_ids": self.test_ids},
        )
        self.add_event(event)
        return event

    def update_progress(
        self,
        step_index: int,
        total_steps: int,
        step_name: str,
        message: str,
    ) -> JobEvent:
        """Update job progress."""
        self.current_step_index = step_index
        self.total_steps = total_steps
        self.current_step = step_name
        self.progress_percent = (step_index / total_steps * 100) if total_steps > 0 else 0

        event = JobEvent(
            event_type=JobEventType.PROGRESS,
            message=message,
            step_index=step_index,
            total_steps=total_steps,
            progress_percent=self.progress_percent,
            details={"step_name": step_name},
        )
        self.add_event(event)
        return event

    def step_started(self, step_index: int, step_name: str, message: str) -> JobEvent:
        """Mark a step as started."""
        self.current_step = step_name
        self.current_step_index = step_index

        event = JobEvent(
            event_type=JobEventType.STEP_STARTED,
            message=message,
            step_index=step_index,
            total_steps=self.total_steps,
            details={"step_name": step_name},
        )
        self.add_event(event)
        return event

    def step_completed(self, step_index: int, step_name: str, message: str) -> JobEvent:
        """Mark a step as completed."""
        self.progress_percent = (
            ((step_index + 1) / self.total_steps * 100) if self.total_steps > 0 else 100
        )

        event = JobEvent(
            event_type=JobEventType.STEP_COMPLETED,
            message=message,
            step_index=step_index,
            total_steps=self.total_steps,
            progress_percent=self.progress_percent,
            details={"step_name": step_name},
        )
        self.add_event(event)
        return event

    def step_failed(self, step_index: int, step_name: str, error: str) -> JobEvent:
        """Mark a step as failed."""
        event = JobEvent(
            event_type=JobEventType.STEP_FAILED,
            message=f"Step '{step_name}' failed: {error}",
            step_index=step_index,
            total_steps=self.total_steps,
            details={"step_name": step_name, "error": error},
        )
        self.add_event(event)
        return event

    def log(self, message: str, details: Optional[dict[str, Any]] = None) -> JobEvent:
        """Add a log event."""
        event = JobEvent(
            event_type=JobEventType.LOG,
            message=message,
            details=details,
        )
        self.add_event(event)
        return event

    def complete(self, result: dict[str, Any], message: str = "Execution completed") -> JobEvent:
        """Mark job as completed successfully."""
        self.status = JobStatus.COMPLETED
        self.completed_at = datetime.utcnow()
        self.progress_percent = 100.0
        self.result = result

        event = JobEvent(
            event_type=JobEventType.COMPLETED,
            message=message,
            progress_percent=100.0,
            details={"result_summary": self._summarize_result(result)},
        )
        self.add_event(event)
        return event

    def fail(self, error: str) -> JobEvent:
        """Mark job as failed."""
        self.status = JobStatus.FAILED
        self.completed_at = datetime.utcnow()
        self.error_message = error

        event = JobEvent(
            event_type=JobEventType.FAILED,
            message=f"Execution failed: {error}",
            details={"error": error},
        )
        self.add_event(event)
        return event

    def cancel(self, reason: str = "Cancelled by user") -> JobEvent:
        """Mark job as cancelled."""
        self.status = JobStatus.CANCELLED
        self.completed_at = datetime.utcnow()
        self.error_message = reason

        event = JobEvent(
            event_type=JobEventType.CANCELLED,
            message=reason,
        )
        self.add_event(event)
        return event

    def _summarize_result(self, result: dict[str, Any]) -> dict[str, Any]:
        """Create a summary of the execution result."""
        return {
            "status": result.get("status", "unknown"),
            "tests_run": len(result.get("results", [])),
            "duration_seconds": (
                (self.completed_at - self.started_at).total_seconds()
                if self.completed_at and self.started_at
                else None
            ),
        }

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "id": str(self.id),
            "conversation_id": self.conversation_id,
            "user_id": self.user_id,
            "workspace_id": self.workspace_id,
            "test_id": self.test_id,
            "test_group": self.test_group,
            "test_ids": self.test_ids,
            "status": self.status.value,
            "progress_percent": self.progress_percent,
            "current_step": self.current_step,
            "current_step_index": self.current_step_index,
            "total_steps": self.total_steps,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "result": self.result,
            "error_message": self.error_message,
            "events": [e.to_dict() for e in self.events],
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExecutionJob":
        """Create ExecutionJob from dictionary."""
        job = cls(
            id=UUID(data["id"]) if isinstance(data["id"], str) else data["id"],
            conversation_id=data.get("conversation_id"),
            user_id=data.get("user_id"),
            workspace_id=data.get("workspace_id", ""),
            test_id=data.get("test_id"),
            test_group=data.get("test_group"),
            test_ids=data.get("test_ids", []),
            status=JobStatus(data.get("status", "pending")),
            progress_percent=data.get("progress_percent", 0.0),
            current_step=data.get("current_step"),
            current_step_index=data.get("current_step_index", 0),
            total_steps=data.get("total_steps", 0),
            created_at=(
                datetime.fromisoformat(data["created_at"])
                if data.get("created_at")
                else datetime.utcnow()
            ),
            started_at=(
                datetime.fromisoformat(data["started_at"]) if data.get("started_at") else None
            ),
            completed_at=(
                datetime.fromisoformat(data["completed_at"]) if data.get("completed_at") else None
            ),
            result=data.get("result"),
            error_message=data.get("error_message"),
            metadata=data.get("metadata", {}),
        )

        for event_data in data.get("events", []):
            job.events.append(
                JobEvent(
                    event_type=JobEventType(event_data["event_type"]),
                    message=event_data["message"],
                    timestamp=datetime.fromisoformat(event_data["timestamp"]),
                    step_index=event_data.get("step_index"),
                    total_steps=event_data.get("total_steps"),
                    progress_percent=event_data.get("progress_percent"),
                    details=event_data.get("details"),
                )
            )

        return job
