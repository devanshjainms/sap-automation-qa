# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Triage analyzer — evidence collection, analysis, reporting, command
execution, log search, and investigation feedback."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from mcp.server.fastmcp import Context
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.session import ServerSession
from mcp.types import ToolAnnotations

from src.agents.cbr import CbrExtract, InvestigationOutcome
from src.core.execution.evidence_collector import EvidenceDefinition
from src.core.execution.log_command_builder import LogCommandBuilder
from src.core.execution.ssh_collector import SshCollectorStrategy
from src.core.models.evidence import CollectorType, EvidenceArtifact, EvidenceType
from src.core.models.knowledge import EvidenceCollectorDef, ExperienceEntry
from src.core.models.ssh import SshCredential
from src.core.models.triage import TriageSession
from src.mcp_server.server import SapContext, mcp
from src.mcp_server.tools._helpers import (
    ICON_CHART,
    ICON_FILE,
    ICON_LIST,
    ICON_SEARCH,
    ICON_TERMINAL,
    load_workspace_host_details,
    load_workspace_params,
    rebuild_artifacts,
)

logger = logging.getLogger(__name__)


def _resolve_placeholders(command: str, extra_vars: dict[str, Any]) -> str:
    """Substitute ``<sid>``, ``<SID>``, and ``<NR>`` with workspace values.

    :param command: Raw command template from evidence definition.
    :param extra_vars: Workspace parameters (sap-parameters.yaml).
    :returns: Command with placeholders resolved, or unchanged if
        the required parameters are missing.
    """
    db_sid = extra_vars.get("db_sid") or extra_vars.get("sap_sid") or ""
    db_nr = str(extra_vars.get("db_instance_number", "")).strip('"').strip("'")
    scs_nr = str(extra_vars.get("scs_instance_number", "")).strip('"').strip("'")
    nr = db_nr or scs_nr or ""
    if db_sid:
        command = command.replace("<sid>", db_sid.lower())
        command = command.replace("<SID>", db_sid.upper())
    if nr:
        command = command.replace("<NR>", nr)
    return command


