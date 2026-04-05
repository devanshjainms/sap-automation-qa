# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for CBR Extract — deterministic pattern extraction."""

from __future__ import annotations

import pytest

from src.agents.cbr import CbrExtract, InvestigationOutcome
from src.core.models.failure import FailureClass, Severity
from src.core.models.knowledge import ExperienceEntry, LearnedPattern
from src.core.models.triage import TriageFinding, TriageReport, TriageSession

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _finding(
    title: str = "Fencing not triggered",
    severity: Severity = Severity.HIGH,
) -> TriageFinding:
    return TriageFinding(
        finding_id="F-001",
        severity=severity,
        title=title,
        description="SBD device timed out",
        failure_class=FailureClass.FENCING_NOT_TRIGGERED,
        remediation=["Configure SBD timeout"],
    )


def _report(findings: list[TriageFinding] | None = None) -> TriageReport:
    return TriageReport(
        session_id="sess-001",
        workspace_id="PRD-01",
        findings=[_finding()] if findings is None else findings,
        summary="Fencing misconfiguration detected",
        evidence_count=5,
        rules_evaluated=100,
        duration_seconds=10.0,
    )


# ---------------------------------------------------------------------------
# CbrExtract
# ---------------------------------------------------------------------------


class TestCbrExtract:
    def test_extract_with_query(self):
        pattern = CbrExtract.extract(_report(), query="Why did fencing fail?")
        assert pattern.name == "Why did fencing fail?"
        assert "Fencing not triggered" in pattern.symptoms
        assert "Configure SBD timeout" in pattern.fixes
        assert pattern.source == "learned"
        assert pattern.source_sessions == ["sess-001"]

    def test_extract_no_query_uses_session_id(self):
        pattern = CbrExtract.extract(_report())
        assert pattern.name.startswith("Session sess")

    def test_extract_empty_report(self):
        pattern = CbrExtract.extract(_report(findings=[]))
        assert pattern.symptoms == []
        assert pattern.fixes == []

    def test_extract_category_from_findings(self):
        pattern = CbrExtract.extract(_report())
        assert "fencing" in pattern.category.lower()

    def test_extract_deduplicates_fixes(self):
        f1 = _finding(title="A")
        f2 = _finding(title="B")
        report = _report(findings=[f1, f2])
        pattern = CbrExtract.extract(report)
        assert pattern.fixes == ["Configure SBD timeout"]

    def test_extract_returns_learned_pattern(self):
        pattern = CbrExtract.extract(_report())
        assert isinstance(pattern, LearnedPattern)
        assert pattern.id.startswith("LP-")


# ---------------------------------------------------------------------------
# InvestigationOutcome
# ---------------------------------------------------------------------------


class TestInvestigationOutcome:
    def test_values(self):
        assert InvestigationOutcome.CORRECT.value == "correct"
        assert InvestigationOutcome.PARTIAL.value == "partial"
        assert InvestigationOutcome.INCORRECT.value == "incorrect"

    def test_parse_valid(self):
        assert InvestigationOutcome("correct") == InvestigationOutcome.CORRECT
        assert InvestigationOutcome("partial") == InvestigationOutcome.PARTIAL
        assert InvestigationOutcome("incorrect") == InvestigationOutcome.INCORRECT

    def test_parse_invalid_raises(self):
        with pytest.raises(ValueError):
            InvestigationOutcome("invalid")


# ---------------------------------------------------------------------------
# build_experience
# ---------------------------------------------------------------------------


def _session_with_report() -> TriageSession:
    """Build a TriageSession with a completed report."""
    session = TriageSession(workspace_id="PRD-01")
    session.start_collection()
    session.complete_collection([])
    report = _report()
    session.complete_analysis(report)
    return session


class TestBuildExperience:
    def test_correct_outcome(self):
        session = _session_with_report()
        exp = CbrExtract.build_experience(
            session=session,
            outcome=InvestigationOutcome.CORRECT,
            root_cause_found=True,
        )
        assert isinstance(exp, ExperienceEntry)
        assert exp.session_id == str(session.id)
        assert exp.system_id == "PRD-01"
        assert exp.trigger == "agent_investigation"
        assert exp.resolution_applied is True
        assert exp.operator_feedback == "correct"
        assert exp.root_cause_found is True

    def test_partial_outcome(self):
        session = _session_with_report()
        exp = CbrExtract.build_experience(
            session=session,
            outcome=InvestigationOutcome.PARTIAL,
        )
        assert exp.resolution_applied is False
        assert exp.operator_feedback == "partial"
        assert exp.root_cause_found is False

    def test_incorrect_outcome(self):
        session = _session_with_report()
        exp = CbrExtract.build_experience(
            session=session,
            outcome=InvestigationOutcome.INCORRECT,
        )
        assert exp.resolution_applied is False
        assert exp.operator_feedback == "incorrect"

    def test_no_report(self):
        session = TriageSession(workspace_id="DEV-01")
        exp = CbrExtract.build_experience(
            session=session,
            outcome=InvestigationOutcome.CORRECT,
        )
        assert exp.duration_seconds == 0.0
        assert exp.rules_fired == 0
        assert exp.rules_failed == 0

    def test_report_fields_propagated(self):
        session = _session_with_report()
        exp = CbrExtract.build_experience(
            session=session,
            outcome=InvestigationOutcome.CORRECT,
        )
        report = session.report
        assert exp.duration_seconds == report.duration_seconds
        assert exp.rules_fired == report.rules_evaluated
        assert exp.rules_failed == report.finding_count
