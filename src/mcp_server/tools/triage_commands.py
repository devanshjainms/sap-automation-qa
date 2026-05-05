# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Triage command tools — log search and investigation feedback."""

from __future__ import annotations
import asyncio
import logging
from typing import Any
from mcp.server.fastmcp import Context
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.session import ServerSession
from mcp.types import ToolAnnotations
from src.core.cbr import CbrExtract, InvestigationOutcome
from src.core.execution.log_command_builder import LogCommandBuilder
from src.core.execution.ssh_collector import SshCollectorStrategy
from src.core.models.evidence import CollectorType, EvidenceType
from src.core.execution import EvidenceDefinition
from src.core.models.knowledge import EvidenceCollectorDef
from src.mcp_server.server import SapContext, mcp
from src.mcp_server.tools._helpers import (
    get_sap_context,
    tool_info,
    ICON_CHART,
    ICON_FILE,
    load_workspace_host_details,
    load_workspace_params,
)

logger = logging.getLogger(__name__)


@mcp.tool(
    name="search_logs",
    title="Search Logs",
    description=(
        "Search a single log source on a target SAP host. Uses RAG "
        "retrieval against the log-file knowledge base to find the "
        "best matching log source for the investigation query, then "
        "fetches the relevant entries via SSH. Call iteratively — "
        "use findings from each call to refine the next search. "
        "Supports time-window filtering and grep pattern matching."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    ),
    icons=[ICON_FILE],
    structured_output=False,
)
async def search_logs(
    workspace_id: str,
    query: str,
    host: str = "",
    time_window: str = "",
    pattern: str = "",
    max_lines: int = 100,
    ctx: Context[ServerSession, SapContext] | None = None,
) -> dict[str, Any]:
    """Search the most relevant log source for the given query.

    Uses RAG retrieval to select the best log file, resolves
    paths from workspace parameters, applies time/pattern
    filtering, and executes via SSH.

    :param workspace_id: SAP workspace identifier.
    :param query: Investigation context (e.g. "fencing failure", "HANA takeover replication error").
    :param host: Target host IP. Defaults to first host.
    :param time_window: Optional time range. Formats accepted:
        ``last 30 min``, ``14:00 to 14:30``,
        ``2025-03-31 14:00 to 2025-03-31 14:30``.
        Applied as journalctl --since/--until or grep filter.
    :param pattern: Optional grep pattern to filter log lines.
    :param max_lines: Maximum lines to return (default 100).
    """
    logger.info(
        "Tool called: search_logs(workspace_id=%s, query=%.60s)",
        workspace_id,
        query,
    )
    sap = get_sap_context(ctx)

    sap.validator.workspace_id(workspace_id)

    if not query.strip():
        raise ToolError("query is required — describe what you're investigating.")

    max_lines = max(10, min(max_lines, 500))

    scored = sap.retriever.search_evidence_definitions(
        query=query,
        limit=10,
    )
    log_defs: list[EvidenceCollectorDef] = [
        s.item
        for s in scored
        if isinstance(s.item, EvidenceCollectorDef)
        and s.item.evidence_type == "log_output"
        and s.item.metadata.get("access_method")
    ]
    if not log_defs:
        raise ToolError(
            "No log evidence definitions matched the query. " "Ensure EC-LOG-* seed data is loaded."
        )

    ev_def = log_defs[0]
    log_title = ev_def.name
    best = next(s for s in scored if s.item is ev_def)

    host_details = load_workspace_host_details(
        sap.workspaces_base,
        workspace_id,
    )
    if not host_details:
        raise ToolError(f"No hosts found for workspace {workspace_id}")

    if host:
        matched = [h for h in host_details if h["ansible_host"] == host]
        if not matched:
            available = [h["ansible_host"] for h in host_details]
            raise ToolError(f"Host {host} not found. Available: {available}")
        target = matched[0]
    else:
        target = host_details[0]

    target_ip = target["ansible_host"]
    ssh_user = target.get("ansible_user", "")
    become_user = target.get("become_user", "")

    extra_vars = load_workspace_params(
        sap.workspaces_base,
        workspace_id,
    )

    loop = asyncio.get_running_loop()
    ssh_credential = await loop.run_in_executor(
        None,
        lambda: sap.ssh_cache.provision(workspace_id, extra_vars),
    )
    if ssh_credential is None:
        raise ToolError(f"No SSH credentials for workspace {workspace_id}")

    builder = LogCommandBuilder(ev_def.metadata, extra_vars)
    command = builder.build(
        time_window=time_window,
        pattern=pattern,
        max_lines=max_lines,
    )

    await tool_info(ctx, f"Searching {log_title} on {target_ip} " f"(score={best.score:.2f})")

    definition = EvidenceDefinition(
        definition_id=f"log@{ev_def.id}@{target_ip}",
        evidence_type=EvidenceType.COMMAND_OUTPUT,
        collector_type=CollectorType.SSH,
        host=target_ip,
        command=command,
        timeout_seconds=30,
        metadata={
            "private_key_path": (ssh_credential.private_key_path or ""),
            "ssh_user": ssh_user,
            "become_user": become_user,
        },
    )
    artifact = SshCollectorStrategy().collect(definition)

    stdout = artifact.content or ""
    line_count = len(stdout.splitlines()) if stdout else 0

    other_sources = [
        {"id": d.id, "title": d.name, "score": round(s.score, 3)}
        for s in scored[1:]
        if isinstance(s.item, EvidenceCollectorDef) and s.item.evidence_type == "log_output"
        for d in [s.item]
    ]

    return {
        "log_source": ev_def.id,
        "title": log_title,
        "relevance_score": round(best.score, 3),
        "host": target_ip,
        "command_executed": command,
        "line_count": line_count,
        "output": stdout,
        "stderr": artifact.error or "",
        "other_relevant_sources": other_sources,
    }


