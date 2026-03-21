# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for CBR Extract — deterministic pattern extraction."""

from __future__ import annotations

import pytest

from src.agents.cbr import CbrExtract
from src.core.models.failure import FailureClass, Severity
from src.core.models.knowledge import LearnedPattern
from src.core.models.triage import TriageFinding, TriageReport

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
