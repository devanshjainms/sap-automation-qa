# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""Semantic Kernel-powered Test Advisor agent.

This agent recommends/selects tests and produces a structured TestPlan.
It does NOT produce executable jobs.
"""

from __future__ import annotations

from typing import Optional

from semantic_kernel import Kernel

from src.agents.agents.base import BaseSKAgent, TracingPhase
from src.agents.models.chat import ChatMessage, ChatResponse
from src.agents.models.reasoning import sanitize_snapshot
from src.agents.observability import get_logger
from src.agents.plugins.test import TestPlannerPlugin
from src.agents.prompts import TEST_ADVISOR_AGENT_SYSTEM_PROMPT
from src.agents.workspace.workspace_store import WorkspaceStore

logger = get_logger(__name__)


class TestAdvisorAgentSK(BaseSKAgent):
    """Recommends tests and generates TestPlan (no execution jobs)."""

    def __init__(self, kernel: Kernel, workspace_store: WorkspaceStore):
        super().__init__(
            name="test_advisor",
            description=(
                "Recommends SAP HA tests based on workspace configuration and generates a TestPlan. "
                "Does not execute and does not generate ActionPlan jobs."
            ),
            kernel=kernel,
            system_prompt=TEST_ADVISOR_AGENT_SYSTEM_PROMPT,
        )

        self.workspace_store = workspace_store

        self.test_planner_plugin = TestPlannerPlugin()
        self.kernel.add_plugin(plugin=self.test_planner_plugin, plugin_name="TestPlannerPlugin")

        logger.info("TestAdvisorAgentSK initialized")

    def _get_tracing_phase(self) -> TracingPhase:
        return "test_selection"

    def _process_response(
        self,
        response_content: str,
        context: Optional[dict] = None,
    ) -> ChatResponse:
        test_plan_dict = None

        if self.test_planner_plugin._last_generated_plan:
            test_plan_dict = self.test_planner_plugin._last_generated_plan.model_dump()
            self.tracer.step(
                "test_selection",
                "decision",
                "Test plan generated successfully",
                output_snapshot=sanitize_snapshot(
                    {
                        "workspace_id": test_plan_dict.get("workspace_id"),
                        "total_tests": test_plan_dict.get("total_tests"),
                        "safe_tests": len(test_plan_dict.get("safe_tests", [])),
                        "destructive_tests": len(test_plan_dict.get("destructive_tests", [])),
                    }
                ),
            )
            self.test_planner_plugin._last_generated_plan = None

        return ChatResponse(
            messages=[ChatMessage(role="assistant", content=response_content)],
            test_plan=test_plan_dict,
            reasoning_trace=self.tracer.get_trace(),
            metadata=None,
        )
