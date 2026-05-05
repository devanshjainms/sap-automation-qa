# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Triage session models with state machine, request, finding, and report."""

from datetime import datetime
from enum import Enum
from typing import Any, Optional
from uuid import UUID, uuid4
from pydantic import BaseModel, ConfigDict, Field
from src.core.models.evidence import EvidenceArtifact
from src.core.models.failure import FailureClass, Severity
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
    ANALYSIS_STARTED = "analysis_started"
    ANALYSIS_COMPLETED = "analysis_completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TriageEvent(BaseModel):
    """Event emitted during a triage session lifecycle."""

    model_config = ConfigDict(use_enum_values=True)

    event_type: TriageEventType
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    message: str = ""
    data: Optional[dict[str, Any]] = None


class TriageRequest(BaseModel):
    """Request to start a triage session.

    :param workspace_id: Target SAP system workspace.
    :param system_properties: Properties of the target system for rule filtering.
    :param evidence_definitions: Specific evidence definition IDs to collect.
    :param query: Optional natural language description of the problem.
    """

    workspace_id: str
    system_properties: Optional[SystemProperties] = None
    evidence_definitions: list[str] = Field(default_factory=list)
    query: str = ""


class TriageFinding(BaseModel):
    """A single finding produced by the analyzer.

    :param finding_id: Unique identifier.
    :param failure_class: Classified failure type.
    :param severity: How critical this finding is.
    :param title: One-line summary.
    :param description: Detailed description of what was found.
    :param rule_id: Rule that produced this finding (if rule-based).
    :param playbook_id: Matched playbook (if any).
    :param validator_results: Individual rule evaluation outcomes.
    :param evidence_ids: IDs of evidence artifacts used.
    :param remediation: Suggested fix steps.
    :param references: Relevant SAP Notes, docs, etc.
    """

    model_config = ConfigDict(use_enum_values=True)

    finding_id: str
    failure_class: FailureClass = FailureClass.UNKNOWN
    severity: Severity = Severity.MEDIUM
    title: str = ""
    description: str = ""
    rule_id: Optional[str] = None
    playbook_id: Optional[str] = None
    validator_results: list[dict[str, Any]] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    remediation: list[str] = Field(default_factory=list)
    references: list[str] = Field(default_factory=list)


class TriageReport(BaseModel):
    """Complete triage report produced by the analyzer.

    :param session_id: Triage session this report belongs to.
    :param workspace_id: Workspace that was triaged.
    :param findings: List of findings.
    :param summary: Human-readable summary.
    :param evidence_count: Total evidence artifacts collected.
    :param rules_evaluated: Total rules evaluated.
    :param duration_seconds: Total triage duration.
    :param created_at: When the report was generated.
    """

    session_id: str
    workspace_id: str
    findings: list[TriageFinding] = Field(default_factory=list)
    summary: str = ""
    evidence_count: int = 0
    rules_evaluated: int = 0
    rules_passed: int = 0
    rules_skipped: int = 0
    duration_seconds: Optional[float] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def finding_count(self) -> int:
        """Number of findings in this report."""
        return len(self.findings)

    @property
    def has_critical(self) -> bool:
        """Whether any finding is CRITICAL severity."""
        return any(f.severity == Severity.CRITICAL for f in self.findings)


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
    :param report: Analysis report (set when analysis completes).
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
    report: Optional[TriageReport] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None
    events: list[TriageEvent] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def _transition(
        self, target: TriageStatus, event_type: TriageEventType, message: str = ""
    ) -> TriageEvent:
        """Perform a validated state transition.

        :param target: Target status.
        :param event_type: Event type to emit.
        :param message: Event message.
        :returns: The emitted event.
        :raises ValueError: If the transition is invalid.
        """
        current = TriageStatus(self.status)
        allowed = _VALID_TRANSITIONS.get(current, set())
        if target not in allowed:
            raise ValueError(f"Invalid transition: {current.value} → {target.value}")
        self.status = target
        event = TriageEvent(event_type=event_type, message=message)
        self.events.append(event)
        return event

    def start_collection(self) -> TriageEvent:
        """Transition to COLLECTING state.

        :returns: TriageEvent indicating collection has started.
        :rtype: TriageEvent
        :raises ValueError: If not in PENDING state.
        """
        self.started_at = datetime.utcnow()
        return self._transition(
            TriageStatus.COLLECTING,
            TriageEventType.COLLECTION_STARTED,
            "Evidence collection started",
        )

    def complete_collection(self, evidence: list[EvidenceArtifact]) -> TriageEvent:
        """Transition to ANALYZING state after evidence collection.

        :param evidence: Collected evidence artifacts.
        :type evidence: list[EvidenceArtifact]
        :returns: TriageEvent indicating collection completed.
        :rtype: TriageEvent
        :raises ValueError: If not in COLLECTING state.
        """
        self.evidence = [e.to_dict() for e in evidence]
        return self._transition(
            TriageStatus.ANALYZING,
            TriageEventType.COLLECTION_COMPLETED,
            f"Collected {len(evidence)} evidence artifacts",
        )

    def complete_analysis(self, report: TriageReport) -> TriageEvent:
        """Transition to COMPLETE state after analysis.

        :param report: Completed triage report.
        :type report: TriageReport
        :returns: TriageEvent indicating analysis completed.
        :rtype: TriageEvent
        :raises ValueError: If not in ANALYZING state.
        """
        self.report = report
        self.completed_at = datetime.utcnow()
        return self._transition(
            TriageStatus.COMPLETE,
            TriageEventType.ANALYSIS_COMPLETED,
            f"Analysis complete: {report.finding_count} findings",
        )

    def fail(self, error: str) -> TriageEvent:
        """Transition to FAILED state.

        :param error: Error message.
        :type error: str
        :returns: TriageEvent indicating failure.
        :rtype: TriageEvent
        :raises ValueError: If already in a terminal state.
        """
        self.completed_at = datetime.utcnow()
        self.error = error
        return self._transition(TriageStatus.FAILED, TriageEventType.FAILED, error)

    def cancel(self, reason: str = "Cancelled by user") -> TriageEvent:
        """Transition to CANCELLED state.

        :param reason: Cancellation reason.
        :type reason: str
        :returns: TriageEvent indicating cancellation.
        :rtype: TriageEvent
        :raises ValueError: If already in a terminal state.
        """
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
