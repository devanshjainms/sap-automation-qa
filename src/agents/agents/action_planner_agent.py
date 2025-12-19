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
        self.workspace_store = workspace_store

        self.action_planner_plugin = action_planner_plugin or ActionPlannerPlugin()
        self.test_planner_plugin = test_planner_plugin or TestPlannerPlugin()
        workspace_plugin = WorkspacePlugin(workspace_store)
        super().__init__(
            name="action_planner",
            description=(
                "Plans operational diagnostics and test/validation runs as a multi-step ActionPlan. "
                "Produces jobs but does not execute them."
            ),
            kernel=kernel,
            instructions=ACTION_PLANNER_AGENT_SYSTEM_PROMPT,
            plugins=[self.action_planner_plugin, self.test_planner_plugin, workspace_plugin],
        )

        logger.info("ActionPlannerAgentSK initialized")