@mcp.tool(
    name="record_investigation_outcome",
    title="Record Investigation Outcome",
    description=(
        "Record the outcome of an investigation session so the "
        "learning pipeline can update pattern confidence. Call this "
        "when the operator confirms whether the investigation was "
        "accurate (correct, partial, or incorrect)."
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
async def record_investigation_outcome(
    session_id: str,
    outcome: str,
    root_cause_found: bool = False,
    ctx: Context[ServerSession, SapContext] | None = None,
) -> dict[str, Any]:
    """Record operator feedback for a completed triage session.

    :param session_id: Triage session ID.
    :param outcome: One of ``correct``, ``partial``, ``incorrect``.
    :param root_cause_found: Whether a root cause was identified.
    :param ctx: MCP context.
    :returns: Summary of the recorded outcome.
    """
    logger.info(
        "Tool called: record_investigation_outcome(session_id=%s, outcome=%s)",
        session_id,
        outcome,
    )
    sap = get_sap_context(ctx)

    session = sap.validator.session_id(session_id)

    try:
        parsed_outcome = InvestigationOutcome(outcome.lower().strip())
    except ValueError:
        valid = [o.value for o in InvestigationOutcome]
        raise ToolError(f"Invalid outcome '{outcome}'. Must be one of: {valid}")

    if session.report is None:
        raise ToolError(f"Session {session_id} has no report. " "Run run_analysis first.")

    experience = CbrExtract.build_experience(
        session=session,
        outcome=parsed_outcome,
        root_cause_found=root_cause_found,
    )
    candidate = CbrExtract.extract(
        report=session.report,
        query=session.workspace_id,
    )

    stored = sap.learning_pipeline.process_session(
        candidate=candidate,
        experience=experience,
    )

    return {
        "session_id": session_id,
        "outcome": parsed_outcome.value,
        "pattern_id": stored.id,
        "pattern_confidence": round(stored.confidence, 3),
        "message": (
            f"Recorded '{parsed_outcome.value}' feedback for session "
            f"{session_id}. Pattern {stored.id} confidence: "
            f"{stored.confidence:.3f}."
        ),
    }
