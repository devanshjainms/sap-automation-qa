# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Triage analysis tools — rule-based analysis and report generation."""

from __future__ import annotations
import logging
from typing import Any
from mcp.server.fastmcp import Context
from mcp.server.session import ServerSession
from mcp.types import ToolAnnotations
from src.core.cbr import CbrExtract
from src.core.models.knowledge import ExperienceEntry
from src.mcp_server.server import SapContext, mcp
from src.mcp_server.tools._helpers import (
    get_sap_context,
    tool_progress,
    tool_info,
    rebuild_artifacts,
    ICON_CHART,
    ICON_FILE,
)

logger = logging.getLogger(__name__)


@mcp.tool(
    name="run_analysis",
    title="Run Analysis",
    description=(
        "Analyze collected evidence against 400+ SAP-specific rules. "
        "Requires a session_id from collect_evidence. Returns findings "
        "with severity, failure class, and remediation steps."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
    icons=[ICON_CHART],
    structured_output=False,
)
async def run_analysis(
    session_id: str,
    ctx: Context[ServerSession, SapContext] | None = None,
) -> dict[str, Any]:
    """Analyze collected evidence against SAP-specific rules.

    Requires a ``session_id`` from ``collect_evidence``.
    """
    logger.info("Tool called: run_analysis(session_id=%s)", session_id)
    sap = get_sap_context(ctx)

    session = sap.validator.session_id(session_id)

    await tool_info(ctx, f"Running analysis on session {session_id}")

    rules = sap.knowledge_store.load_rules(system=session.system_properties)
    artifacts = rebuild_artifacts(session)

    await tool_progress(ctx, progress=0.3, total=1.0, message="Loaded rules, analyzing...")

    usable = [a for a in artifacts if a.is_usable]
    if not usable:
        failed_ids = [a.evidence_id for a in artifacts if not a.is_usable][:10]
        return {
            "session_id": session_id,
            "health": "UNKNOWN",
            "error": "No usable evidence artifacts to analyze.",
            "total_artifacts": len(artifacts),
            "usable_artifacts": 0,
            "failed_artifacts": failed_ids,
            "hint": (
                "Use get_evidence_output(session_id, evidence_id) to inspect "
                "individual artifact errors, then retry collection with "
                "corrected parameters."
            ),
        }

    try:
        report = sap.analyzer.analyze(session, artifacts, rules)
    except Exception as exc:
        logger.warning("Analysis failed for session %s: %s", session_id, exc)
        return {
            "session_id": session_id,
            "health": "UNKNOWN",
            "error": f"Analysis engine failed: {exc}",
            "total_artifacts": len(artifacts),
            "usable_artifacts": len(usable),
            "hint": (
                "The analyzer could not process the evidence. "
                "Use get_evidence_output to inspect artifacts manually."
            ),
        }

    await tool_progress(ctx, progress=0.9, total=1.0, message="Learning from session...")

    try:
        pattern = CbrExtract.extract(report, query="")
        experience = ExperienceEntry(
            session_id=session_id,
            system_id=session.workspace_id,
            patterns_matched=[pattern.id],
            rules_fired=report.rules_evaluated,
            rules_failed=report.finding_count,
            duration_seconds=report.duration_seconds or 0.0,
        )
        sap.learning_pipeline.process_session(pattern, experience)
    except Exception:
        logger.warning(
            "Learning pipeline failed for session %s",
            session_id,
            exc_info=True,
        )

    await tool_progress(ctx, progress=1.0, total=1.0, message="Analysis complete")

    return {
        "session_id": session_id,
        "health": (
            "CRITICAL"
            if report.has_critical
            else ("HEALTHY" if report.finding_count == 0 else "DEGRADED")
        ),
        "checks_passed": report.rules_passed,
        "checks_failed": report.finding_count,
        "checks_skipped": report.rules_skipped,
        "rules_evaluated": report.rules_evaluated,
        "summary": report.summary,
        "findings": [
            {
                "severity": f.severity,
                "title": f.title,
                "remediation": f.remediation,
            }
            for f in sorted(
                report.findings,
                key=lambda f: {
                    "CRITICAL": 0,
                    "HIGH": 1,
                    "MEDIUM": 2,
                    "LOW": 3,
                }.get(f.severity, 4),
            )[:25]
        ],
    }


@mcp.tool(
    name="get_triage_report",
    title="Get Triage Report",
    description=(
        "Retrieve a completed triage report for a session. Returns the full "
        "report with findings, severity breakdown, and remediation steps. "
        "Requires a session that has completed run_analysis."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
    icons=[ICON_FILE],
    structured_output=False,
)
async def get_triage_report(
    session_id: str,
    ctx: Context[ServerSession, SapContext] | None = None,
) -> dict[str, Any]:
    """Retrieve a completed triage report for a session."""
    sap = get_sap_context(ctx)

    session = sap.validator.session_id(session_id)

    if session.report is None:
        return {
            "session_id": session_id,
            "status": str(session.status),
            "report": None,
            "message": "Analysis not yet complete. Run run_analysis first.",
        }

    return {
        "session_id": session_id,
        "status": str(session.status),
        "report": session.report.model_dump(mode="json"),
        "formatted": sap.formatter.format(session.report),
    }
