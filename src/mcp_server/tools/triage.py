# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Triage tools — evidence collection, analysis, knowledge, workspace lookup.

Tools registered here:
    - ``collect_evidence``
    - ``run_analysis``
    - ``query_knowledge``
    - ``get_triage_report``
    - ``list_workspaces``
    - ``get_workspace``
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from mcp.server.fastmcp import Context
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.session import ServerSession

from src.core.execution.evidence_collector import EvidenceDefinition
from src.core.models.evidence import CollectorType, EvidenceArtifact, EvidenceType
from src.core.models.ssh import SshCredential
from src.core.models.triage import TriageSession
from src.mcp_server.server import SapContext, mcp
from src.mcp_server.tools._helpers import (
    load_workspace_hosts,
    load_workspace_params,
    rebuild_artifacts,
)

logger = logging.getLogger(__name__)


@mcp.tool()
async def collect_evidence(
    workspace_id: str,
    definitions: list[str] | None = None,
    timeout_seconds: int = 60,
    ctx: Context[ServerSession, SapContext] | None = None,
) -> dict[str, Any]:
    """Gather evidence from a target SAP system via SSH.

    Connects to the target host(s) discovered from the workspace
    ``hosts.yaml`` and collects evidences
    """
    assert ctx is not None
    sap: SapContext = ctx.request_context.lifespan_context

    sap.validator.workspace_id(workspace_id)
    sap.validator.timeout(timeout_seconds)
    definitions = sap.validator.definitions(definitions)

    session = TriageSession(workspace_id=workspace_id)
    sid = str(session.id)
    sap.triage_sessions[sid] = session
    hosts = load_workspace_hosts(sap.workspaces_base, workspace_id)
    if not hosts:
        raise ToolError(
            f"No hosts found for workspace {workspace_id}. "
            "Ensure hosts.yaml exists in the workspace directory."
        )

    extra_vars = load_workspace_params(sap.workspaces_base, workspace_id)
    ssh_credential: SshCredential | None = None
    try:
        await ctx.info(f"Provisioning SSH credentials for workspace {workspace_id}")
        loop = asyncio.get_running_loop()
        ssh_credential = await loop.run_in_executor(
            None,
            lambda: sap.ssh_provider.provision(workspace_id, extra_vars),
        )
        if ssh_credential is None:
            raise ToolError(
                f"No SSH credentials found for workspace {workspace_id}. "
                "Provide ssh_key.ppk in the workspace or configure "
                "secret_id in sap-parameters.yaml."
            )
    except ToolError:
        raise
    except Exception as exc:
        logger.error("SSH provisioning failed for %s: %s", workspace_id, exc)
        raise ToolError(f"SSH credential provisioning failed: {exc}") from exc

    target_host = hosts[0]  # Primary host for evidence collection.
    unknown: list[str] = []

    if definitions:
        # Caller specified explicit definition IDs — look them up in the store.
        all_defs = sap.knowledge_store.load_evidence_definitions()
        defs_by_id = {d.id: d for d in all_defs}
        collector_defs = [defs_by_id[d] for d in definitions if d in defs_by_id]
        # If IDs don't match any stored definition, treat them as raw commands.
        unknown = [d for d in definitions if d not in defs_by_id]
        if unknown:
            logger.warning("Unknown evidence definition IDs treated as commands: %s", unknown)
    else:
        # Load all seed evidence definitions from the knowledge store.
        collector_defs = sap.knowledge_store.load_evidence_definitions()

    if not collector_defs and not unknown:
        raise ToolError(
            "No evidence definitions found in the knowledge store. "
            "Ensure seed data is loaded."
        )

    evidence_defs = [
        EvidenceDefinition(
            definition_id=cd.id,
            evidence_type=EvidenceType.COMMAND_OUTPUT,
            collector_type=CollectorType.SSH,
            host=target_host,
            command=cd.command,
            description=cd.description,
            timeout_seconds=cd.max_timeout_seconds,
            metadata={
                "workspace_id": workspace_id,
                "private_key_path": ssh_credential.private_key_path or "",
                "auth_type": ssh_credential.auth_type.value,
            },
        )
        for cd in collector_defs
    ]
    if definitions:
        for raw_cmd in unknown:
            evidence_defs.append(
                EvidenceDefinition(
                    definition_id=raw_cmd,
                    evidence_type=EvidenceType.COMMAND_OUTPUT,
                    collector_type=CollectorType.SSH,
                    host=target_host,
                    command=raw_cmd,
                    description=f"Custom command: {raw_cmd}",
                    timeout_seconds=timeout_seconds,
                    metadata={
                        "workspace_id": workspace_id,
                        "private_key_path": ssh_credential.private_key_path or "",
                        "auth_type": ssh_credential.auth_type.value,
                    },
                )
            )

    await ctx.info(
        f"Collecting evidence from {target_host} "
        f"({len(evidence_defs)} definitions, {len(hosts)} hosts discovered)"
    )

    total_defs = len(evidence_defs)
    try:
        await ctx.report_progress(progress=0.0, total=1.0, message="Connecting to target host...")

        def _collect() -> list[EvidenceArtifact]:
            return sap.triage_executor.collect(session, evidence_defs)

        artifacts = await loop.run_in_executor(None, _collect)

        for i, artifact in enumerate(artifacts, 1):
            pct = i / max(total_defs, 1)
            await ctx.report_progress(
                progress=pct,
                total=1.0,
                message=f"Collected {i}/{total_defs}: {artifact.evidence_id}",
            )

    except ToolError:
        raise
    except Exception as exc:
        logger.error("Evidence collection failed for %s: %s", sid, exc)
        try:
            session.fail(str(exc))
        except Exception:
            pass
        raise ToolError(f"Evidence collection failed: {exc}") from exc
    finally:
        if ssh_credential:
            ssh_credential.cleanup()

    return {
        "session_id": sid,
        "status": str(session.status),
        "hosts_discovered": hosts,
        "target_host": target_host,
        "artifact_count": len(artifacts),
        "artifacts": [
            {
                "evidence_id": a.evidence_id,
                "evidence_type": str(a.evidence_type),
                "status": str(a.status),
                "host": a.host,
            }
            for a in artifacts
        ],
    }


