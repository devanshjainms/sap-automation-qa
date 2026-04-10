# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Triage evidence tools — catalog, collection, and execution."""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from mcp.server.fastmcp import Context
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.session import ServerSession
from mcp.types import ToolAnnotations
from src.core.execution.evidence_collector import EvidenceDefinition
from src.core.execution.ssh_collector import SshCollectorStrategy
from src.core.models.evidence import CollectorType, EvidenceArtifact, EvidenceType
from src.core.models.knowledge import EvidenceCollectorDef
from src.core.models.ssh import SshCredential
from src.core.models.triage import TriageSession
from src.mcp_server.server import SapContext, mcp
from src.mcp_server.tools._helpers import (
    get_sap_context,
    tool_progress,
    tool_info,
    ICON_LIST,
    ICON_SEARCH,
    ICON_TERMINAL,
    load_workspace_host_details,
    load_workspace_params,
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
    sap = get_sap_context(ctx)

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
    sap = get_sap_context(ctx)

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
        await tool_info(ctx, f"Provisioning SSH credentials for workspace {workspace_id}")
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
            "No evidence definitions found in the knowledge store. " "Ensure seed data is loaded."
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

    await tool_info(
        ctx,
        f"Collecting evidence from {len(hosts)} host(s) "
        f"({len(evidence_defs)} definitions, tiers={target_tiers or 'all'})",
    )

    total_defs = len(evidence_defs)
    try:
        await tool_progress(ctx, progress=0.0, total=1.0, message="Connecting to target host...")

        def _collect() -> list[EvidenceArtifact]:
            return sap.triage_executor.collect(session, evidence_defs)

        artifacts = await loop.run_in_executor(None, _collect)

        for i, artifact in enumerate(artifacts, 1):
            pct = i / max(total_defs, 1)
            await tool_progress(
                ctx,
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
    sap = get_sap_context(ctx)

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