class TriageAnalyzerTools:
    """Evidence collection, analysis, reporting, command execution,
    log search, and investigation feedback tools."""

    @staticmethod
    @mcp.tool(
        name="list_evidence_catalog",
        title="List Evidence Catalog",
        description=(
            "List all available evidence collectors in the knowledge store. "
            "Each collector has a definition ID, name, description, command, "
            "and tags. Use this to discover what evidence can be gathered "
            "via collect_evidence(definitions=[...]) or "
            "run_evidence_collector(definition_id=...)."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
        icons=[ICON_LIST],
        structured_output=False,
    )
    async def list_evidence_catalog(
        category: str = "",
        ctx: Context[ServerSession, SapContext] | None = None,
    ) -> dict[str, Any]:
        """List available evidence collectors from the knowledge store.

        :param category: Optional tag filter (e.g. ``hana``, ``pacemaker``,
            ``logs``, ``storage``). Empty returns all definitions.
        """
        logger.info("Tool called: list_evidence_catalog(category=%s)", category)
        assert ctx is not None
        sap: SapContext = ctx.request_context.lifespan_context

        all_defs = sap.knowledge_store.load_evidence_definitions()
        if category.strip():
            cat = category.strip().lower()
            all_defs = [d for d in all_defs if cat in (t.lower() for t in d.tags)]

        return {
            "definitions": [
                {
                    "id": d.id,
                    "name": d.name,
                    "description": d.description,
                    "command": d.command,
                    "tags": d.tags,
                    "evidence_type": d.evidence_type,
                    "requires_ha": d.requires_ha,
                }
                for d in all_defs
            ],
            "total": len(all_defs),
        }

    @staticmethod
    @mcp.tool(
        name="collect_evidence",
        title="Collect Evidence",
        description=(
            "Gather evidence from a target SAP system via SSH. "
            "Connects to host(s) from the workspace hosts.yaml and collects evidence. "
            "Use target_tiers to scope to specific SAP layers (hana, scs, ers, pas, app)."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=True,
        ),
        icons=[ICON_SEARCH],
        structured_output=False,
    )
    async def collect_evidence(
        workspace_id: str,
        target_tiers: list[str] | None = None,
        definitions: list[str] | None = None,
        query: str = "",
        timeout_seconds: int = 60,
        ctx: Context[ServerSession, SapContext] | None = None,
    ) -> dict[str, Any]:
        """Gather evidence from SAP hosts via SSH.

        Connects to hosts from workspace ``hosts.yaml``. Use
        ``target_tiers`` to scope to specific SAP layers.
        When ``query`` is provided and ``definitions`` is omitted,
        uses RAG retrieval to select the most relevant evidence
        definitions instead of running all of them.
        """
        logger.info("Tool called: collect_evidence(workspace_id=%s)", workspace_id)
        assert ctx is not None
        sap: SapContext = ctx.request_context.lifespan_context

        sap.validator.workspace_id(workspace_id)
        sap.validator.timeout(timeout_seconds)
        definitions = sap.validator.definitions(definitions)

        session = TriageSession(workspace_id=workspace_id)
        sid = str(session.id)
        sap.triage_sessions[sid] = session
        host_details = load_workspace_host_details(sap.workspaces_base, workspace_id)
        if not host_details:
            raise ToolError(
                f"No hosts found for workspace {workspace_id}. "
                "Ensure hosts.yaml exists in the workspace directory."
            )

        if target_tiers:
            tier_set = {t.lower() for t in target_tiers}
            filtered = [h for h in host_details if h.get("node_tier", "").lower() in tier_set]
            if not filtered:
                available = sorted({h["node_tier"] for h in host_details if h.get("node_tier")})
                raise ToolError(
                    f"No hosts match tiers {target_tiers}. " f"Available tiers: {available}"
                )
            host_details = filtered

        hosts = [h["ansible_host"] for h in host_details]

        extra_vars = load_workspace_params(sap.workspaces_base, workspace_id)
        ssh_credential: SshCredential | None = None
        try:
            await ctx.info(f"Provisioning SSH credentials for workspace {workspace_id}")
            loop = asyncio.get_running_loop()
            ssh_credential = await loop.run_in_executor(
                None,
                lambda: sap.ssh_cache.provision(workspace_id, extra_vars),
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

        ssh_user = host_details[0].get("ansible_user", "")
        become_user = host_details[0].get("become_user", "")

        host_meta: dict[str, dict[str, str]] = {}
        for hd in host_details:
            host_meta[hd["ansible_host"]] = {
                "ssh_user": hd.get("ansible_user", ""),
                "become_user": hd.get("become_user", ""),
                "node_tier": hd.get("node_tier", ""),
            }

        unknown: list[str] = []

        if definitions:
            all_defs = sap.knowledge_store.load_evidence_definitions()
            defs_by_id = {d.id: d for d in all_defs}
            collector_defs = [defs_by_id[d] for d in definitions if d in defs_by_id]
            unknown = [d for d in definitions if d not in defs_by_id]
            if unknown:
                logger.warning(
                    "Unknown evidence definition IDs treated as commands: %s",
                    unknown,
                )
        else:
            if query.strip():
                scored = sap.retriever.search_evidence_definitions(
                    query=query,
                    limit=20,
                )
                collector_defs: list[EvidenceCollectorDef] = [
                    r.item for r in scored if r.relevance > 0  # type: ignore[misc]
                ]
                if not collector_defs:
                    collector_defs = sap.knowledge_store.load_evidence_definitions()
                else:
                    logger.info(
                        "RAG selected %d/%d evidence definitions " "for query: %.60s",
                        len(collector_defs),
                        len(scored),
                        query,
                    )
            else:
                collector_defs = sap.knowledge_store.load_evidence_definitions()

            db_ha = extra_vars.get("database_high_availability", False)
            scs_ha = extra_vars.get("scs_high_availability", False)
            if not db_ha and not scs_ha:
                before = len(collector_defs)
                collector_defs = [d for d in collector_defs if not d.requires_ha]
                skipped = before - len(collector_defs)
                if skipped:
                    logger.info(
                        "Filtered %d HA definitions (no HA in workspace %s)",
                        skipped,
                        workspace_id,
                    )

        if not collector_defs and not unknown:
            raise ToolError(
                "No evidence definitions found in the knowledge store. "
                "Ensure seed data is loaded."
            )

        evidence_defs: list[EvidenceDefinition] = []
        for host_ip in hosts:
            meta = host_meta.get(host_ip, {})
            for cd in collector_defs:
                resolved_cmd = _resolve_placeholders(cd.command, extra_vars)
                evidence_defs.append(
                    EvidenceDefinition(
                        definition_id=f"{cd.id}@{host_ip}",
                        evidence_type=EvidenceType(cd.evidence_type),
                        collector_type=CollectorType.SSH,
                        host=host_ip,
                        command=resolved_cmd,
                        description=cd.description,
                        timeout_seconds=cd.max_timeout_seconds,
                        metadata={
                            "workspace_id": workspace_id,
                            "private_key_path": (ssh_credential.private_key_path or ""),
                            "auth_type": ssh_credential.auth_type.value,
                            "ssh_user": meta.get("ssh_user", ssh_user),
                            "become_user": meta.get("become_user", become_user),
                            "node_tier": meta.get("node_tier", ""),
                            "source": cd.source,
                        },
                    )
                )
        if definitions:
            for raw_cmd in unknown:
                for host_ip in hosts:
                    meta = host_meta.get(host_ip, {})
                    evidence_defs.append(
                        EvidenceDefinition(
                            definition_id=f"{raw_cmd}@{host_ip}",
                            evidence_type=EvidenceType.COMMAND_OUTPUT,
                            collector_type=CollectorType.SSH,
                            host=host_ip,
                            command=raw_cmd,
                            description=f"Custom command: {raw_cmd}",
                            timeout_seconds=timeout_seconds,
                            metadata={
                                "workspace_id": workspace_id,
                                "private_key_path": (ssh_credential.private_key_path or ""),
                                "auth_type": ssh_credential.auth_type.value,
                                "ssh_user": meta.get("ssh_user", ssh_user),
                                "become_user": meta.get("become_user", become_user),
                                "node_tier": meta.get("node_tier", ""),
                            },
                        )
                    )

        await ctx.info(
            f"Collecting evidence from {len(hosts)} host(s) "
            f"({len(evidence_defs)} definitions, tiers={target_tiers or 'all'})"
        )

        total_defs = len(evidence_defs)
        try:
            await ctx.report_progress(
                progress=0.0, total=1.0, message="Connecting to target host..."
            )

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

        return {
            "session_id": sid,
            "status": str(session.status),
            "hosts_targeted": hosts,
            "tiers_targeted": target_tiers or [h.get("node_tier", "") for h in host_details],
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

    @staticmethod
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
        assert ctx is not None
        sap: SapContext = ctx.request_context.lifespan_context

        session = sap.validator.session_id(session_id)

        await ctx.info(f"Running analysis on session {session_id}")

        rules = sap.knowledge_store.load_rules()
        artifacts = rebuild_artifacts(session)

        await ctx.report_progress(progress=0.3, total=1.0, message="Loaded rules, analyzing...")

        report = sap.analyzer.analyze(session, artifacts, rules)

        await ctx.report_progress(progress=0.9, total=1.0, message="Learning from session...")

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

        await ctx.report_progress(progress=1.0, total=1.0, message="Analysis complete")

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

    @staticmethod
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

    @staticmethod
    @mcp.tool(
        name="run_evidence_collector",
        title="Run Evidence Collector",
        description=(
            "Run a single evidence collector on a target SAP host via SSH. "
            "Requires a definition_id from the evidence catalog (use "
            "list_evidence_catalog to discover available IDs). The command, "
            "parser, timeout, and run-as user are resolved from the "
            "definition — do NOT construct commands manually."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
        icons=[ICON_TERMINAL],
        structured_output=False,
    )
    async def run_evidence_collector(
        workspace_id: str,
        definition_id: str,
        host: str = "",
        timeout_seconds: int = 30,
        ctx: Context[ServerSession, SapContext] | None = None,
    ) -> dict[str, Any]:
        """Run a single evidence collector by definition ID.

        :param workspace_id: SAP workspace identifier.
        :param definition_id: Evidence definition ID from the catalog
            (e.g. ``EC-CLUSTER-MON-0001``).
        :param host: Target host IP. Defaults to first host.
        :param timeout_seconds: SSH command timeout (default 30).
        """
        logger.info(
            "Tool called: run_evidence_collector(" "workspace_id=%s, definition_id=%s, host=%s)",
            workspace_id,
            definition_id,
            host,
        )
        assert ctx is not None
        sap: SapContext = ctx.request_context.lifespan_context

        sap.validator.workspace_id(workspace_id)

        all_defs = sap.knowledge_store.load_evidence_definitions()
        defs_by_id = {d.id: d for d in all_defs}
        collector_def = defs_by_id.get(definition_id)
        if collector_def is None:
            available_ids = sorted(defs_by_id.keys())
            raise ToolError(
                f"Unknown definition_id '{definition_id}'. "
                f"Use list_evidence_catalog to see available IDs. "
                f"Examples: {available_ids[:5]}"
            )

        host_details = load_workspace_host_details(sap.workspaces_base, workspace_id)
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

        extra_vars = load_workspace_params(sap.workspaces_base, workspace_id)
        resolved_cmd = _resolve_placeholders(collector_def.command, extra_vars)

        loop = asyncio.get_running_loop()
        ssh_credential = await loop.run_in_executor(
            None,
            lambda: sap.ssh_cache.provision(workspace_id, extra_vars),
        )
        if ssh_credential is None:
            raise ToolError(f"No SSH credentials for workspace {workspace_id}")

        definition = EvidenceDefinition(
            definition_id=f"{definition_id}@{target_ip}",
            evidence_type=EvidenceType(collector_def.evidence_type),
            collector_type=CollectorType.SSH,
            host=target_ip,
            command=resolved_cmd,
            timeout_seconds=min(timeout_seconds, collector_def.max_timeout_seconds),
            metadata={
                "private_key_path": (ssh_credential.private_key_path or ""),
                "ssh_user": ssh_user,
                "become_user": become_user,
                "source": collector_def.source,
            },
        )
        artifact = SshCollectorStrategy().collect(definition)

        return {
            "definition_id": definition_id,
            "name": collector_def.name,
            "host": target_ip,
            "command": resolved_cmd,
            "exit_code": artifact.metadata.get("return_code", -1),
            "stdout": artifact.content or "",
            "stderr": artifact.error or "",
        }

    @staticmethod
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
        :param query: Investigation context (e.g. "fencing failure",
            "HANA takeover replication error").
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
        assert ctx is not None
        sap: SapContext = ctx.request_context.lifespan_context

        sap.validator.workspace_id(workspace_id)

        if not query.strip():
            raise ToolError("query is required — describe what you're investigating.")

        max_lines = max(10, min(max_lines, 500))

        scored = sap.retriever.search_evidence_definitions(
            query=query,
            limit=10,
        )
        log_defs: list[EvidenceCollectorDef] = [
            s.item  # type: ignore[misc]
            for s in scored
            if isinstance(s.item, EvidenceCollectorDef)
            and s.item.evidence_type == "log_output"
            and s.item.metadata.get("access_method")
        ]
        if not log_defs:
            raise ToolError(
                "No log evidence definitions matched the query. "
                "Ensure EC-LOG-* seed data is loaded."
            )

        ev_def = log_defs[0]
        log_title = ev_def.name
        best = next(s for s in scored if s.item is ev_def)

        # --- Resolve host ---
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

        await ctx.info(f"Searching {log_title} on {target_ip} " f"(score={best.score:.2f})")

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

    @staticmethod
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
        assert ctx is not None
        sap: SapContext = ctx.request_context.lifespan_context

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
