# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""MCP resources — expose workspace configurations and knowledge base.

Resources are read-only data the LLM can pull into its context
(like GET endpoints). They complement tools which perform actions.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import yaml
from mcp.server.fastmcp import Context
from mcp.server.session import ServerSession

from src.mcp_server.server import SapContext, mcp

logger = logging.getLogger(__name__)


@mcp.resource("workspace://{workspace_id}/config")
def get_workspace_config(
    workspace_id: str,
    ctx: Context[ServerSession, SapContext] | None = None,
) -> str:
    """Read the SAP parameters configuration for a workspace.

    Returns the ``sap-parameters.yaml`` content as text so the LLM
    can reason about the system's SID, topology, and HA setup.
    """
    assert ctx is not None
    sap: SapContext = ctx.request_context.lifespan_context
    config_path = sap.workspaces_base / workspace_id / "sap-parameters.yaml"

    if not config_path.exists():
        return json.dumps({"error": f"No configuration found for workspace {workspace_id}"})

    content = config_path.read_text(encoding="utf-8")

    # Parse and return as structured JSON for easier LLM consumption
    try:
        data = yaml.safe_load(content) or {}
        return json.dumps(data, indent=2, default=str)
    except yaml.YAMLError:
        return content


@mcp.resource("workspace://{workspace_id}/hosts")
def get_workspace_hosts(
    workspace_id: str,
    ctx: Context[ServerSession, SapContext] | None = None,
) -> str:
    """Read the Ansible inventory (hosts.yaml) for a workspace.

    Returns host groups and connection details the LLM can use to
    understand the cluster topology.
    """
    assert ctx is not None
    sap: SapContext = ctx.request_context.lifespan_context
    hosts_path = sap.workspaces_base / workspace_id / "hosts.yaml"

    if not hosts_path.exists():
        return json.dumps({"error": f"No hosts file found for workspace {workspace_id}"})

    content = hosts_path.read_text(encoding="utf-8")
    try:
        data = yaml.safe_load(content) or {}
        return json.dumps(data, indent=2, default=str)
    except yaml.YAMLError:
        return content


@mcp.resource("knowledge://rules")
def get_knowledge_rules(
    ctx: Context[ServerSession, SapContext] | None = None,
) -> str:
    """List all SAP-specific analysis rules in the knowledge base.

    Returns a JSON summary of every rule including its ID, name,
    severity, category, and description.
    """
    assert ctx is not None
    sap: SapContext = ctx.request_context.lifespan_context
    rules = sap.knowledge_store.load_rules()

    return json.dumps(
        [
            {
                "id": r.id,
                "name": r.name,
                "severity": r.severity,
                "category": r.category,
                "description": r.description,
                "tags": r.tags,
            }
            for r in rules
        ],
        indent=2,
        default=str,
    )


@mcp.resource("knowledge://playbooks")
def get_knowledge_playbooks(
    ctx: Context[ServerSession, SapContext] | None = None,
) -> str:
    """List all remediation playbooks in the knowledge base.

    Returns a JSON summary of every playbook including its ID, name,
    category, and symptoms it addresses.
    """
    assert ctx is not None
    sap: SapContext = ctx.request_context.lifespan_context
    playbooks = sap.knowledge_store.load_playbooks()

    return json.dumps(
        [
            {
                "id": p.id,
                "name": p.name,
                "category": p.category,
                "description": p.description,
                "symptoms": p.symptoms,
            }
            for p in playbooks
        ],
        indent=2,
        default=str,
    )
