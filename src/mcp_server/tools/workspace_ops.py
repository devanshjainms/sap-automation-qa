# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Workspace ops — list and inspect SAP system workspaces."""

from __future__ import annotations

import logging
from typing import Any

from mcp.server.fastmcp import Context
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.session import ServerSession
from mcp.types import ToolAnnotations

from src.core.services.workspace_discovery import load_workspaces_from_directory
from src.mcp_server.server import SapContext, mcp
from src.mcp_server.tools._helpers import (
    get_sap_context,
    ICON_FOLDER,
    load_workspace_host_details,
    load_workspace_params,
)

logger = logging.getLogger(__name__)


@staticmethod
@mcp.tool(
    name="list_workspaces",
    title="List Workspaces",
    description=(
        "List available SAP system workspaces. Each workspace represents "
        "one SAP landscape (SID). Returns workspace IDs, names, and "
        "environment tags."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
    icons=[ICON_FOLDER],
    structured_output=False,
)
async def list_workspaces(
    ctx: Context[ServerSession, SapContext] | None = None,
) -> dict[str, Any]:
    """List available SAP system workspaces."""
    logger.info("Tool called: list_workspaces()")
    sap = get_sap_context(ctx)

    workspaces = load_workspaces_from_directory(base_dir=str(sap.workspaces_base))

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


@staticmethod
@mcp.tool(
    name="get_workspace",
    title="Get Workspace",
    description=(
        "Get details of a specific SAP workspace. Returns workspace ID, "
        "name, environment, path, host count, tier breakdown, and SAP "
        "system attributes (SID, platform, instance numbers, HA config, "
        "topology, NFS provider)."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
    icons=[ICON_FOLDER],
    structured_output=False,
)
async def get_workspace(
    workspace_id: str,
    ctx: Context[ServerSession, SapContext] | None = None,
) -> dict[str, Any]:
    """Get details of a specific SAP workspace."""
    logger.info("Tool called: get_workspace(workspace_id=%s)", workspace_id)
    sap = get_sap_context(ctx)
    sap.validator.workspace_id(workspace_id)

    workspaces = load_workspaces_from_directory(base_dir=str(sap.workspaces_base))
    for ws in workspaces:
        if ws.id == workspace_id:
            host_details = load_workspace_host_details(sap.workspaces_base, workspace_id)
            tiers: dict[str, list[str]] = {}
            for hd in host_details:
                tier = hd.get("node_tier", "unknown")
                tiers.setdefault(tier, []).append(hd["ansible_host"])

            params = load_workspace_params(sap.workspaces_base, workspace_id)
            sap_system = _extract_sap_attributes(params)

            return {
                "id": ws.id,
                "name": ws.name,
                "environment": ws.environment,
                "path": ws.path,
                "host_count": len(host_details),
                "tiers": tiers,
                "sap_system": sap_system,
            }
    raise ToolError(f"Workspace '{workspace_id}' not found")


_SAP_ATTRIBUTE_KEYS: tuple[str, ...] = (
    "sap_sid",
    "db_sid",
    "platform",
    "db_instance_number",
    "scs_instance_number",
    "ers_instance_number",
    "database_high_availability",
    "scs_high_availability",
    "database_scale_out",
    "database_no_standby",
    "database_cluster_type",
    "scs_cluster_type",
    "use_hanasr_angi",
    "use_simple_mount",
    "NFS_provider",
    "database_loadbalancer_ip",
    "scs_lb_ip",
    "ers_lb_ip",
    "sap_fqdn",
)


def _extract_sap_attributes(params: dict[str, Any]) -> dict[str, Any]:
    """Extract SAP system attributes from workspace parameters.

    :param params: Parsed sap-parameters.yaml dict.
    :returns: Dict containing only the keys in ``_SAP_ATTRIBUTE_KEYS``
        that are present and non-empty in *params*.
    """
    attrs: dict[str, Any] = {}
    for key in _SAP_ATTRIBUTE_KEYS:
        value = params.get(key)
        if value is not None and value != "":
            attrs[key] = value
    return attrs
