# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for ReportFormatter — structured findings to Markdown."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.agents.formatter import ReportFormatter
from src.core.models.failure import FailureClass, Severity
from src.core.models.triage import TriageFinding, TriageReport

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _finding(
    severity: Severity = Severity.HIGH,
    title: str = "Test finding",
    description: str = "Something went wrong",
    failure_class: FailureClass = FailureClass.FENCING_NOT_TRIGGERED,
    remediation: list[str] | None = None,
    references: list[str] | None = None,
) -> TriageFinding:
    return TriageFinding(
        finding_id="F-001",
        severity=severity,
        title=title,
        description=description,
        failure_class=failure_class,
        remediation=remediation or ["Fix step 1"],
        references=references or ["SAP Note 123"],
    )


def _report(
    findings: list[TriageFinding] | None = None,
    workspace_id: str = "PRD-01",
) -> TriageReport:
    return TriageReport(
        session_id="sess-001",
        workspace_id=workspace_id,
        findings=findings or [],
        summary="Test summary",
        evidence_count=5,
        rules_evaluated=100,
        duration_seconds=12.5,
    )


# ---------------------------------------------------------------------------
# Deterministic formatting
# ---------------------------------------------------------------------------


class TestDeterministicFormat:
    def test_empty_report(self):
        fmt = ReportFormatter()
        md = fmt.format(_report())
        assert "No findings" in md
        assert "PRD-01" in md

    def test_single_finding(self):
        fmt = ReportFormatter()
        md = fmt.format(_report(findings=[_finding()]))
        assert "Test finding" in md
        assert "HIGH" in md
        assert "Fix step 1" in md
        assert "SAP Note 123" in md

    def test_severity_ordering(self):
        findings = [
            _finding(severity=Severity.LOW, title="Low issue"),
            _finding(severity=Severity.CRITICAL, title="Critical issue"),
            _finding(severity=Severity.MEDIUM, title="Medium issue"),
        ]
        fmt = ReportFormatter()
        md = fmt.format(_report(findings=findings))
        critical_pos = md.index("Critical issue")
        medium_pos = md.index("Medium issue")
        low_pos = md.index("Low issue")
        assert critical_pos < medium_pos < low_pos

    def test_severity_summary_table(self):
        findings = [
            _finding(severity=Severity.HIGH),
            _finding(severity=Severity.HIGH),
            _finding(severity=Severity.LOW, title="Minor"),
        ]
        fmt = ReportFormatter()
        md = fmt.format(_report(findings=findings))
        assert "| HIGH | 2 |" in md
        assert "| LOW | 1 |" in md

    def test_header_metadata(self):
        fmt = ReportFormatter()
        md = fmt.format(_report())
        assert "sess-001" in md
        assert "Evidence collected:** 5" in md
        assert "Rules evaluated:** 100" in md
        assert "12.5s" in md

    def test_footer(self):
        fmt = ReportFormatter()
        md = fmt.format(_report(findings=[_finding()]))
        assert "1 finding(s)" in md
        assert "100 rules evaluated" in md

    def test_failure_class_displayed(self):
        fmt = ReportFormatter()
        md = fmt.format(_report(findings=[_finding(failure_class=FailureClass.NETWORK_ISOLATION)]))
        assert "network_isolation" in md.lower()

    def test_unknown_failure_class_hidden(self):
        fmt = ReportFormatter()
        md = fmt.format(_report(findings=[_finding(failure_class=FailureClass.UNKNOWN)]))
        assert "Failure class" not in md


# ---------------------------------------------------------------------------
# Streaming format
# ---------------------------------------------------------------------------


class TestStreamFormat:
    @pytest.mark.asyncio
    async def test_stream_without_factory_yields_deterministic(self):
        fmt = ReportFormatter()
        chunks = []
        async for chunk in fmt.stream_format(_report(findings=[_finding()])):
            chunks.append(chunk)
        assert len(chunks) == 1
        assert "Test finding" in chunks[0]

    @pytest.mark.asyncio
    async def test_stream_with_factory_uses_llm(self):
        update = MagicMock()
        update.text = "LLM summary"

        final = MagicMock()
        final.text = "LLM summary"

        class FakeStream:
            async def __aiter__(self):
                yield update

            async def get_final_response(self):
                return final

        agent = MagicMock()
        agent.run.return_value = FakeStream()

        factory = MagicMock()
        factory.create.return_value = agent

        fmt = ReportFormatter(agent_factory=factory)
        chunks = []
        async for chunk in fmt.stream_format(_report(findings=[_finding()])):
            chunks.append(chunk)
        assert "LLM summary" in chunks

    @pytest.mark.asyncio
    async def test_stream_llm_failure_falls_back(self):
        agent = MagicMock()
        agent.run.side_effect = RuntimeError("LLM down")

        factory = MagicMock()
        factory.create.return_value = agent

        fmt = ReportFormatter(agent_factory=factory)
        chunks = []
        async for chunk in fmt.stream_format(_report(findings=[_finding()])):
            chunks.append(chunk)
        assert len(chunks) == 1
        assert "Test finding" in chunks[0]


# ---------------------------------------------------------------------------
# Text serialization
# ---------------------------------------------------------------------------


class TestFindingsAsText:
    def test_empty_findings(self):
        text = ReportFormatter._findings_as_text(_report())
        assert text == "No findings."

    def test_findings_serialized(self):
        text = ReportFormatter._findings_as_text(_report(findings=[_finding()]))
        assert "HIGH" in text
        assert "Test finding" in text
        assert "Fix step 1" in text
