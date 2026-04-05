# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""STAF tools — test execution."""

from __future__ import annotations

import logging
from typing import Any

import httpx
from mcp.server.fastmcp import Context
from mcp.server.session import ServerSession
from mcp.types import ToolAnnotations

from src.mcp_server.server import SapContext, mcp
from src.mcp_server.tools._helpers import ICON_PLAY

logger = logging.getLogger(__name__)


class StafTools:
    """STAF test execution."""

    @staticmethod
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
            destructiveHint=False,
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
        assert ctx is not None
        sap: SapContext = ctx.request_context.lifespan_context

        await ctx.info(f"Submitting STAF test: {test_group} on {workspace_id}")

        payload: dict[str, Any] = {
            "workspace_id": workspace_id,
            "test_group": test_group,
        }
        if test_ids:
            payload["test_ids"] = test_ids

        async with httpx.AsyncClient(
            base_url=sap.core_api_url, timeout=30.0
        ) as client:
            resp = await client.post("/api/v1/jobs", json=payload)
            resp.raise_for_status()
            job_data = resp.json()

        return {
            "job_id": job_data.get("id", job_data.get("job_id", "")),
            "workspace_id": workspace_id,
            "test_group": test_group,
            "status": job_data.get("status", "submitted"),
        }
