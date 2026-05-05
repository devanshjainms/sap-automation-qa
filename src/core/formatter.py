# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Report formatter — converts structured triage findings to prose.
Structured findings are **never modified** — only formatted for
human consumption.
"""

from __future__ import annotations
import logging
from src.core.models.triage import TriageFinding, TriageReport

logger = logging.getLogger(__name__)

_SEVERITY_ORDER = {
    "CRITICAL": 0,
    "HIGH": 1,
    "MEDIUM": 2,
    "LOW": 3,
    "INFO": 4,
}


class ReportFormatter:
    """Formats a ``TriageReport`` into human-readable Markdown."""

    def __init__(self) -> None:
        pass

    def format(self, report: TriageReport) -> str:
        """Format a triage report as deterministic Markdown.

        :param report: The structured triage report.
        :returns: Markdown string.
        """
        sections: list[str] = []
        sections.append(self._header(report))
        sections.append(self._severity_summary(report))

        for finding in sorted(
            report.findings,
            key=lambda f: _SEVERITY_ORDER.get(str(f.severity), 99),
        ):
            sections.append(self._finding_section(finding))

        if not report.findings:
            sections.append("No findings were identified. The system appears healthy.")

        sections.append(self._footer(report))
        return "\n\n".join(sections)

    @staticmethod
    def _header(report: TriageReport) -> str:
        """Report header with metadata."""
        lines = [
            f"# Triage Report — {report.workspace_id}",
            "",
            f"**Session:** `{report.session_id}`  ",
            f"**Evidence collected:** {report.evidence_count}  ",
            f"**Rules evaluated:** {report.rules_evaluated}  ",
        ]
        if report.duration_seconds is not None:
            lines.append(f"**Duration:** {report.duration_seconds:.1f}s  ")
        return "\n".join(lines)

    @staticmethod
    def _severity_summary(report: TriageReport) -> str:
        """Severity breakdown table."""
        counts: dict[str, int] = {}
        for f in report.findings:
            key = str(f.severity)
            counts[key] = counts.get(key, 0) + 1
        if not counts:
            return ""
        lines = ["## Summary", "", "| Severity | Count |", "|----------|-------|"]
        for sev in ("CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"):
            if sev in counts:
                lines.append(f"| {sev} | {counts[sev]} |")
        return "\n".join(lines)

    @staticmethod
    def _finding_section(finding: TriageFinding) -> str:
        """Format a single finding."""
        badge = f"**[{finding.severity}]**"
        lines = [
            f"### {badge} {finding.title or finding.finding_id}",
        ]
        if finding.description:
            lines.append(f"\n{finding.description}")
        if finding.failure_class and str(finding.failure_class) != "unknown":
            lines.append(f"\n**Failure class:** {finding.failure_class}")
        if finding.remediation:
            lines.append("\n**Remediation:**")
            for step in finding.remediation:
                lines.append(f"- {step}")
        if finding.references:
            lines.append("\n**References:**")
            for ref in finding.references:
                lines.append(f"- {ref}")
        return "\n".join(lines)

    @staticmethod
    def _footer(report: TriageReport) -> str:
        """Report footer."""
        return (
            "---\n"
            f"*{report.finding_count} finding(s) from "
            f"{report.rules_evaluated} rules evaluated.*"
        )

    @staticmethod
    def _findings_as_text(report: TriageReport) -> str:
        """Serialize findings as plain text."""
        lines: list[str] = []
        for i, f in enumerate(report.findings, 1):
            parts = [
                f"{i}. [{f.severity}] {f.title or f.finding_id}",
            ]
            if f.description:
                parts.append(f"   Description: {f.description}")
            if f.failure_class and str(f.failure_class) != "unknown":
                parts.append(f"   Failure class: {f.failure_class}")
            if f.remediation:
                parts.append(f"   Remediation: {'; '.join(f.remediation)}")
            lines.append("\n".join(parts))
        return "\n\n".join(lines) if lines else "No findings."
