# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
SAP Triage Skill — full investigation in one call.

Uses the Agent Framework ``Skill`` API with ``@skill.script`` to run
a complete triage pipeline server-side: workspace validation, evidence
collection via SSH, rule-based analysis, and structured diagnosis.
All core services are accessed directly in-process (no MCP round-trips).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from agent_framework import Skill, SkillResource, SkillScript

from src.agents.skills.strings import (
    TRIAGE_DESCRIPTION,
    TRIAGE_INSTRUCTIONS,
    TRIAGE_NAME,
    TRIAGE_RES_EVIDENCE_CATALOG_DESC,
    TRIAGE_RES_EVIDENCE_CATALOG_NAME,
    TRIAGE_RES_WORKSPACES_DESC,
    TRIAGE_RES_WORKSPACES_NAME,
    TRIAGE_SCRIPT_INVESTIGATE_DESC,
    TRIAGE_SCRIPT_INVESTIGATE_NAME,
)
from src.core.execution.evidence_collector import EvidenceDefinition
from src.core.execution.ssh_collector import SshCollectorStrategy
from src.core.models.evidence import CollectorType, EvidenceType
from src.core.models.system import SystemProperties
from src.core.models.triage import TriageSession
from src.core.services.workspace_discovery import load_workspaces_from_directory
from src.mcp_server.tools._helpers import (
    load_workspace_host_details,
    load_workspace_params,
)

logger = logging.getLogger(__name__)


