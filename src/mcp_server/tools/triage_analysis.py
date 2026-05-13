# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Triage analysis tools — evidence + rules retrieval for LLM reasoning."""

from __future__ import annotations
import logging
from typing import Any
from mcp.server.fastmcp import Context
from mcp.server.session import ServerSession
from mcp.types import ToolAnnotations
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

_MAX_OUTPUT_CHARS = 4000


@mcp.tool(
    name="get_analysis_context",
    title="Get Analysis Context",
    description=(
        "Retrieve collected evidence and applicable SAP rules for a triage "
        "session. Returns raw evidence output and matching rules so you can "
        "reason about the system health, identify issues, and suggest "
        "remediation. Requires a session_id from collect_evidence."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
    icons=[ICON_CHART],
    structured_output=False,
)
async def get_analysis_context(
    session_id: str,
    ctx: Context[ServerSession, SapContext] | None = None,
) -> dict[str, Any]:
    """Retrieve evidence and applicable rules for LLM-driven analysis."""
    logger.info("Tool called: get_analysis_context(session_id=%s)", session_id)
    sap = get_sap_context(ctx)

    session = sap.validator.session_id(session_id)

    await tool_info(ctx, f"Loading analysis context for session {session_id}")

    rules = sap.knowledge_store.load_rules(system=session.system_properties)
    artifacts = rebuild_artifacts(session)

    await tool_progress(ctx, progress=0.5, total=1.0, message="Loaded evidence and rules")

    usable = [a for a in artifacts if a.is_usable]
    if not usable:
        failed_ids = [a.evidence_id for a in artifacts if not a.is_usable][:10]
        return {
            "session_id": session_id,
            "total_artifacts": len(artifacts),
            "usable_artifacts": 0,
            "failed_artifacts": failed_ids,
            "hint": (
                "No usable evidence. Use get_evidence_output(session_id, "
                "evidence_id) to inspect errors, then retry collection."
            ),
        }

    evidence_summaries = []
    for artifact in usable:
        content = artifact.content or ""
        if len(content) > _MAX_OUTPUT_CHARS:
            content = content[:_MAX_OUTPUT_CHARS] + "\n... (truncated)"
        evidence_summaries.append(
            {
                "evidence_id": artifact.evidence_id,
                "command": artifact.command,
                "host": artifact.host,
                "output": content,
            }
        )

    rule_summaries = [
        {
            "id": r.id,
            "name": r.name,
            "description": r.description,
            "category": r.category,
            "severity": r.severity,
            "tags": r.tags,
        }
        for r in rules[:100]
    ]

    await tool_progress(ctx, progress=1.0, total=1.0, message="Context ready")

    return {
        "session_id": session_id,
        "workspace_id": session.workspace_id,
        "total_artifacts": len(artifacts),
        "usable_artifacts": len(usable),
        "evidence": evidence_summaries,
        "applicable_rules": rule_summaries,
        "total_rules": len(rules),
        "instruction": (
            "Analyze the evidence output against the applicable rules. "
            "Identify configuration issues, cluster health problems, and "
            "suggest remediation steps. Use get_evidence_output for full "
            "output of any truncated artifact."
        ),
    }
