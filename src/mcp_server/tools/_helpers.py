# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Shared helpers for MCP tool implementations."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from src.core.models.evidence import EvidenceArtifact
from src.core.models.triage import TriageSession


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

    :param workspaces_base: Base path to WORKSPACES/SYSTEM.
    :param workspace_id: Workspace directory name.
    :returns: List of host names/IPs. Empty if file not found.
    """
    hosts_file = workspaces_base / workspace_id / "hosts.yaml"
    if not hosts_file.is_file():
        return []

    with open(hosts_file, encoding="utf-8") as f:
        inventory = yaml.safe_load(f) or {}

    hosts: list[str] = []

    def _extract_hosts(node: Any) -> None:
        if not isinstance(node, dict):
            return
        if "hosts" in node and isinstance(node["hosts"], dict):
            hosts.extend(node["hosts"].keys())
        if "children" in node and isinstance(node["children"], dict):
            for child in node["children"].values():
                _extract_hosts(child)

    all_group = inventory.get("all", inventory)
    _extract_hosts(all_group)
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
