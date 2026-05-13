# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Triage session models with state machine transitions."""

from datetime import datetime
from enum import Enum
from typing import Any, Optional
from uuid import UUID, uuid4
from pydantic import BaseModel, ConfigDict, Field
from src.core.models.evidence import EvidenceArtifact
from src.core.models.system import SystemProperties


class TriageStatus(str, Enum):
    """Status of a triage session."""

    PENDING = "pending"
    COLLECTING = "collecting"
    ANALYZING = "analyzing"
    COMPLETE = "complete"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TriageEventType(str, Enum):
    """Type of triage session event."""

    CREATED = "created"
    COLLECTION_STARTED = "collection_started"
    COLLECTION_COMPLETED = "collection_completed"
    ANALYSIS_COMPLETED = "analysis_completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TriageEvent(BaseModel):
    """Record of a triage session state change.

    :param event_type: Type of event.
    :param timestamp: When the event occurred.
    :param message: Human-readable description.
    """

    event_type: TriageEventType
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    message: str = ""


class TriageRequest(BaseModel):
    """Input parameters for starting a triage session.

    :param workspace_id: Target workspace to triage.
    :param system_properties: Optional system properties for rule filtering.
    :param evidence_definitions: Specific evidence definition IDs to collect.
    :param query: Optional natural language description of the problem.
    """

    workspace_id: str
    system_properties: Optional[SystemProperties] = None
    evidence_definitions: list[str] = Field(default_factory=list)
    query: str = ""


_VALID_TRANSITIONS: dict[TriageStatus, set[TriageStatus]] = {
    TriageStatus.PENDING: {
        TriageStatus.COLLECTING,
        TriageStatus.FAILED,
        TriageStatus.CANCELLED,
    },
    TriageStatus.COLLECTING: {
        TriageStatus.ANALYZING,
        TriageStatus.FAILED,
        TriageStatus.CANCELLED,
    },
    TriageStatus.ANALYZING: {
        TriageStatus.COMPLETE,
        TriageStatus.FAILED,
        TriageStatus.CANCELLED,
    },
    TriageStatus.COMPLETE: set(),
    TriageStatus.FAILED: set(),
    TriageStatus.CANCELLED: set(),
}


class TriageSession(BaseModel):
    """A triage session with explicit state machine transitions.

    :param id: Unique session identifier.
    :param workspace_id: Target SAP system workspace.
    :param status: Current session status.
    :param system_properties: Properties of the target system.
    :param query: Original user query.
    :param evidence: Collected evidence artifacts.
    :param created_at: When the session was created.
    :param started_at: When evidence collection started.
    :param completed_at: When the session reached a terminal state.
    :param error: Error message if session failed.
    :param events: Timeline of session events.
    :param metadata: Additional context.
    """

    model_config = ConfigDict(populate_by_name=True, use_enum_values=True)

    id: UUID = Field(default_factory=uuid4)
    workspace_id: str
    status: TriageStatus = TriageStatus.PENDING
    system_properties: Optional[SystemProperties] = None
    query: str = ""
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None
    events: list[TriageEvent] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def _transition(
        self, target: TriageStatus, event_type: TriageEventType, message: str = ""
    ) -> TriageEvent:
        """Perform a validated state transition."""
        current = TriageStatus(self.status)
        allowed = _VALID_TRANSITIONS.get(current, set())
        if target not in allowed:
            raise ValueError(f"Invalid transition: {current.value} → {target.value}")
        self.status = target
        event = TriageEvent(event_type=event_type, message=message)
        self.events.append(event)
        return event

    def start_collection(self) -> TriageEvent:
        """Transition to COLLECTING state."""
        self.started_at = datetime.utcnow()
        return self._transition(
            TriageStatus.COLLECTING,
            TriageEventType.COLLECTION_STARTED,
            "Evidence collection started",
        )

    def complete_collection(self, evidence: list[EvidenceArtifact]) -> TriageEvent:
        """Transition to ANALYZING state after evidence collection."""
        self.evidence = [e.to_dict() for e in evidence]
        return self._transition(
            TriageStatus.ANALYZING,
            TriageEventType.COLLECTION_COMPLETED,
            f"Collected {len(evidence)} evidence artifacts",
        )

    def complete(self) -> TriageEvent:
        """Transition to COMPLETE state."""
        self.completed_at = datetime.utcnow()
        return self._transition(
            TriageStatus.COMPLETE,
            TriageEventType.ANALYSIS_COMPLETED,
            "Triage complete",
        )

    def fail(self, error: str) -> TriageEvent:
        """Transition to FAILED state."""
        self.completed_at = datetime.utcnow()
        self.error = error
        return self._transition(TriageStatus.FAILED, TriageEventType.FAILED, error)

    def cancel(self, reason: str = "Cancelled by user") -> TriageEvent:
        """Transition to CANCELLED state."""
        self.completed_at = datetime.utcnow()
        self.error = reason
        return self._transition(TriageStatus.CANCELLED, TriageEventType.CANCELLED, reason)

    @property
    def is_terminal(self) -> bool:
        """Check if the session is in a terminal state."""
        return TriageStatus(self.status) in (
            TriageStatus.COMPLETE,
            TriageStatus.FAILED,
            TriageStatus.CANCELLED,
        )

    @property
    def duration_seconds(self) -> Optional[float]:
        """Calculate session duration in seconds."""
        if not self.started_at:
            return None
        end_time = self.completed_at or datetime.utcnow()
        return (end_time - self.started_at).total_seconds()
