# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Shared helpers for MCP tool implementations."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import yaml
from mcp.server.fastmcp import Context
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.session import ServerSession
from src.core.models.evidence import EvidenceArtifact
from src.core.models.triage import TriageSession
from src.mcp_server.server import SapContext
from src.core.services.workspace_discovery import get_workspace_backend
from src.core.services.workspace_backend import FilesystemBackend, WorkspaceBackend


def get_sap_context(
    ctx: Context[ServerSession, SapContext] | None,
) -> SapContext:
    """Extract ``SapContext`` from the MCP request context.

    :param ctx: The MCP tool context (may be None).
    :returns: The shared application context.
    :raises ToolError: If context is unavailable.
    """
    if ctx is None:
        raise ToolError("MCP context is not available")
    return ctx.request_context.lifespan_context


async def tool_info(
    ctx: Context[ServerSession, SapContext] | None,
    message: str,
) -> None:
    """Log an info message via the MCP context (no-op if ctx is None).

    :param ctx: The MCP tool context.
    :param message: Message to log.
    """
    if ctx is not None:
        await ctx.info(message)


async def tool_progress(
    ctx: Context[ServerSession, SapContext] | None,
    progress: float,
    total: float,
    **kwargs: Any,
) -> None:
    """Report progress via the MCP context (no-op if ctx is None).

    :param ctx: The MCP tool context.
    :param progress: Current step.
    :param total: Total steps.
    :param kwargs: Extra keyword args forwarded to ``ctx.report_progress``.
    """
    if ctx is not None:
        await ctx.report_progress(progress, total, **kwargs)


def _effective_backend(workspaces_base: Path) -> WorkspaceBackend:
    """Return a backend that honours the *workspaces_base* parameter.

    When the singleton is a :class:`FilesystemBackend` whose base
    directory differs from *workspaces_base*, a one-off backend is
    returned so that callers that pass an explicit path still work.

    :param workspaces_base: Caller-supplied base path.
    :returns: Workspace backend to use for this call.
    """
    backend = get_workspace_backend()
    if isinstance(backend, FilesystemBackend):
        if str(backend._base) != str(workspaces_base):
            return FilesystemBackend(base_dir=str(workspaces_base))
    return backend


def load_workspace_params(workspaces_base: Path, workspace_id: str) -> dict[str, Any]:
    """Load sap-parameters.yaml for a workspace.

    Delegates to the active :class:`WorkspaceBackend`.  The
    *workspaces_base* parameter is retained for backward compatibility.

    :param workspaces_base: Base path (used for filesystem fallback).
    :param workspace_id: Workspace directory name.
    :returns: Parsed YAML dict, or empty dict if not found.
    """
    backend = _effective_backend(workspaces_base)
    return backend.read_yaml(workspace_id, "sap-parameters.yaml")


def load_workspace_hosts(workspaces_base: Path, workspace_id: str) -> list[str]:
    """Parse host IPs/names from hosts.yaml Ansible inventory.

    Prefers ``ansible_host`` (IP) over the inventory key (hostname).
    Delegates to the active :class:`WorkspaceBackend` for file I/O.

    :param workspaces_base: Base path (used for filesystem fallback).
    :param workspace_id: Workspace directory name.
    :returns: List of host addresses (IPs preferred). Empty if not found.
    """
    details = load_workspace_host_details(workspaces_base, workspace_id)
    return [h["ansible_host"] for h in details]


def load_workspace_host_details(workspaces_base: Path, workspace_id: str) -> list[dict[str, str]]:
    """Parse structured host info from hosts.yaml Ansible inventory.

    Returns a list of dicts with ``ansible_host`` (connect address),
    ``ansible_user``, ``become_user``, ``node_tier``, and ``name``
    (inventory key) for each host.

    Delegates to the active :class:`WorkspaceBackend` for file I/O.

    :param workspaces_base: Base path (used for filesystem fallback).
    :param workspace_id: Workspace directory name.
    :returns: List of host detail dicts. Empty if file not found.
    """
    backend = _effective_backend(workspaces_base)
    content = backend.read_file(workspace_id, "hosts.yaml")
    if content is None:
        return []

    inventory = yaml.safe_load(content) or {}

    hosts: list[dict[str, str]] = []

    def _extract_hosts(node: Any, tier: str = "") -> None:
        if not isinstance(node, dict):
            return
        group_tier = tier
        group_vars = node.get("vars")
        if isinstance(group_vars, dict) and "node_tier" in group_vars:
            group_tier = str(group_vars["node_tier"])
        if "hosts" in node and isinstance(node["hosts"], dict):
            for name, attrs in node["hosts"].items():
                attrs = attrs or {}
                hosts.append(
                    {
                        "name": str(name),
                        "ansible_host": str(attrs.get("ansible_host", name)),
                        "ansible_user": str(attrs.get("ansible_user", "")),
                        "become_user": str(attrs.get("become_user", "")),
                        "node_tier": group_tier,
                    }
                )
        if "children" in node and isinstance(node["children"], dict):
            for child in node["children"].values():
                _extract_hosts(child, group_tier)

    all_group = inventory.get("all")
    if all_group and isinstance(all_group, dict):
        _extract_hosts(all_group)
    else:
        for group in inventory.values():
            _extract_hosts(group)

    return hosts


def rebuild_artifacts(session: TriageSession) -> list[EvidenceArtifact]:
    """Reconstruct ``EvidenceArtifact`` objects from session evidence dicts."""
    artifacts: list[EvidenceArtifact] = []
    for ev in session.evidence:
        try:
            artifacts.append(
                EvidenceArtifact(
                    evidence_id=ev["evidence_id"],
                    evidence_type=ev["evidence_type"],
                    collector_type=ev["collector_type"],
                    status=ev["status"],
                    host=ev.get("host", ""),
                    command=ev.get("command", ""),
                    content=ev.get("content", ""),
                )
            )
        except (KeyError, TypeError):
            continue
    return artifacts
