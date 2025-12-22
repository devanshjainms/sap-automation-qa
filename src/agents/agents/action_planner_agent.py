# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""Semantic Kernel-powered Action Planner agent.

This agent produces a validated ActionPlan (jobs) for a request.
It does NOT execute actions.

It is the single planner for:
- operational diagnostics (multi-command / multi-log workflows)
- test/validation execution (jobs that call execution.* tools)
"""

from __future__ import annotations

from typing import Optional

from semantic_kernel import Kernel

from src.agents.agents.base import SAPAutomationAgent
from src.agents.observability import get_logger
from src.agents.plugins.action_planner import ActionPlannerPlugin
from src.agents.plugins.test import TestPlannerPlugin
from src.agents.plugins.workspace import WorkspacePlugin
from src.agents.workspace.workspace_store import WorkspaceStore
from src.agents.prompts import ACTION_PLANNER_AGENT_SYSTEM_PROMPT
from src.agents.models.action import ActionPlan, ActionJob
import json
import uuid

logger = get_logger(__name__)


class ActionPlannerAgentSK(SAPAutomationAgent):
    """Plans work as an ActionPlan (jobs)."""

    def __init__(
        self,
        kernel: Kernel,
        workspace_store: WorkspaceStore,
        action_planner_plugin: Optional[ActionPlannerPlugin] = None,
        test_planner_plugin: Optional[TestPlannerPlugin] = None,
    ) -> None:
        action_planner = action_planner_plugin or ActionPlannerPlugin()
        test_planner = test_planner_plugin or TestPlannerPlugin()
        workspace_plugin = WorkspacePlugin(workspace_store)

        super().__init__(
            name="action_planner",
            description=(
                "Plans operational diagnostics and test/validation runs as a multi-step ActionPlan. "
                "Produces jobs but does not execute them."
            ),
            kernel=kernel,
            instructions=ACTION_PLANNER_AGENT_SYSTEM_PROMPT,
            plugins=[action_planner, test_planner, workspace_plugin],
        )

        object.__setattr__(self, "workspace_store", workspace_store)
        object.__setattr__(self, "action_planner_plugin", action_planner)
        object.__setattr__(self, "test_planner_plugin", test_planner)

        logger.info("ActionPlannerAgentSK initialized")

    def normalize_action_plan(self, raw: str | dict) -> ActionPlan:
        """Normalize and validate a raw ActionPlan JSON or dict into ActionPlan model.

        This fills missing required fields (job_id, title, destructive) with
        sensible defaults so downstream systems receive a well-formed plan.
        """
        if isinstance(raw, str):
            try:
                data = json.loads(raw)
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSON for ActionPlan: {e}") from e
        else:
            data = raw

        jobs = data.get("jobs", []) or []
        normalized_jobs: list[dict] = []
        for idx, j in enumerate(jobs):
            if not isinstance(j, dict):
                raise ValueError(f"ActionPlan job must be an object, got: {type(j)}")
            job = dict(j)  # shallow copy
            if "job_id" not in job or not job.get("job_id"):
                job["job_id"] = f"job-{idx+1}-{uuid.uuid4().hex[:6]}"
            if "title" not in job or not job.get("title"):
                plugin = job.get("plugin_name") or job.get("plugin") or "unknown"
                func = job.get("function_name") or job.get("function") or "action"
                job["title"] = f"{plugin}.{func}"
            if "function_name" not in job and "function" in job:
                job["function_name"] = job.pop("function")
            if "plugin_name" not in job and "plugin" in job:
                job["plugin_name"] = job.pop("plugin")
            if "arguments" not in job or job["arguments"] is None:
                job["arguments"] = {}
            if "destructive" not in job:
                job["destructive"] = False
            normalized_jobs.append(job)

        normalized: dict = dict(data)
        normalized["jobs"] = normalized_jobs

        try:
            plan = ActionPlan(**normalized)
        except Exception as e:
            logger.error(f"Failed to validate normalized ActionPlan: {e}")
            raise

        # store the last generated plan in plugin if available
        try:
            if hasattr(self, "action_planner_plugin") and getattr(self.action_planner_plugin, "_last_generated_plan", None) is None:
                object.__setattr__(self.action_planner_plugin, "_last_generated_plan", plan)
        except Exception:
            # non-fatal; plugin storage is a convenience
            logger.debug("Could not store last_generated_plan on plugin")

        return plan
