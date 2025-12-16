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

from src.agents.agents.base import BaseSKAgent, TracingPhase
from src.agents.models.chat import ChatMessage, ChatResponse
from src.agents.models.reasoning import sanitize_snapshot
from src.agents.observability import get_logger
from src.agents.plugins.action_planner import ActionPlannerPlugin
from src.agents.plugins.test import TestPlannerPlugin
from src.agents.plugins.workspace import WorkspacePlugin
from src.agents.workspace.workspace_store import WorkspaceStore
from src.agents.prompts import ACTION_PLANNER_AGENT_SYSTEM_PROMPT

logger = get_logger(__name__)


class ActionPlannerAgentSK(BaseSKAgent):
    """Plans work as an ActionPlan (jobs)."""

    def __init__(
        self,
        kernel: Kernel,
        workspace_store: WorkspaceStore,
        action_planner_plugin: Optional[ActionPlannerPlugin] = None,
        test_planner_plugin: Optional[TestPlannerPlugin] = None,
    ) -> None:
        super().__init__(
            name="action_planner",
            description=(
                "Plans operational diagnostics and test/validation runs as a multi-step ActionPlan. "
                "Produces jobs but does not execute them."
            ),
            kernel=kernel,
            system_prompt=ACTION_PLANNER_AGENT_SYSTEM_PROMPT,
        )

        self.workspace_store = workspace_store

        self.action_planner_plugin = action_planner_plugin or ActionPlannerPlugin()
        self._safe_add_plugin(self.action_planner_plugin, "ActionPlannerPlugin")

        self.test_planner_plugin = test_planner_plugin or TestPlannerPlugin()
        self._safe_add_plugin(self.test_planner_plugin, "TestPlannerPlugin")

        self._safe_add_plugin(WorkspacePlugin(workspace_store), "workspace")

        logger.info("ActionPlannerAgentSK initialized")

    def _safe_add_plugin(self, plugin: object, plugin_name: str) -> None:
        try:
            self.kernel.add_plugin(plugin=plugin, plugin_name=plugin_name)
        except Exception as e:
            logger.info(f"Plugin '{plugin_name}' already registered or unavailable: {e}")

    def _get_tracing_phase(self) -> TracingPhase:
        return "execution_planning"

    def _process_response(
        self,
        response_content: str,
        context: Optional[dict] = None,
    ) -> ChatResponse:
        action_plan_dict = None

        if self.action_planner_plugin._last_generated_plan:
            action_plan_dict = self.action_planner_plugin._last_generated_plan.model_dump()
            self.tracer.step(
                "execution_planning",
                "decision",
                "ActionPlan generated",
                output_snapshot=sanitize_snapshot(
                    {
                        "workspace_id": action_plan_dict.get("workspace_id"),
                        "intent": action_plan_dict.get("intent"),
                        "jobs": len(action_plan_dict.get("jobs", [])),
                    }
                ),
            )
            self.action_planner_plugin._last_generated_plan = None

        return ChatResponse(
            messages=[ChatMessage(role="assistant", content=response_content)],
            action_plan=action_plan_dict,
            reasoning_trace=self.tracer.get_trace(),
            metadata=None,
        )
