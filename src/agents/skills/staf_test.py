# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
STAF Test Skill — full test lifecycle in one call.

Uses the Agent Framework ``Skill`` API with ``@skill.script`` to run
the complete STAF test lifecycle server-side: workspace validation,
job submission, polling, result retrieval, and structured interpretation.
All core services are accessed directly in-process (no MCP round-trips).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any

import httpx
from agent_framework import Skill, SkillResource, SkillScript

from src.agents.skills.strings import (
    STAF_DESCRIPTION,
    STAF_INSTRUCTIONS,
    STAF_NAME,
    STAF_RES_TEST_CATALOG_DESC,
    STAF_RES_TEST_CATALOG_NAME,
    STAF_SCRIPT_RUN_TEST_DESC,
    STAF_SCRIPT_RUN_TEST_NAME,
)

logger = logging.getLogger(__name__)

_POLL_INTERVAL_SECONDS = 5.0
_POLL_MAX_SECONDS = 1800  # 30 minutes
_TERMINAL_STATUSES = {"completed", "failed", "cancelled"}

_DB_HA_TESTS = [
    ("ha-config", "HA configuration validation", False),
    ("ha-config-offline", "HA configuration (offline)", False),
    ("azure-lb", "Azure Load Balancer validation", False),
    ("resource-migration", "Resource migration", True),
    ("primary-node-crash", "Primary node crash", True),
    ("primary-node-kill", "Primary node kill", True),
    ("primary-crash-index", "Primary indexserver crash", True),
    ("primary-echo-b", "Primary echo-b", True),
    ("secondary-node-kill", "Secondary node kill", True),
    ("secondary-crash-index", "Secondary indexserver crash", True),
    ("secondary-echo-b", "Secondary echo-b", True),
    ("block-network", "Network isolation", True),
    ("block-hana-shared", "HANA-shared isolation", True),
    ("fs-freeze", "Filesystem freeze (ANF)", True),
    ("sbd-fencing", "SBD fencing", True),
]

_SCS_HA_TESTS = [
    ("ha-config", "HA configuration validation", False),
    ("ha-config-offline", "HA configuration (offline)", False),
    ("azure-lb", "Azure Load Balancer validation", False),
    ("sapcontrol-config", "SAP control validation", False),
    ("ascs-migration", "ASCS migration", True),
    ("ascs-node-crash", "ASCS node crash", True),
    ("kill-message-server", "Kill message server", True),
    ("kill-enqueue-server", "Kill enqueue server", True),
    ("kill-enqueue-replication", "Kill enqueue replication", True),
    ("kill-sapstartsrv-process", "Kill SAPStartSrv process", True),
    ("manual-restart", "Manual restart", True),
    ("ha-failover-to-node", "Failover to node", True),
    ("block-network", "Network isolation", True),
]

_CONFIG_CHECK_TESTS = [
    ("configuration-checks", "Configuration validation", False),
]

_TEST_CATALOG: dict[str, list[tuple[str, str, bool]]] = {
    "DatabaseHighAvailability": _DB_HA_TESTS,
    "SCSHighAvailability": _SCS_HA_TESTS,
    "ConfigurationChecks": _CONFIG_CHECK_TESTS,
}