@mcp.tool()
async def run_analysis(
    session_id: str,
    ctx: Context[ServerSession, SapContext] | None = None,
) -> dict[str, Any]:
    """Analyze collected evidence against 400+ SAP-specific rules.

    Requires a ``session_id`` from ``collect_evidence``. Returns findings
    with severity, failure class, and remediation steps.
    Call ``get_triage_report`` for a formatted summary.
    """
    assert ctx is not None
    sap: SapContext = ctx.request_context.lifespan_context

    session = sap.validator.session_id(session_id)

    await ctx.info(f"Running analysis on session {session_id}")

    rules = sap.knowledge_store.load_rules()
    artifacts = rebuild_artifacts(session)

    await ctx.report_progress(progress=0.3, total=1.0, message="Loaded rules, analyzing...")

    report = sap.analyzer.analyze(session, artifacts, rules)

    await ctx.report_progress(progress=0.9, total=1.0, message="Learning from session...")

    # Extract a learned pattern and feed through the learning pipeline.
    try:
        from src.agents.cbr import CbrExtract  # pylint: disable=import-outside-toplevel
        from src.core.models.knowledge import ExperienceEntry  # pylint: disable=import-outside-toplevel

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
        logger.warning("Learning pipeline failed for session %s", session_id, exc_info=True)

    await ctx.report_progress(progress=1.0, total=1.0, message="Analysis complete")

    return {
        "session_id": session_id,
        "finding_count": report.finding_count,
        "has_critical": report.has_critical,
        "summary": report.summary,
        "findings": [
            {
                "finding_id": f.finding_id,
                "severity": f.severity,
                "title": f.title,
                "failure_class": f.failure_class,
                "remediation": f.remediation,
            }
            for f in report.findings
        ],
    }


