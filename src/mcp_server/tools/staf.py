# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""STAF tools — test execution."""

from __future__ import annotations
import logging
from typing import Any
from mcp.server.fastmcp import Context
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.session import ServerSession
from mcp.types import ToolAnnotations
from src.core.models.job import Job
from src.core.execution.executor import TEST_GROUP_PLAYBOOKS
from src.mcp_server.server import SapContext, mcp
from src.mcp_server.tools._helpers import get_sap_context, tool_info

logger = logging.getLogger(__name__)


@mcp.tool(
    name="run_staf_test",
    title="Run STAF Test",
    description=(
        "Run a specific STAF test on a workspace. You MUST specify test_ids — "
        "never call this without explicit test case names. "
        "Valid test_group values: DatabaseHighAvailability, "
        "CentralServicesHighAvailability, ConfigurationChecks. "
        "IMPORTANT: When user says 'ha-config' or 'HA configuration check', "
        "use test_group=DatabaseHighAvailability for HANA systems or "
        "test_group=CentralServicesHighAvailability for SCS systems — NOT ConfigurationChecks. "
        "ConfigurationChecks is for OS-level configuration checks only. "
        "Valid test_ids for DatabaseHighAvailability: ha-config, ha-config-offline, "
        "azure-lb, resource-migration, primary-node-crash, primary-node-kill, "
        "primary-crash-index, primary-echo-b, secondary-node-kill, "
        "secondary-crash-index, secondary-echo-b, block-network, "
        "block-hana-shared, fs-freeze, sbd-fencing. "
        "Valid test_ids for CentralServicesHighAvailability: ha-config, ha-config-offline, "
        "azure-lb, sapcontrol-config, "
        "ascs-migration, ascs-node-crash, kill-message-server, "
        "kill-enqueue-server, kill-enqueue-replication, "
        "kill-sapstartsrv-process, manual-restart, ha-failover-to-node, "
        "block-network. "
        "Valid test_ids for ConfigurationChecks: ha-config (OS-level only). "
        "Returns a job_id to poll with get_job_status."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=False,
        openWorldHint=True,
    ),
    structured_output=False,
)
async def run_staf_test(
    workspace_id: str,
    test_group: str,
    test_ids: list[str],
    ctx: Context[ServerSession, SapContext] | None = None,
) -> dict[str, Any]:
    """Run a specific STAF test on a workspace."""
    sap = get_sap_context(ctx)

    await tool_info(ctx, f"Submitting STAF test: {test_group}/{test_ids} on {workspace_id}")

    sap.validator.workspace_id(workspace_id)

    if test_group not in TEST_GROUP_PLAYBOOKS:
        valid = sorted(TEST_GROUP_PLAYBOOKS)
        raise ToolError(f"Unknown test_group '{test_group}'. Valid: {valid}")

    if not test_ids:
        raise ToolError(
            "test_ids is required — specify which test cases to run. "
            "Example: ['ha-config'] or ['primary-node-crash']"
        )

    job = Job(
        workspace_id=workspace_id,
        test_group=test_group,
        test_ids=test_ids,
    )
    submitted = await sap.job_worker.submit_job(job)

    return {
        "job_id": str(submitted.id),
        "workspace_id": workspace_id,
        "test_group": test_group,
        "test_ids": test_ids,
        "status": submitted.status,
    }
