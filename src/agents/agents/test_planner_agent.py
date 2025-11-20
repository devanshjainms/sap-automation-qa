# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""
Semantic Kernel-powered Test Planner agent for SAP HA testing.
"""

import logging
from typing import Optional

from semantic_kernel import Kernel
from semantic_kernel.contents.chat_history import ChatHistory

from src.agents.models.chat import ChatMessage, ChatResponse
from src.agents.agents.base import Agent
from src.agents.plugins.test import TestPlannerPlugin
from src.agents.workspace.workspace_store import WorkspaceStore
from src.agents.prompts import TEST_PLANNER_AGENT_SYSTEM_PROMPT
from src.agents.models.reasoning import sanitize_snapshot
from src.agents.logging_config import get_logger

logger = get_logger(__name__)


class TestPlannerAgentSK(Agent):
    """Test Planner agent using Semantic Kernel with workspace and test planning plugins."""

    def __init__(self, kernel: Kernel, workspace_store: WorkspaceStore):
        """Initialize TestPlannerAgentSK with Semantic Kernel.

        :param kernel: Semantic Kernel instance with Azure OpenAI service
        :type kernel: Kernel
        :param workspace_store: WorkspaceStore for accessing workspace data
        :type workspace_store: WorkspaceStore
        """
        super().__init__(
            name="test_planner",
            description="Plans high availability tests for SAP systems using workspace data and "
            + f"test configurations. Can query workspace details and recommend appropriate tests.",
        )

        self.kernel = kernel
        self.workspace_store = workspace_store
        self.test_planner_plugin = TestPlannerPlugin()
        self.kernel.add_plugin(plugin=self.test_planner_plugin, plugin_name="TestPlannerPlugin")
        self._last_test_plan_json = None
        logger.info(
            "TestPlannerAgentSK initialized with Semantic Kernel, WorkspacePlugin, TestPlannerPlugin"
        )

    async def run(
        self,
        messages: list[ChatMessage],
        context: Optional[dict] = None,
    ) -> ChatResponse:
        """Generate an intelligent test plan using SK function calling.

        :param messages: Full conversation history
        :type messages: list[ChatMessage]
        :param context: Optional metadata
        :type context: Optional[dict]
        :returns: ChatResponse with test plan recommendations and optional structured TestPlan
        :rtype: ChatResponse
        """
        self.tracer.start()
        
        try:
            self.tracer.step(
                "system_capabilities",
                "tool_call",
                "Invoking SK with test planning plugins",
                input_snapshot=sanitize_snapshot({
                    "message_count": len(messages),
                    "has_agent_input": context and "agent_input" in context if context else False
                })
            )
            
            chat_history = ChatHistory()
            chat_history.add_system_message(TEST_PLANNER_AGENT_SYSTEM_PROMPT)
            for msg in messages:
                if msg.role == "user":
                    chat_history.add_user_message(msg.content)
                elif msg.role == "assistant":
                    chat_history.add_assistant_message(msg.content)
            chat_service = self.kernel.get_service(service_id="azure_openai_chat")
            execution_settings = chat_service.get_prompt_execution_settings_class()(
                function_choice_behavior="auto",
                max_completion_tokens=2000,
            )
            logger.info(
                "Calling SK chat completion with function calling enabled for test planning"
            )
            response = await chat_service.get_chat_message_content(
                chat_history=chat_history,
                settings=execution_settings,
                kernel=self.kernel,
            )

            logger.info("SK chat completion returned successfully for test planning")
            response_content = (
                str(response.content) if response.content else "No response generated"
            )

            test_plan_dict = None
            if self.test_planner_plugin._last_generated_plan:
                test_plan_dict = self.test_planner_plugin._last_generated_plan.model_dump()
                logger.info(
                    f"Attaching TestPlan to response: {test_plan_dict['workspace_id']} with "
                    + f"{test_plan_dict['total_tests']} tests"
                )
                self.tracer.step(
                    "test_selection",
                    "decision",
                    "Test plan generated successfully",
                    output_snapshot=sanitize_snapshot({
                        "workspace_id": test_plan_dict['workspace_id'],
                        "total_tests": test_plan_dict['total_tests'],
                        "safe_tests": len(test_plan_dict.get('safe_tests', [])),
                        "destructive_tests": len(test_plan_dict.get('destructive_tests', []))
                    })
                )
                
                self.test_planner_plugin._last_generated_plan = None

            return ChatResponse(
                messages=[ChatMessage(role="assistant", content=response_content)],
                test_plan=test_plan_dict,
                reasoning_trace=self.tracer.get_trace()
            )

        except Exception as e:
            logger.error(f"Error in TestPlannerAgentSK: {e}", exc_info=True)
            
            self.tracer.step(
                "test_selection",
                "inference",
                f"Error during test planning: {str(e)}",
                error=str(e),
                output_snapshot=sanitize_snapshot({"error_type": type(e).__name__})
            )
            
            raise
        
        finally:
            self.tracer.finish()