@mcp.tool()
async def query_knowledge(
    query: str,
    category: str = "",
    limit: int = 20,
    ctx: Context[ServerSession, SapContext] | None = None,
) -> dict[str, Any]:
    """Search the SAP knowledge base for rules, playbooks, and references.

    Useful for understanding what the system checks, finding remediation
    playbooks, or retrieving SAP Notes relevant to a failure class.
    """
    assert ctx is not None
    sap: SapContext = ctx.request_context.lifespan_context

    query = sap.validator.query(query)
    limit = max(1, min(limit, 100))

    # Retrieve with a generous limit so we can report accurate totals.
    rule_results = sap.retriever.search_rules(query=query, limit=1000)
    playbook_results = sap.retriever.search_playbooks(query=query, limit=1000)

    if category:
        rule_results = [
            r for r in rule_results if category.lower() in getattr(r.item, "category", "").lower()
        ]

    total_rules = len(rule_results)
    total_playbooks = len(playbook_results)

    return {
        "rules": [
            {
                "id": r.item_id,
                "name": getattr(r.item, "name", ""),
                "severity": getattr(r.item, "severity", ""),
                "category": getattr(r.item, "category", ""),
                "score": round(r.score, 3),
            }
            for r in rule_results[:limit]
        ],
        "playbooks": [
            {
                "id": r.item_id,
                "name": getattr(r.item, "name", ""),
                "category": getattr(r.item, "category", ""),
                "score": round(r.score, 3),
            }
            for r in playbook_results[:limit]
        ],
        "total_rules": total_rules,
        "total_playbooks": total_playbooks,
    }


@mcp.tool()
async def get_triage_report(
    session_id: str,
    ctx: Context[ServerSession, SapContext] | None = None,
) -> dict[str, Any]:
    """Retrieve a completed triage report for a session.

    Returns the full report with findings, severity breakdown, and
    remediation steps. Requires a session that has completed
    ``run_analysis``.
    """
    assert ctx is not None
    sap: SapContext = ctx.request_context.lifespan_context

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


@mcp.tool()
async def list_workspaces(
    ctx: Context[ServerSession, SapContext] | None = None,
) -> dict[str, Any]:
    """List available SAP system workspaces.

    Each workspace represents one SAP landscape (SID). Returns workspace
    IDs, names, and environment tags.
    """
    from src.api.routes.workspaces import (  # pylint: disable=import-outside-toplevel
        _load_workspaces_from_directory,
    )

    assert ctx is not None
    sap: SapContext = ctx.request_context.lifespan_context

    workspaces = _load_workspaces_from_directory(base_dir=str(sap.workspaces_base))

    return {
        "workspaces": [
            {
                "id": ws.id,
                "name": ws.name,
                "environment": ws.environment,
            }
            for ws in workspaces
        ],
        "total": len(workspaces),
    }


@mcp.tool()
async def get_workspace(
    workspace_id: str,
    ctx: Context[ServerSession, SapContext] | None = None,
) -> dict[str, Any]:
    """Get details of a specific SAP workspace.

    Returns workspace ID, name, environment, and path.
    """
    from src.api.routes.workspaces import (  # pylint: disable=import-outside-toplevel
        _load_workspaces_from_directory,
    )

    assert ctx is not None
    sap: SapContext = ctx.request_context.lifespan_context
    sap.validator.workspace_id(workspace_id)

    workspaces = _load_workspaces_from_directory(base_dir=str(sap.workspaces_base))
    for ws in workspaces:
        if ws.id == workspace_id:
            return {
                "id": ws.id,
                "name": ws.name,
                "environment": ws.environment,
                "path": ws.path,
            }
    raise ToolError(f"Workspace '{workspace_id}' not found")
