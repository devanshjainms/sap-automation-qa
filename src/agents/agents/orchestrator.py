# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""
Orchestrator powered by Semantic Kernel for routing chat requests to agents.

This orchestrator uses Semantic Kernel with AgentRoutingPlugin for intelligent
request routing using function calling.
"""

import json
import time
from typing import Optional
from semantic_kernel import Kernel
from semantic_kernel.contents import ChatHistory
from src.agents.models.chat import ChatRequest, ChatResponse, ChatMessage
from src.agents.agents.base import AgentRegistry, AgentTracer
from src.agents.plugins.routing import AgentRoutingPlugin
from src.agents.prompts import ORCHESTRATOR_SK_SYSTEM_PROMPT
from src.agents.models.execution import ExecutionRequest
from src.agents.models.reasoning import sanitize_snapshot
from src.agents.models.streaming import (
    emit_thinking_start,
    emit_thinking_step,
    emit_thinking_end,
)
from src.agents.observability import get_logger

logger = get_logger(__name__)


class OrchestratorSK:
    """Routes chat requests to appropriate agents using Semantic Kernel."""

    def __init__(self, registry: AgentRegistry, kernel: Kernel) -> None:
        """Initialize orchestrator with agent registry and Semantic Kernel.

        :param registry: AgentRegistry containing available agents
        :type registry: AgentRegistry
        :param kernel: Configured Semantic Kernel instance
        :type kernel: Kernel
        """
        self.registry = registry
        self.kernel = kernel
        self.tracer = AgentTracer(agent_name="orchestrator")
        routing_plugin = AgentRoutingPlugin(registry)
        self.kernel.add_plugin(plugin=routing_plugin, plugin_name="AgentRouting")
        logger.info("OrchestratorSK initialized with Semantic Kernel and AgentRouting plugin")

    async def _choose_agent_with_sk(self, request: ChatRequest) -> tuple[str, dict]:
        """Use Semantic Kernel to choose the best agent for the request.

        :param request: ChatRequest with conversation history
        :type request: ChatRequest
        :returns: Tuple of (agent_name, agent_input dict)
        :rtype: tuple[str, dict]
        """
        await emit_thinking_start()
        routing_step_id = await emit_thinking_step(
            agent="orchestrator",
            action="Analyzing request...",
            status="in_progress",
        )
        routing_start = time.time()

        chat_history = ChatHistory()
        chat_history.add_system_message(ORCHESTRATOR_SK_SYSTEM_PROMPT)

        for msg in request.messages:
            if msg.role == "user":
                chat_history.add_user_message(msg.content)
            elif msg.role == "assistant":
                chat_history.add_assistant_message(msg.content)

        agent_name = "echo"
        agent_input = {}
        routing_reason = "ok"
        sk_content_length = 0

        try:
            logger.info("Calling SK for agent routing with function calling...")
            chat_service = self.kernel.get_service(service_id="azure_openai_chat")
            execution_settings = chat_service.get_prompt_execution_settings_class()(
                function_choice_behavior="auto",
                max_completion_tokens=500,
            )

            response = await chat_service.get_chat_message_content(
                chat_history=chat_history,
                settings=execution_settings,
                kernel=self.kernel,
            )

            logger.info("SK routing response received")

            routing_json = None
            if response and hasattr(response, "items"):
                for item in response.items:
                    item_type = type(item).__name__
                    logger.info(f"Response item type: {item_type}")
                    if item_type == "FunctionResultContent":
                        result_str = str(item.result) if hasattr(item, "result") else str(item)
                        logger.info(f"Found function result: {result_str}")
                        if "agent_name" in result_str:
                            routing_json = result_str
                            break
            if not routing_json:
                for msg in reversed(chat_history.messages):
                    if hasattr(msg, "items"):
                        for item in msg.items:
                            item_str = str(item)
                            if "agent_name" in item_str and "{" in item_str:
                                start = item_str.find("{")
                                end = item_str.rfind("}") + 1
                                if start >= 0 and end > start:
                                    routing_json = item_str[start:end]
                                    logger.info(f"Found routing JSON in history: {routing_json}")
                                    break
                    if routing_json:
                        break
            for item in reversed(chat_history.messages):
                item_str = str(item)
                if "agent_name" in item_str and "{" in item_str:
                    try:
                        start_idx = item_str.find("{")
                        end_idx = item_str.rfind("}") + 1
                        routing_json = item_str[start_idx:end_idx]
                        logger.info(f"Found routing JSON in chat history: {routing_json}")
                        break
                    except Exception:
                        pass
            response_content = str(response) if response else ""
            sk_content_length = len(response_content)

            if not routing_json and "{" in response_content and "agent_name" in response_content:
                start_idx = response_content.find("{")
                end_idx = response_content.rfind("}") + 1
                routing_json = response_content[start_idx:end_idx]
                logger.info(f"Found routing JSON in response: {routing_json}")

            if routing_json:
                try:
                    routing_decision = json.loads(routing_json)
                    agent_name = routing_decision.get("agent_name", "echo")
                    agent_input = routing_decision.get("agent_input", {})
                    logger.info(f"Routing to agent: {agent_name} with input: {agent_input}")

                    if agent_name not in self.registry:
                        logger.warning(f"Agent {agent_name} not found, falling back to echo")
                        agent_name = "echo"
                        agent_input = {}
                        routing_reason = "agent_not_found"
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse routing decision JSON: {e}")
                    routing_reason = "json_parse_error"
            else:
                logger.warning("No routing JSON found, falling back to echo")
                routing_reason = "no_json"

        except Exception as e:
            logger.error(f"Error in SK routing: {type(e).__name__}: {e}", exc_info=e)
            routing_reason = f"exception:{type(e).__name__}"

        routing_duration = int((time.time() - routing_start) * 1000)
        await emit_thinking_step(
            agent="orchestrator",
            action=f"Routing to {agent_name}",
            detail=f"Selected {agent_name} agent to handle request",
            status="complete",
            step_id=routing_step_id,
            duration_ms=routing_duration,
        )

        self.tracer.step(
            "routing",
            "decision",
            "Agent routing decision based on SK response",
            input_snapshot=sanitize_snapshot({"message_count": len(request.messages)}),
            output_snapshot=sanitize_snapshot(
                {
                    "agent_name": agent_name,
                    "agent_input_keys": list(agent_input.keys()),
                    "routing_reason": routing_reason,
                    "sk_content_length": sk_content_length,
                }
            ),
        )

        return (agent_name, agent_input)

    async def handle_chat(
        self,
        request: ChatRequest,
        context: Optional[dict] = None,
    ) -> ChatResponse:
        """Route chat request to appropriate agent and return response.

        For operational/execution requests routed to the unified executor, this orchestrator will:
        1. Invoke ActionPlannerAgent to generate a validated ActionPlan (jobs)
        2. Invoke the unified executor (ActionExecutorAgent) with the ActionPlan
        3. Return the execution results

        :param request: ChatRequest with conversation history
        :type request: ChatRequest
        :param context: Optional metadata for agent execution
        :type context: Optional[dict]
        :returns: ChatResponse from the selected agent
        :rtype: ChatResponse
        :raises ValueError: If no suitable agent found
        """
        self.tracer.start()

        try:
            agent_name, agent_input = await self._choose_agent_with_sk(request)

            if agent_name == "action_executor":
                response = await self._handle_action_execution(request, agent_input, context)
                await emit_thinking_end()
                return response

            agent = self.registry.get(agent_name)
            if agent is None:
                raise ValueError(f"Agent '{agent_name}' not found in registry")

            if context is None:
                context = {}
            context["agent_input"] = agent_input

            agent_step_id = await emit_thinking_step(
                agent=agent_name,
                action=f"Processing with {agent_name}...",
                status="in_progress",
            )
            agent_start = time.time()

            response = await agent.run(messages=request.messages, context=context)

            agent_duration = int((time.time() - agent_start) * 1000)
            await emit_thinking_step(
                agent=agent_name,
                action=f"Completed {agent_name}",
                status="complete",
                step_id=agent_step_id,
                duration_ms=agent_duration,
            )

            await emit_thinking_end()

            orch_trace = self.tracer.get_trace()
            if orch_trace and response.reasoning_trace:
                orch_trace["steps"].extend(response.reasoning_trace.get("steps", []))
                response.reasoning_trace = orch_trace
            elif orch_trace:
                response.reasoning_trace = orch_trace

            return response

        except Exception as e:
            self.tracer.step(
                "response_generation",
                "inference",
                f"Error during orchestration: {str(e)}",
                error=str(e),
                output_snapshot=sanitize_snapshot({"error_type": type(e).__name__}),
            )
            raise

        finally:
            self.tracer.finish()

    async def _handle_action_execution(
        self,
        request: ChatRequest,
        agent_input: dict,
        context: Optional[dict] = None,
    ) -> ChatResponse:
        """Generate an ActionPlan via ActionPlannerAgent, then execute it via unified executor."""

        action_planner = self.registry.get("action_planner")
        if action_planner is None:
            raise ValueError("ActionPlannerAgent not found")

        planning_context = {"agent_input": agent_input} if context is None else {**context}
        planning_context["agent_input"] = agent_input

        planning_response = await action_planner.run(
            messages=request.messages,
            context=planning_context,
        )

        action_plan = getattr(planning_response, "action_plan", None)
        if not action_plan:
            logger.warning(
                "ActionPlannerAgent did not return ActionPlan; returning planner response"
            )
            return planning_response

        action_executor = self.registry.get("action_executor")
        if action_executor is None:
            raise ValueError("ActionExecutorAgent not found")

        execution_context = {"agent_input": agent_input, "action_plan": action_plan}
        if context:
            execution_context = {**context, **execution_context}

        execution_response = await action_executor.run(
            messages=request.messages,
            context=execution_context,
        )

        orch_trace = self.tracer.get_trace()
        if orch_trace:
            if planning_response.reasoning_trace:
                orch_trace["steps"].extend(planning_response.reasoning_trace.get("steps", []))
            if execution_response.reasoning_trace:
                orch_trace["steps"].extend(execution_response.reasoning_trace.get("steps", []))
            execution_response.reasoning_trace = orch_trace

        return execution_response