def _resolve_placeholders(command: str, extra_vars: dict[str, Any]) -> str:
    """Substitute ``<sid>``, ``<SID>``, and ``<NR>`` in a command template.

    :param command: Raw command template.
    :param extra_vars: Workspace parameters.
    :returns: Command with placeholders resolved.
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


def build_triage_skill(sap_context: Any) -> Skill:
    """Build the SAP triage skill with core services bound via closure.

    :param sap_context: ``SapContext`` from the MCP server lifespan.
    :returns: Configured ``Skill`` instance.
    """

    def get_workspaces(**kwargs: Any) -> Any:
        """Return available SAP workspaces."""
        workspaces = load_workspaces_from_directory(
            base_dir=str(sap_context.workspaces_base),
        )
        lines = [f"| {ws.id} | {ws.name} | {ws.environment} |" for ws in workspaces]
        header = "| Workspace ID | SAP SID | Environment |\n|---|---|---|"
        return f"{header}\n" + "\n".join(lines) if lines else "No workspaces found."

    def get_evidence_catalog(**kwargs: Any) -> Any:
        """Return the evidence collector catalog."""
        all_defs = sap_context.knowledge_store.load_evidence_definitions()
        lines = []
        for d in all_defs:
            tags = ", ".join(d.tags) if d.tags else ""
            lines.append(f"| {d.id} | {d.description} | {tags} |")
        header = "| Definition ID | Description | Tags |\n|---|---|---|"
        return f"{header}\n" + "\n".join(lines) if lines else "No evidence definitions found."

    async def investigate(workspace_id: str, query: str = "", **kwargs: Any) -> str:
        """Run a full triage investigation on an SAP system.

        :param workspace_id: Target workspace ID.
        :param query: Problem description for RAG-based definition selection.
        :returns: JSON string with structured diagnosis.
        """
        start = time.monotonic()
        steps: list[dict[str, Any]] = []

        try:
            # Step 1: Validate workspace
            host_details = load_workspace_host_details(sap_context.workspaces_base, workspace_id)
            if not host_details:
                return json.dumps(
                    {
                        "status": "failed",
                        "error": (
                            f"No hosts found for workspace '{workspace_id}'. "
                            "Ensure hosts.yaml exists."
                        ),
                    }
                )
            hosts = [h["ansible_host"] for h in host_details]
            extra_vars = load_workspace_params(sap_context.workspaces_base, workspace_id)
            steps.append(
                {
                    "step": "validate_workspace",
                    "status": "ok",
                    "detail": f"Found {len(hosts)} host(s)",
                }
            )

            # Step 2: Provision SSH credentials
            loop = asyncio.get_running_loop()
            ssh_credential = await loop.run_in_executor(
                None,
                lambda: sap_context.ssh_cache.provision(workspace_id, extra_vars),
            )
            if ssh_credential is None:
                return json.dumps(
                    {
                        "status": "failed",
                        "error": (
                            f"No SSH credentials for workspace '{workspace_id}'. "
                            "Provide ssh_key.ppk or configure secret_id."
                        ),
                        "steps": steps,
                    }
                )
            steps.append(
                {
                    "step": "provision_ssh",
                    "status": "ok",
                    "detail": f"Auth type: {ssh_credential.auth_type.value}",
                }
            )

            # Step 3: Build system properties + evidence definitions
            system_props = SystemProperties(
                database_type=(extra_vars.get("platform", "").upper() or None),
                ha_enabled=extra_vars.get("database_high_availability", False),
                hana_topology=("scale_out" if extra_vars.get("database_scale_out") else "scale_up"),
            )

            collector_defs = _select_definitions(sap_context, query, extra_vars)
            steps.append(
                {
                    "step": "select_definitions",
                    "status": "ok",
                    "detail": f"Selected {len(collector_defs)} evidence definitions",
                }
            )

            # Step 4: Build EvidenceDefinition objects for all hosts
            evidence_defs = _build_evidence_definitions(
                collector_defs=collector_defs,
                hosts=hosts,
                host_details=host_details,
                extra_vars=extra_vars,
                ssh_credential=ssh_credential,
                workspace_id=workspace_id,
            )

            # Step 5: Collect evidence via TriageExecutor
            session = TriageSession(
                workspace_id=workspace_id,
                system_properties=system_props,
                query=query,
            )

            artifacts = await loop.run_in_executor(
                None,
                lambda: sap_context.triage_executor.collect(session, evidence_defs),
            )
            successful = sum(1 for a in artifacts if a.is_usable)
            steps.append(
                {
                    "step": "collect_evidence",
                    "status": "ok",
                    "detail": (f"Collected {successful}/{len(artifacts)} artifacts"),
                }
            )

            # Step 6: Analyze against rules
            rules = sap_context.knowledge_store.load_rules(system=system_props)
            report = sap_context.analyzer.analyze(session, artifacts, rules)
            steps.append(
                {
                    "step": "analyze",
                    "status": "ok",
                    "detail": (
                        f"{report.finding_count} findings from " f"{report.rules_evaluated} rules"
                    ),
                }
            )

            # Step 7: Compile result
            duration_ms = int((time.monotonic() - start) * 1000)
            result = {
                "status": "completed",
                "session_id": str(session.id),
                "workspace_id": workspace_id,
                "steps": steps,
                "duration_ms": duration_ms,
                "evidence_count": len(artifacts),
                "evidence_successful": successful,
                "rules_evaluated": report.rules_evaluated,
                "rules_passed": report.rules_passed,
                "finding_count": report.finding_count,
                "has_critical": report.has_critical,
                "findings": [
                    {
                        "finding_id": f.finding_id,
                        "title": f.title,
                        "severity": f.severity,
                        "failure_class": f.failure_class,
                        "description": f.description,
                        "remediation": f.remediation,
                        "rule_id": f.rule_id,
                        "evidence_ids": f.evidence_ids,
                    }
                    for f in report.findings
                ],
                "summary": report.summary or _build_summary(report),
            }
            return json.dumps(result, default=str)

        except Exception as exc:
            logger.exception("Triage skill failed for workspace %s", workspace_id)
            duration_ms = int((time.monotonic() - start) * 1000)
            return json.dumps(
                {
                    "status": "failed",
                    "error": str(exc),
                    "steps": steps,
                    "duration_ms": duration_ms,
                }
            )

    skill = Skill(
        name=TRIAGE_NAME,
        description=TRIAGE_DESCRIPTION,
        content=TRIAGE_INSTRUCTIONS,
        resources=[
            SkillResource(
                name=TRIAGE_RES_WORKSPACES_NAME,
                description=TRIAGE_RES_WORKSPACES_DESC,
                function=get_workspaces,
            ),
            SkillResource(
                name=TRIAGE_RES_EVIDENCE_CATALOG_NAME,
                description=TRIAGE_RES_EVIDENCE_CATALOG_DESC,
                function=get_evidence_catalog,
            ),
        ],
        scripts=[
            SkillScript(
                name=TRIAGE_SCRIPT_INVESTIGATE_NAME,
                description=TRIAGE_SCRIPT_INVESTIGATE_DESC,
                function=investigate,
            ),
        ],
    )
    return skill


def _select_definitions(
    sap_context: Any,
    query: str,
    extra_vars: dict[str, Any],
) -> list:
    """Select evidence definitions — RAG-based if query provided, else all.

    :param sap_context: Application context.
    :param query: User query for RAG selection.
    :param extra_vars: Workspace parameters.
    :returns: List of evidence collector definitions.
    """
    if query.strip():
        scored = sap_context.retriever.search_evidence_definitions(query=query, limit=20)
        defs = [r.item for r in scored if r.relevance > 0]
        if defs:
            return defs

    all_defs = sap_context.knowledge_store.load_evidence_definitions()
    db_ha = extra_vars.get("database_high_availability", False)
    scs_ha = extra_vars.get("scs_high_availability", False)
    if not db_ha and not scs_ha:
        all_defs = [d for d in all_defs if not d.requires_ha]
    return all_defs


def _build_evidence_definitions(
    *,
    collector_defs: list,
    hosts: list[str],
    host_details: list[dict[str, str]],
    extra_vars: dict[str, Any],
    ssh_credential: Any,
    workspace_id: str,
) -> list[EvidenceDefinition]:
    """Build ``EvidenceDefinition`` objects for all hosts × definitions.

    :returns: Flat list of evidence definitions.
    """
    host_meta = {h["ansible_host"]: h for h in host_details}
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
                        "ssh_user": meta.get("ansible_user", ""),
                        "become_user": meta.get("become_user", ""),
                        "node_tier": meta.get("node_tier", ""),
                        "source": cd.source,
                        "ok_exit_codes": cd.ok_exit_codes,
                    },
                )
            )
    return evidence_defs


def _build_summary(report: Any) -> str:
    """Build a human-readable summary from a triage report.

    :param report: ``TriageReport`` instance.
    :returns: Summary string.
    """
    if not report.findings:
        return (
            f"No issues found. Evaluated {report.rules_evaluated} rules "
            f"against {report.evidence_count} evidence artifacts."
        )
    critical = sum(1 for f in report.findings if f.severity == "critical")
    high = sum(1 for f in report.findings if f.severity == "high")
    parts = [f"{report.finding_count} finding(s)"]
    if critical:
        parts.append(f"{critical} critical")
    if high:
        parts.append(f"{high} high")
    return f"Found {', '.join(parts)} from {report.rules_evaluated} rules."
