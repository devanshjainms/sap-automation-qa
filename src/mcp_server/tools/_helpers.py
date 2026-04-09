# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Shared helpers for MCP tool implementations."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from mcp.types import Icon

from src.core.models.evidence import EvidenceArtifact
from src.core.models.triage import TriageSession

_SVG = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23555' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E{0}%3C/svg%3E"  # noqa: E501


def _icon(body: str) -> Icon:
    return Icon(src=_SVG.format(body))


# Schedule / calendar
ICON_CALENDAR = _icon(
    "%3Crect x='3' y='4' width='18' height='18' rx='2'/%3E"
    "%3Cline x1='16' y1='2' x2='16' y2='6'/%3E"
    "%3Cline x1='8' y1='2' x2='8' y2='6'/%3E"
    "%3Cline x1='3' y1='10' x2='21' y2='10'/%3E"
)
ICON_PLAY = _icon("%3Cpolygon points='5,3 19,12 5,21'/%3E")
ICON_LIST = _icon(
    "%3Cline x1='8' y1='6' x2='21' y2='6'/%3E"
    "%3Cline x1='8' y1='12' x2='21' y2='12'/%3E"
    "%3Cline x1='8' y1='18' x2='21' y2='18'/%3E"
    "%3Cline x1='3' y1='6' x2='3.01' y2='6'/%3E"
    "%3Cline x1='3' y1='12' x2='3.01' y2='12'/%3E"
    "%3Cline x1='3' y1='18' x2='3.01' y2='18'/%3E"
)
ICON_CLIPBOARD = _icon(
    "%3Cpath d='M16 4h2a2 2 0 012 2v14a2 2 0 01-2 2H6a2 2 0 01-2-2V6a2 2 0 012-2h2'/%3E"
    "%3Crect x='8' y='2' width='8' height='4' rx='1'/%3E"
)
ICON_SEARCH = _icon(
    "%3Ccircle cx='11' cy='11' r='8'/%3E" "%3Cline x1='21' y1='21' x2='16.65' y2='16.65'/%3E"
)
ICON_CHART = _icon(
    "%3Cline x1='18' y1='20' x2='18' y2='10'/%3E"
    "%3Cline x1='12' y1='20' x2='12' y2='4'/%3E"
    "%3Cline x1='6' y1='20' x2='6' y2='14'/%3E"
)
ICON_BOOK = _icon(
    "%3Cpath d='M4 19.5A2.5 2.5 0 016.5 17H20'/%3E"
    "%3Cpath d='M4 19.5V4.5A2.5 2.5 0 016.5 2H20v20H6.5A2.5 2.5 0 014 19.5z'/%3E"
)
ICON_FILE = _icon(
    "%3Cpath d='M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z'/%3E"
    "%3Cline x1='16' y1='13' x2='8' y2='13'/%3E"
    "%3Cline x1='16' y1='17' x2='8' y2='17'/%3E"
    "%3Cpolyline points='10,9 9,9 8,9'/%3E"
)
ICON_FOLDER = _icon(
    "%3Cpath d='M22 19a2 2 0 01-2 2H4a2 2 0 01-2-2V5a2 2 0 012-2h5l2 3h9a2 2 0 012 2z'/%3E"
)
ICON_TERMINAL = _icon(
    "%3Cpolyline points='4,17 10,11 4,5'/%3E" "%3Cline x1='12' y1='19' x2='20' y2='19'/%3E"
)
ICON_CANCEL = _icon(
    "%3Ccircle cx='12' cy='12' r='10'/%3E"
    "%3Cline x1='15' y1='9' x2='9' y2='15'/%3E"
    "%3Cline x1='9' y1='9' x2='15' y2='15'/%3E"
)
ICON_TRASH = _icon(
    "%3Cpolyline points='3,6 5,6 21,6'/%3E"
    "%3Cpath d='M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6'/%3E"
    "%3Cpath d='M10 11v6'/%3E%3Cpath d='M14 11v6'/%3E"
)
ICON_EDIT = _icon(
    "%3Cpath d='M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7'/%3E"
    "%3Cpath d='M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z'/%3E"
)
ICON_ACTIVITY = _icon("%3Cpolyline points='22,12 18,12 15,21 9,3 6,12 2,12'/%3E")
ICON_LOG = _icon(
    "%3Cpath d='M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z'/%3E"
    "%3Cpolyline points='14,2 14,8 20,8'/%3E"
)


def load_workspace_params(workspaces_base: Path, workspace_id: str) -> dict[str, Any]:
    """Load sap-parameters.yaml for a workspace.

    :param workspaces_base: Base path to WORKSPACES/SYSTEM.
    :param workspace_id: Workspace directory name.
    :returns: Parsed YAML dict, or empty dict if not found.
    """
    params_file = workspaces_base / workspace_id / "sap-parameters.yaml"
    if not params_file.is_file():
        return {}
    with open(params_file, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_workspace_hosts(workspaces_base: Path, workspace_id: str) -> list[str]:
    """Parse host IPs/names from hosts.yaml Ansible inventory.

    Prefers ``ansible_host`` (IP) over the inventory key (hostname).

    :param workspaces_base: Base path to WORKSPACES/SYSTEM.
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

    :param workspaces_base: Base path to WORKSPACES/SYSTEM.
    :param workspace_id: Workspace directory name.
    :returns: List of host detail dicts. Empty if file not found.
    """
    hosts_file = workspaces_base / workspace_id / "hosts.yaml"
    if not hosts_file.is_file():
        return []

    with open(hosts_file, encoding="utf-8") as f:
        inventory = yaml.safe_load(f) or {}

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
