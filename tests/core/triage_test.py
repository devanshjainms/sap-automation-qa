# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for triage session state machine, request, finding, and report."""

import pytest
from src.core.models.evidence import (
    CollectionStatus,
    CollectorType,
    EvidenceArtifact,
    EvidenceType,
)
from src.core.models.failure import FailureClass, Severity
from src.core.models.system import SystemProperties
from src.core.models.triage import (
    TriageEvent,
    TriageEventType,
    TriageFinding,
    TriageReport,
    TriageRequest,
    TriageSession,
    TriageStatus,
)


class TestTriageStatus:
    """Unit tests for TriageStatus enum."""

    def test_known_members(self) -> None:
        """Verify expected statuses exist."""
        expected = {
            "pending",
            "collecting",
            "analyzing",
            "complete",
            "failed",
            "cancelled",
        }
        actual = {m.value for m in TriageStatus}
        assert actual == expected


class TestTriageRequest:
    """Unit tests for TriageRequest model."""

    def test_create_minimal(self) -> None:
        """Verify minimal request creation."""
        req = TriageRequest(workspace_id="WS-001")
        assert req.workspace_id == "WS-001"
        assert req.query == ""
        assert req.evidence_definitions == []

    def test_create_full(self) -> None:
        """Verify full request creation."""
        req = TriageRequest(
            workspace_id="WS-001",
            system_properties=SystemProperties(database_type="HANA", ha_enabled=True),
            evidence_definitions=["DEF-001", "DEF-002"],
            query="Why is HANA down?",
        )
        assert req.query == "Why is HANA down?"
        assert len(req.evidence_definitions) == 2


class TestTriageFinding:
    """Unit tests for TriageFinding model."""

    def test_create(self) -> None:
        """Verify finding creation."""
        finding = TriageFinding(
            finding_id="F-001",
            failure_class=FailureClass.HSR_TAKEOVER_FAILURE,
            severity=Severity.CRITICAL,
            title="HANA takeover did not occur",
            rule_id="DB-HANA-0001",
            remediation=["Set PREFER_SITE_TAKEOVER = true"],
        )
        assert finding.severity == Severity.CRITICAL.value
        assert len(finding.remediation) == 1

    def test_defaults(self) -> None:
        """Verify finding defaults."""
        finding = TriageFinding(finding_id="F-002")
        assert finding.failure_class == FailureClass.UNKNOWN.value
        assert finding.severity == Severity.MEDIUM.value
        assert finding.validator_results == []
        assert finding.evidence_ids == []


class TestTriageReport:
    """Unit tests for TriageReport model."""

    def test_create_empty(self) -> None:
        """Verify empty report creation."""
        report = TriageReport(session_id="S-001", workspace_id="WS-001")
        assert report.finding_count == 0
        assert report.has_critical is False

    def test_finding_count(self) -> None:
        """Verify finding_count property."""
        report = TriageReport(
            session_id="S-001",
            workspace_id="WS-001",
            findings=[
                TriageFinding(finding_id="F-001"),
                TriageFinding(finding_id="F-002"),
            ],
        )
        assert report.finding_count == 2

    def test_has_critical(self) -> None:
        """Verify has_critical detects CRITICAL findings."""
        report = TriageReport(
            session_id="S-001",
            workspace_id="WS-001",
            findings=[
                TriageFinding(
                    finding_id="F-001",
                    severity=Severity.CRITICAL,
                ),
            ],
        )
        assert report.has_critical is True

    def test_no_critical(self) -> None:
        """Verify has_critical is False when no CRITICAL findings."""
        report = TriageReport(
            session_id="S-001",
            workspace_id="WS-001",
            findings=[
                TriageFinding(finding_id="F-001", severity=Severity.LOW),
            ],
        )
        assert report.has_critical is False