def build_staf_test_skill(sap_context: Any) -> Skill:
    """Build the STAF test skill with core services bound via closure.

    :param sap_context: ``SapContext`` from the MCP server lifespan.
    :returns: Configured ``Skill`` instance.
    """

    def get_test_catalog(**kwargs: Any) -> Any:
        """Return the test catalog grouped by test group."""
        lines: list[str] = []
        for group, tests in _TEST_CATALOG.items():
            lines.append(f"\n## {group}")
            lines.append("| Test ID | Description | Destructive |")
            lines.append("|---|---|---|")
            for test_id, desc, destructive in tests:
                flag = "Yes" if destructive else "No"
                lines.append(f"| {test_id} | {desc} | {flag} |")
        return "\n".join(lines)

    async def run_test(
        workspace_id: str,
        test_group: str,
        test_ids: str = "",
        **kwargs: Any,
    ) -> str:
        """Execute a STAF test end-to-end.

        :param workspace_id: Target workspace ID.
        :param test_group: Test group (ConfigurationChecks,
            DatabaseHighAvailability, SCSHighAvailability).
        :param test_ids: Comma-separated test IDs (optional, runs all
            in the group if omitted).
        :returns: JSON string with structured test results.
        """
        start = time.monotonic()
        steps: list[dict[str, Any]] = []

        try:
            # Validate test group
            if test_group not in _TEST_CATALOG:
                return json.dumps(
                    {
                        "status": "failed",
                        "error": (
                            f"Unknown test_group '{test_group}'. "
                            f"Valid groups: {list(_TEST_CATALOG.keys())}"
                        ),
                    }
                )

            parsed_ids: list[str] | None = None
            if test_ids.strip():
                parsed_ids = [t.strip() for t in test_ids.split(",") if t.strip()]
            steps.append(
                {
                    "step": "validate_input",
                    "status": "ok",
                    "detail": (f"Group: {test_group}, " f"Tests: {parsed_ids or 'all'}"),
                }
            )

            # Submit job via core API
            payload: dict[str, Any] = {
                "workspace_id": workspace_id,
                "test_group": test_group,
            }
            if parsed_ids:
                payload["test_ids"] = parsed_ids

            async with httpx.AsyncClient(base_url=sap_context.core_api_url, timeout=30.0) as client:
                resp = await client.post("/api/v1/jobs", json=payload)
                resp.raise_for_status()
                job_data = resp.json()

            job_id = job_data.get("id", job_data.get("job_id", ""))
            steps.append(
                {
                    "step": "submit_job",
                    "status": "ok",
                    "detail": f"Job ID: {job_id}",
                }
            )

            # Poll until terminal state
            final_status = await _poll_job(sap_context.core_api_url, job_id, steps)

            # Fetch results
            result_data = await _fetch_job_details(sap_context.core_api_url, job_id)
            log_text = await _fetch_job_log(sap_context.core_api_url, job_id)
            steps.append(
                {
                    "step": "fetch_results",
                    "status": "ok",
                    "detail": f"Final status: {final_status}",
                }
            )

            # Compile structured result
            duration_ms = int((time.monotonic() - start) * 1000)
            result = {
                "status": "completed",
                "job_id": job_id,
                "workspace_id": workspace_id,
                "test_group": test_group,
                "test_ids": parsed_ids,
                "job_status": final_status,
                "steps": steps,
                "duration_ms": duration_ms,
                "results": result_data,
                "log_excerpt": (log_text[-2000:] if log_text else ""),
            }
            return json.dumps(result, default=str)

        except Exception as exc:
            logger.exception("STAF test skill failed for workspace %s", workspace_id)
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
        name=STAF_NAME,
        description=STAF_DESCRIPTION,
        content=STAF_INSTRUCTIONS,
        resources=[
            SkillResource(
                name=STAF_RES_TEST_CATALOG_NAME,
                description=STAF_RES_TEST_CATALOG_DESC,
                function=get_test_catalog,
            ),
        ],
        scripts=[
            SkillScript(
                name=STAF_SCRIPT_RUN_TEST_NAME,
                description=STAF_SCRIPT_RUN_TEST_DESC,
                function=run_test,
            ),
        ],
    )
    return skill


async def _poll_job(
    core_api_url: str,
    job_id: str,
    steps: list[dict[str, Any]],
) -> str:
    """Poll job status until terminal with exponential backoff.

    :param core_api_url: Base URL of the core API.
    :param job_id: Job ID to poll.
    :param steps: Step log to append to.
    :returns: Final job status string.
    """
    elapsed = 0.0
    interval = _POLL_INTERVAL_SECONDS

    async with httpx.AsyncClient(base_url=core_api_url, timeout=15.0) as client:
        while elapsed < _POLL_MAX_SECONDS:
            await asyncio.sleep(interval)
            elapsed += interval

            try:
                resp = await client.get(f"/api/v1/jobs/{job_id}")
                resp.raise_for_status()
                data = resp.json()
                status = data.get("status", "unknown")
            except Exception as exc:
                logger.warning("Poll failed for job %s: %s", job_id, exc)
                interval = min(interval * 1.5, 30.0)
                continue

            if status in _TERMINAL_STATUSES:
                steps.append(
                    {
                        "step": "poll_complete",
                        "status": "ok",
                        "detail": (f"Job {status} after {int(elapsed)}s"),
                    }
                )
                return status

            interval = min(interval * 1.2, 30.0)

    steps.append(
        {
            "step": "poll_complete",
            "status": "timeout",
            "detail": f"Timed out after {int(elapsed)}s",
        }
    )
    return "timeout"


async def _fetch_job_details(core_api_url: str, job_id: str) -> dict[str, Any]:
    """Fetch job details from the core API.

    :param core_api_url: Base URL of the core API.
    :param job_id: Job ID.
    :returns: Job detail dict, or error dict on failure.
    """
    try:
        async with httpx.AsyncClient(base_url=core_api_url, timeout=15.0) as client:
            resp = await client.get(f"/api/v1/jobs/{job_id}")
            resp.raise_for_status()
            return resp.json()
    except Exception as exc:
        logger.warning("Failed to fetch job details for %s: %s", job_id, exc)
        return {"error": str(exc)}


async def _fetch_job_log(core_api_url: str, job_id: str) -> str:
    """Fetch job execution log from the core API.

    :param core_api_url: Base URL of the core API.
    :param job_id: Job ID.
    :returns: Log text, or empty string on failure.
    """
    try:
        async with httpx.AsyncClient(base_url=core_api_url, timeout=15.0) as client:
            resp = await client.get(f"/api/v1/jobs/{job_id}/log", params={"tail": 200})
            resp.raise_for_status()
            return resp.text
    except Exception as exc:
        logger.warning("Failed to fetch job log for %s: %s", job_id, exc)
        return ""
