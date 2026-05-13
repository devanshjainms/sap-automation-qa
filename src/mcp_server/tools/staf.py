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
from src.mcp_server.tools._helpers import get_sap_context, tool_info, ICON_PLAY

logger = logging.getLogger(__name__)


@mcp.tool(
    name="run_staf_test",
    title="Run STAF Test",
    description=(
        "Trigger a STAF test — configuration check or HA functional test. "
        "Valid test_group values: ConfigurationChecks, "
        "DatabaseHighAvailability, SCSHighAvailability. "
        "Returns a job_id to poll with get_job_status."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=False,
        openWorldHint=True,
    ),
    icons=[ICON_PLAY],
    structured_output=False,
)
async def run_staf_test(
    workspace_id: str,
    test_group: str,
    test_ids: list[str] | None = None,
    ctx: Context[ServerSession, SapContext] | None = None,
) -> dict[str, Any]:
    """Trigger a STAF test — configuration check or HA functional test."""
    sap = get_sap_context(ctx)

    await tool_info(ctx, f"Submitting STAF test: {test_group} on {workspace_id}")

    sap.validator.workspace_id(workspace_id)

    if test_group not in TEST_GROUP_PLAYBOOKS:
        valid = sorted(TEST_GROUP_PLAYBOOKS)
        raise ToolError(f"Unknown test_group '{test_group}'. Valid: {valid}")

    job = Job(
        workspace_id=workspace_id,
        test_group=test_group,
        test_ids=test_ids or [],
    )
    submitted = await sap.job_worker.submit_job(job)

    return {
        "job_id": str(submitted.id),
        "workspace_id": workspace_id,
        "test_group": test_group,
        "status": submitted.status,
    }
