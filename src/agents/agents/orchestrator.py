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

    async def handle_chat(
        self,
        request: ChatRequest,
        context: Optional[dict] = None,
    ) -> ChatResponse:
        """Route chat request to appropriate agents and return response.

        Supports multi-agent workflows by looping until a final answer is produced.

        :param request: ChatRequest with conversation history
        :type request: ChatRequest
        :param context: Optional metadata for agent execution
        :type context: Optional[dict]
        :returns: ChatResponse from the selected agent(s)
        :rtype: ChatResponse
        """
        from src.agents.models.streaming import emit_thinking_start

        await emit_thinking_start()

        self.tracer.start()
        agent_chain = ["orchestrator"]

        parent_step = self.tracer.step(
            "routing",
            "inference",
            "Starting multi-agent orchestration loop",
            input_snapshot=sanitize_snapshot({"message_count": len(request.messages)}),
        )
        parent_step_id = parent_step.id if parent_step else None
        combined_trace = self.tracer.get_trace() or {"steps": []}

        chat_history = ChatHistory()
        chat_history.add_system_message(ORCHESTRATOR_SK_SYSTEM_PROMPT)
        for msg in request.messages:
            if msg.role == "user":
                chat_history.add_user_message(msg.content)
            elif msg.role == "assistant":
                chat_history.add_assistant_message(msg.content)

        chat_service = self.kernel.get_service(service_id="azure_openai_chat")
        execution_settings = chat_service.get_prompt_execution_settings_class()(
            function_choice_behavior="auto",
            max_completion_tokens=1000,
        )

        max_iterations = 10
        final_content = ""
        iteration_count = 0
        last_history_len = len(chat_history.messages)

        for i in range(max_iterations):
            iteration_count = i + 1
            logger.info(f"Orchestration iteration {iteration_count}/{max_iterations}")

            response = await chat_service.get_chat_message_content(
                chat_history=chat_history,
                settings=execution_settings,
                kernel=self.kernel,
            )

            new_messages = chat_history.messages[last_history_len:]
            routing_decision = self._extract_routing_decision(response, new_messages)
            last_history_len = len(chat_history.messages)

            if routing_decision:
                agent_name = routing_decision.get("agent_name")
                agent_input = routing_decision.get("agent_input", {})

                if agent_name:
                    agent = self.registry.get(agent_name)
                    if agent:
                        logger.info(f"Executing agent: {agent_name}")
                        agent_chain.append(agent_name)
                        agent_step_id = await emit_thinking_step(
                            agent=agent_name,
                            action=f"Agent {agent_name} is working...",
                            status="in_progress",
                            parent_step_id=parent_step_id,
                        )

                        agent_start = time.time()
                        agent_context = (context or {}).copy()
                        agent_context["agent_input"] = agent_input

                        agent_response = await agent.run(
                            messages=request.messages, context=agent_context
                        )

                        agent_duration = int((time.time() - agent_start) * 1000)
                        await emit_thinking_step(
                            agent=agent_name,
                            action=f"Agent {agent_name} completed",
                            status="complete",
                            step_id=agent_step_id,
                            duration_ms=agent_duration,
                        )
                        if agent_response.reasoning_trace:
                            steps = agent_response.reasoning_trace.get("steps", [])
                            for step in steps:
                                if isinstance(step, dict):
                                    if "parent_step_id" not in step or not step["parent_step_id"]:
                                        step["parent_step_id"] = parent_step_id
                                elif hasattr(step, "parent_step_id"):
                                    if not step.parent_step_id:
                                        step.parent_step_id = parent_step_id
                            combined_trace["steps"].extend(steps)
                        agent_content = agent_response.messages[-1].content
                        chat_history.add_system_message(
                            f"OUTPUT FROM AGENT {agent_name}:\n{agent_content}"
                        )

                        continue
                    else:
                        logger.warning(f"Agent {agent_name} not found in registry")
                else:
                    logger.warning("No agent_name specified in routing decision")

            if response and response.content:
                final_content = str(response.content)
                break

        if not final_content:
            final_content = "I've consulted the specialized agents but couldn't produce a final summary. Please try rephrasing your request."

        final_step = self.tracer.step(
            "response_generation",
            "inference",
            "Orchestration complete",
            output_snapshot=sanitize_snapshot({"final_content": final_content}),
            parent_step_id=parent_step_id,
        )
        if final_step:
            combined_trace["steps"].append(final_step.model_dump())

        await emit_thinking_end()

        self.tracer.finish()
        return ChatResponse(
            messages=[ChatMessage(role="assistant", content=final_content)],
            agent_chain=agent_chain,
            reasoning_trace=combined_trace,
            metadata={"iterations": iteration_count},
        )

    def _extract_routing_decision(self, response, new_messages) -> Optional[dict]:
        """Helper to extract routing JSON from SK response or new messages."""
        routing_json = None

        logger.info("Extracting routing decision from response and new messages")

        if response and hasattr(response, "items"):
            for item in response.items:
                item_type = type(item).__name__
                if item_type == "FunctionResultContent":
                    result_str = str(item.result) if hasattr(item, "result") else str(item)
                    if "agent_name" in result_str:
                        routing_json = result_str
                        logger.info(f"Found routing JSON in response item: {routing_json}")
                        break

        if not routing_json:
            for msg in reversed(new_messages):
                if hasattr(msg, "items"):
                    for item in msg.items:
                        item_type = type(item).__name__
                        if item_type == "FunctionResultContent":
                            result_str = str(item.result) if hasattr(item, "result") else str(item)
                            if "agent_name" in result_str:
                                routing_json = result_str
                                logger.info(
                                    f"Found routing JSON in new message item: {routing_json}"
                                )
                                break
                    if routing_json:
                        break

                msg_str = str(msg)
                if "agent_name" in msg_str and "{" in msg_str:
                    start = msg_str.find("{")
                    end = msg_str.rfind("}") + 1
                    if start >= 0 and end > start:
                        routing_json = msg_str[start:end]
                        logger.info(f"Found routing JSON in new message string: {routing_json}")
                        break

        if routing_json:
            try:
                decision = json.loads(routing_json)
                if isinstance(decision, dict) and "agent_name" in decision:
                    logger.info(f"Successfully extracted routing decision: {decision}")
                    return decision
            except Exception as e:
                logger.error(f"Failed to parse routing JSON: {e}")

        return None
