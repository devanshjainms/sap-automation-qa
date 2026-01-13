# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""Semantic Kernel-powered Action Planner agent.

This agent produces a validated ActionPlan (jobs) for a request.
It does NOT execute actions.

It is the single planner for:
- operational diagnostics (multi-command / multi-log workflows)
- test/validation execution (jobs that call execution.* tools)

NOTE: This agent has NO hardcoded methods - all planning operations
are performed by the LLM autonomously calling plugin tools.
Validation/normalization is handled by src.agents.utils.action_plan_utils.
"""

from __future__ import annotations

from typing import Optional

from semantic_kernel import Kernel

from src.agents.agents.base import SAPAutomationAgent
from src.agents.observability import get_logger
from src.agents.plugins.action_planner import ActionPlannerPlugin
from src.agents.plugins.test import TestPlannerPlugin
from src.agents.plugins.workspace import WorkspacePlugin
from src.agents.plugins.troubleshooting import TroubleshootingPlugin
from src.agents.workspace.workspace_store import WorkspaceStore
from src.agents.prompts import ACTION_PLANNER_AGENT_SYSTEM_PROMPT

logger = get_logger(__name__)


class ActionPlannerAgentSK(SAPAutomationAgent):
    """Action Planner agent using Semantic Kernel.
    
    Plans test/diagnostic operations without executing.
    Investigation is AI-driven via ExecutionPlugin tools.
    """
    """Plans work as an ActionPlan (jobs).

    This agent uses SK's native function calling to create action plans,
    allowing the LLM to autonomously decide what jobs to include.

    All planning operations are handled via plugins:
    - ActionPlannerPlugin: Create and validate action plans
    - TestPlannerPlugin: Query available tests and groups
    - WorkspacePlugin: Access workspace configuration (hosts.yaml, sap-parameters.yaml)

    Post-processing validation is handled by:
    - src.agents.utils.normalize_action_plan() - called by orchestrator, not agent
    """

    def __init__(
        self,
        kernel: Kernel,
        workspace_store: WorkspaceStore,
        action_planner_plugin: Optional[ActionPlannerPlugin] = None,
        test_planner_plugin: Optional[TestPlannerPlugin] = None,
        troubleshooting_plugin: Optional[TroubleshootingPlugin] = None,
    ) -> None:
        action_planner = action_planner_plugin or ActionPlannerPlugin()
        test_planner = test_planner_plugin or TestPlannerPlugin()
        workspace_plugin = WorkspacePlugin(workspace_store)
        troubleshooting = troubleshooting_plugin or TroubleshootingPlugin(workspace_store)

        super().__init__(
            name="action_planner",
            description=(
                "Plans operational diagnostics and test/validation runs as a multi-step ActionPlan. "
                "Produces jobs but does not execute them."
            ),
            kernel=kernel,
            instructions=ACTION_PLANNER_AGENT_SYSTEM_PROMPT,
            plugins=[action_planner, test_planner, workspace_plugin, troubleshooting],
        )

        self.workspace_store: WorkspaceStore = workspace_store
        self.action_planner_plugin: ActionPlannerPlugin = action_planner
        self.test_planner_plugin: TestPlannerPlugin = test_planner
        self.troubleshooting_plugin: TroubleshootingPlugin = troubleshooting

        logger.info("ActionPlannerAgentSK initialized")