class TestTriageSession:
    """Unit tests for TriageSession state machine."""

    def _make_session(self) -> TriageSession:
        """Create a session for testing."""
        return TriageSession(workspace_id="WS-001")

    def _make_evidence(self) -> list[EvidenceArtifact]:
        """Create sample evidence artifacts."""
        return [
            EvidenceArtifact(
                evidence_id="EV-001",
                evidence_type=EvidenceType.COMMAND_OUTPUT,
                collector_type=CollectorType.SSH,
                status=CollectionStatus.SUCCESS,
                host="node1",
                command="crm_mon -1",
                content="<xml/>",
            ),
        ]

    def _make_report(self, session_id: str) -> TriageReport:
        """Create a sample report."""
        return TriageReport(
            session_id=session_id,
            workspace_id="WS-001",
            findings=[TriageFinding(finding_id="F-001")],
        )

    def test_defaults(self) -> None:
        """Verify new session has correct defaults."""
        session = self._make_session()
        assert session.status == TriageStatus.PENDING.value
        assert session.id is not None
        assert session.started_at is None
        assert session.events == []
        assert not session.is_terminal

    def test_start_collection(self) -> None:
        """Verify start_collection transitions to COLLECTING."""
        session = self._make_session()
        event = session.start_collection()
        assert event.event_type == TriageEventType.COLLECTION_STARTED.value
        assert session.status == TriageStatus.COLLECTING.value
        assert session.started_at is not None
        assert not session.is_terminal

    def test_complete_collection(self) -> None:
        """Verify complete_collection transitions to ANALYZING."""
        session = self._make_session()
        session.start_collection()
        evidence = self._make_evidence()
        event = session.complete_collection(evidence)
        assert event.event_type == TriageEventType.COLLECTION_COMPLETED.value
        assert session.status == TriageStatus.ANALYZING.value
        assert len(session.evidence) == 1

    def test_complete_analysis(self) -> None:
        """Verify complete_analysis transitions to COMPLETE."""
        session = self._make_session()
        session.start_collection()
        session.complete_collection(self._make_evidence())
        report = self._make_report(str(session.id))
        event = session.complete_analysis(report)
        assert event.event_type == TriageEventType.ANALYSIS_COMPLETED.value
        assert session.status == TriageStatus.COMPLETE.value
        assert session.is_terminal
        assert session.report is not None
        assert session.completed_at is not None

    def test_fail_from_pending(self) -> None:
        """Verify fail transitions from PENDING."""
        session = self._make_session()
        event = session.fail("workspace not found")
        assert event.event_type == TriageEventType.FAILED.value
        assert session.status == TriageStatus.FAILED.value
        assert session.is_terminal
        assert session.error == "workspace not found"

    def test_fail_from_collecting(self) -> None:
        """Verify fail transitions from COLLECTING."""
        session = self._make_session()
        session.start_collection()
        event = session.fail("SSH timeout")
        assert session.status == TriageStatus.FAILED.value
        assert session.is_terminal

    def test_fail_from_analyzing(self) -> None:
        """Verify fail transitions from ANALYZING."""
        session = self._make_session()
        session.start_collection()
        session.complete_collection(self._make_evidence())
        event = session.fail("analyzer error")
        assert session.status == TriageStatus.FAILED.value

    def test_cancel_from_pending(self) -> None:
        """Verify cancel transitions from PENDING."""
        session = self._make_session()
        event = session.cancel("user request")
        assert event.event_type == TriageEventType.CANCELLED.value
        assert session.status == TriageStatus.CANCELLED.value
        assert session.is_terminal

    def test_cancel_from_collecting(self) -> None:
        """Verify cancel transitions from COLLECTING."""
        session = self._make_session()
        session.start_collection()
        session.cancel()
        assert session.status == TriageStatus.CANCELLED.value

    def test_cancel_from_analyzing(self) -> None:
        """Verify cancel transitions from ANALYZING."""
        session = self._make_session()
        session.start_collection()
        session.complete_collection(self._make_evidence())
        session.cancel()
        assert session.status == TriageStatus.CANCELLED.value

    def test_invalid_transition_collecting_from_analyzing(self) -> None:
        """Verify ANALYZING → COLLECTING is rejected."""
        session = self._make_session()
        session.start_collection()
        session.complete_collection(self._make_evidence())
        with pytest.raises(ValueError, match="Invalid transition"):
            session.start_collection()

    def test_invalid_transition_from_complete(self) -> None:
        """Verify no transitions from COMPLETE."""
        session = self._make_session()
        session.start_collection()
        session.complete_collection(self._make_evidence())
        session.complete_analysis(self._make_report(str(session.id)))
        with pytest.raises(ValueError, match="Invalid transition"):
            session.fail("nope")

    def test_invalid_transition_from_failed(self) -> None:
        """Verify no transitions from FAILED."""
        session = self._make_session()
        session.fail("err")
        with pytest.raises(ValueError, match="Invalid transition"):
            session.cancel()

    def test_invalid_transition_from_cancelled(self) -> None:
        """Verify no transitions from CANCELLED."""
        session = self._make_session()
        session.cancel()
        with pytest.raises(ValueError, match="Invalid transition"):
            session.start_collection()

    def test_invalid_double_start(self) -> None:
        """Verify COLLECTING → COLLECTING is rejected."""
        session = self._make_session()
        session.start_collection()
        with pytest.raises(ValueError, match="Invalid transition"):
            session.start_collection()

    @pytest.mark.parametrize(
        "status,terminal",
        [
            (TriageStatus.PENDING, False),
            (TriageStatus.COLLECTING, False),
            (TriageStatus.ANALYZING, False),
            (TriageStatus.COMPLETE, True),
            (TriageStatus.FAILED, True),
            (TriageStatus.CANCELLED, True),
        ],
    )
    def test_is_terminal(self, status: TriageStatus, terminal: bool) -> None:
        """Verify is_terminal property for each status."""
        session = TriageSession(workspace_id="WS", status=status)
        assert session.is_terminal == terminal

    def test_duration_none_when_not_started(self) -> None:
        """Verify duration_seconds is None for unstarted sessions."""
        session = self._make_session()
        assert session.duration_seconds is None

    def test_duration_calculated(self) -> None:
        """Verify duration_seconds is calculated for completed sessions."""
        session = self._make_session()
        session.start_collection()
        session.complete_collection(self._make_evidence())
        session.complete_analysis(self._make_report(str(session.id)))
        duration = session.duration_seconds
        assert duration is not None
        assert duration >= 0

    def test_events_accumulate(self) -> None:
        """Verify events list accumulates through transitions."""
        session = self._make_session()
        session.start_collection()
        session.complete_collection(self._make_evidence())
        session.complete_analysis(self._make_report(str(session.id)))
        assert len(session.events) == 3
        types = [e.event_type for e in session.events]
        assert types == [
            TriageEventType.COLLECTION_STARTED.value,
            TriageEventType.COLLECTION_COMPLETED.value,
            TriageEventType.ANALYSIS_COMPLETED.value,
        ]

    def test_json_roundtrip(self) -> None:
        """Verify session serializes and deserializes via JSON."""
        session = self._make_session()
        data = session.model_dump()
        restored = TriageSession(**data)
        assert str(restored.id) == str(session.id)
        assert restored.workspace_id == session.workspace_id

    def test_metadata(self) -> None:
        """Verify metadata field works."""
        session = TriageSession(
            workspace_id="WS-001",
            metadata={"source": "chat", "conversation_id": "conv-1"},
        )
        assert session.metadata["source"] == "chat"
