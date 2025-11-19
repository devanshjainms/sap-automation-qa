# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""
Orchestrator for routing chat requests to agents.
"""

import json
import logging
from typing import Optional

from src.agents.models.chat import ChatRequest, ChatResponse, ChatMessage
from src.agents.agents.base import AgentRegistry
from src.agents.llm_client import call_llm
from src.agents.prompts import ORCHESTRATOR_ROUTING_SYSTEM_PROMPT
from src.agents.models.execution import ExecutionRequest
from src.agents.logging_config import get_logger

logger = get_logger(__name__)


class Orchestrator:
    """Routes chat requests to appropriate agents."""

    def __init__(self, registry: AgentRegistry) -> None:
        """Initialize orchestrator with agent registry.

        :param registry: AgentRegistry containing available agents
        :type registry: AgentRegistry
        """
        self.registry = registry

    async def _choose_agent_with_llm(self, request: ChatRequest) -> tuple[str, dict]:
        """Use LLM to choose the best agent for the request.

        :param request: ChatRequest with conversation history
        :type request: ChatRequest
        :returns: Tuple of (agent_name, agent_input dict)
        :rtype: tuple[str, dict]
        """
        available_agents = self.registry.list_agents()
        agents_description = "\n".join(
            [f"- {agent['name']}: {agent['description']}" for agent in available_agents]
        )

        system_prompt = ORCHESTRATOR_ROUTING_SYSTEM_PROMPT.format(
            agents_description=agents_description
        )

        llm_messages = [{"role": "system", "content": system_prompt}]
        for msg in request.messages:
            llm_messages.append({"role": msg.role, "content": msg.content})

        try:
            logger.info("Calling Azure OpenAI for agent routing...")
            response = await call_llm(llm_messages)
            logger.info(f"LLM response received: {response}")
            content_clean = response.choices[0].message.content.strip()
            logger.info(f"LLM content: {content_clean}")
            if content_clean.startswith("```json"):
                content_clean = content_clean[7:]
                if content_clean.endswith("```"):
                    content_clean = content_clean[:-3]
            elif content_clean.startswith("```"):
                content_clean = content_clean[3:]
                if content_clean.endswith("```"):
                    content_clean = content_clean[:-3]

            routing_decision = json.loads(content_clean.strip())

            agent_name = routing_decision.get("agent_name", "echo")
            agent_input = routing_decision.get("agent_input", {})

            logger.info(f"Routing to agent: {agent_name} with input: {agent_input}")
            if agent_name not in self.registry:
                logger.warning(f"Agent {agent_name} not found, falling back to echo")
                return ("echo", {})

            return (agent_name, agent_input)

        except Exception as e:
            logger.error(f"Error in LLM routing: {type(e).__name__}: {e}", exc_info=True)
            return ("echo", {})

    async def handle_chat(
        self,
        request: ChatRequest,
        context: Optional[dict] = None,
    ) -> ChatResponse:
        """Route chat request to appropriate agent and return response.

        For test execution requests, this orchestrator will:
        1. First route to TestPlannerAgent to generate a plan
        2. Then route to TestExecutorAgent with the generated plan
        3. Return the execution results

        :param request: ChatRequest with conversation history
        :type request: ChatRequest
        :param context: Optional metadata for agent execution
        :type context: Optional[dict]
        :returns: ChatResponse from the selected agent
        :rtype: ChatResponse
        :raises ValueError: If no suitable agent found
        """
        agent_name, agent_input = await self._choose_agent_with_llm(request)
        if agent_name == "test_executor":
            return await self._handle_test_execution(request, agent_input, context)
        agent = self.registry.get(agent_name)
        if agent is None:
            raise ValueError(f"Agent '{agent_name}' not found in registry")
        if context is None:
            context = {}
        context["agent_input"] = agent_input
        return await agent.run(messages=request.messages, context=context)

    async def _handle_test_execution(
        self,
        request: ChatRequest,
        agent_input: dict,
        context: Optional[dict] = None,
    ) -> ChatResponse:
        """Handle test execution by coordinating TestPlannerAgent -> TestExecutorAgent.

        :param request: Original chat request
        :type request: ChatRequest
        :param agent_input: Input extracted for the test executor
        :type agent_input: dict
        :param context: Optional context
        :type context: Optional[dict]
        :returns: ChatResponse from test execution
        :rtype: ChatResponse
        """
        try:
            logger.info("Generating test plan for execution request...")

            test_planner = self.registry.get("test_planner")
            if test_planner is None:
                raise ValueError("TestPlannerAgent not found")
            planning_context = (
                {"agent_input": agent_input}
                if context is None
                else {**context, "agent_input": agent_input}
            )
            planning_response = await test_planner.run(
                messages=request.messages, context=planning_context
            )
            test_plan = None
            if planning_response.test_plan:
                test_plan = planning_response.test_plan
                logger.info(
                    f"Retrieved test plan from TestPlannerAgent: "
                    + f"workspace={test_plan.get('workspace_id')}, "
                    + f"tests={test_plan.get('total_tests', 0)}"
                )
            else:
                logger.warning("TestPlannerAgent did not return a structured test plan")
                last_message = (
                    planning_response.messages[-1].content if planning_response.messages else ""
                )
                if "test_plan" in last_message.lower() or "{" in last_message:
                    try:
                        start_idx = last_message.find("{")
                        end_idx = last_message.rfind("}") + 1
                        if start_idx >= 0 and end_idx > start_idx:
                            json_str = last_message[start_idx:end_idx]
                            test_plan = json.loads(json_str)
                            logger.info("Extracted test plan from message content")
                    except (json.JSONDecodeError, ValueError) as e:
                        logger.error(f"Failed to parse JSON from message: {e}")

            if not test_plan:
                last_message = (
                    planning_response.messages[-1].content if planning_response.messages else ""
                )
                if "success" in last_message.lower() or "completed" in last_message.lower():
                    logger.info("Test executed successfully without formal test plan generation")
                    return planning_response
                else:
                    logger.warning("No test plan generated, returning planner response")
                    return planning_response

            execution_request = ExecutionRequest(
                workspace_id=agent_input.get("workspace_id", test_plan.get("workspace_id", "")),
                include_destructive=False,
                mode="selected" if agent_input.get("test_filter") else "all_safe",
            )

            logger.info("Executing test plan...")

            test_executor = self.registry.get("test_executor")
            if test_executor is None:
                raise ValueError("TestExecutorAgent not found")

            execution_context = {
                "test_plan": test_plan,
                "execution_request": execution_request.dict(),
                "agent_input": agent_input,
            }
            execution_response = await test_executor.run(
                messages=request.messages, context=execution_context
            )

            return execution_response

        except Exception as e:
            logger.error(f"Error in test execution orchestration: {e}")
            return ChatResponse(
                messages=[
                    ChatMessage(
                        role="assistant", content=f"Error orchestrating test execution: {str(e)}"
                    )
                ]
            )
