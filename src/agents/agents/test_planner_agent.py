# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""
Semantic Kernel-powered Test Planner agent for SAP HA testing.
"""

from typing import Optional

from semantic_kernel import Kernel

from src.agents.models.chat import ChatMessage, ChatResponse
from src.agents.agents.base import BaseSKAgent, TracingPhase
from src.agents.plugins.test import TestPlannerPlugin
from src.agents.workspace.workspace_store import WorkspaceStore
from src.agents.prompts import TEST_PLANNER_AGENT_SYSTEM_PROMPT
from src.agents.models.reasoning import sanitize_snapshot
from src.agents.observability import get_logger

logger = get_logger(__name__)


class TestPlannerAgentSK(BaseSKAgent):
    """Test Planner agent using Semantic Kernel with workspace and test planning plugins.

    This agent generates intelligent test plans for SAP HA systems. It extends
    BaseSKAgent and overrides _process_response to extract structured test plans.
    """

    def __init__(self, kernel: Kernel, workspace_store: WorkspaceStore):
        """Initialize TestPlannerAgentSK with Semantic Kernel.

        :param kernel: Semantic Kernel instance with Azure OpenAI service
        :type kernel: Kernel
        :param workspace_store: WorkspaceStore for accessing workspace data
        :type workspace_store: WorkspaceStore
        """
        super().__init__(
            name="test_planner",
            description=(
                "Plans high availability tests for SAP systems using workspace data and "
                "test configurations. Can query workspace details and recommend appropriate tests."
            ),
            kernel=kernel,
            system_prompt=TEST_PLANNER_AGENT_SYSTEM_PROMPT,
        )

        self.workspace_store = workspace_store

        self.test_planner_plugin = TestPlannerPlugin()
        self.kernel.add_plugin(plugin=self.test_planner_plugin, plugin_name="TestPlannerPlugin")

        logger.info("TestPlannerAgentSK initialized with TestPlannerPlugin")

    def _get_tracing_phase(self) -> TracingPhase:
        """Return test_selection as the primary tracing phase."""
        return "test_selection"

    def _process_response(
        self,
        response_content: str,
        context: Optional[dict] = None,
    ) -> ChatResponse:
        """Process SK response and extract structured test plan if available.

        :param response_content: Raw response content from SK
        :type response_content: str
        :param context: Optional context dictionary
        :type context: Optional[dict]
        :returns: ChatResponse with test plan if generated
        :rtype: ChatResponse
        """
        test_plan_dict = None

        if self.test_planner_plugin._last_generated_plan:
            test_plan_dict = self.test_planner_plugin._last_generated_plan.model_dump()
            logger.info(
                f"Attaching TestPlan to response: {test_plan_dict['workspace_id']} with "
                f"{test_plan_dict['total_tests']} tests"
            )

            self.tracer.step(
                "test_selection",
                "decision",
                "Test plan generated successfully",
                output_snapshot=sanitize_snapshot(
                    {
                        "workspace_id": test_plan_dict["workspace_id"],
                        "total_tests": test_plan_dict["total_tests"],
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
