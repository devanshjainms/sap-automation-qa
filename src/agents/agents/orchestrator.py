# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""
Orchestrator powered by Semantic Kernel for routing chat requests to agents.

This orchestrator uses Semantic Kernel with AgentRoutingPlugin for intelligent
request routing using function calling.
"""

import json
from typing import Optional
from semantic_kernel import Kernel
from semantic_kernel.contents import ChatHistory
from src.agents.models.chat import ChatRequest, ChatResponse, ChatMessage
from src.agents.agents.base import AgentRegistry, AgentTracer
from src.agents.plugins.routing import AgentRoutingPlugin
from src.agents.prompts import ORCHESTRATOR_SK_SYSTEM_PROMPT
from src.agents.models.execution import ExecutionRequest
from src.agents.models.reasoning import sanitize_snapshot
from src.agents.logging_config import get_logger

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

            response_content = str(response) if response else ""
            sk_content_length = len(response_content)
            try:
                if "{" in response_content and "}" in response_content:
                    start_idx = response_content.find("{")
                    end_idx = response_content.rfind("}") + 1
                    json_str = response_content[start_idx:end_idx]
                    routing_decision = json.loads(json_str)

                    agent_name = routing_decision.get("agent_name", "echo")
                    agent_input = routing_decision.get("agent_input", {})

                    logger.info(f"Routing to agent: {agent_name} with input: {agent_input}")

                    if agent_name not in self.registry:
                        logger.warning(f"Agent {agent_name} not found, falling back to echo")
                        agent_name = "echo"
                        agent_input = {}
                        routing_reason = "agent_not_found"
                else:
                    logger.warning("No JSON found in routing response, falling back to echo")
                    routing_reason = "no_json"

            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse routing decision JSON: {e}")
                routing_reason = "json_parse_error"

        except Exception as e:
            logger.error(f"Error in SK routing: {type(e).__name__}: {e}", exc_info=True)
            routing_reason = f"exception:{type(e).__name__}"
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
        self.tracer.start()

        try:
            agent_name, agent_input = await self._choose_agent_with_sk(request)

            if agent_name == "test_executor":
                return await self._handle_test_execution(request, agent_input, context)

            agent = self.registry.get(agent_name)
            if agent is None:
                raise ValueError(f"Agent '{agent_name}' not found in registry")

            if context is None:
                context = {}
            context["agent_input"] = agent_input

            response = await agent.run(messages=request.messages, context=context)
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

            self.tracer.step(
                "test_selection",
                "tool_call",
                "Invoking test planner to generate test plan",
                input_snapshot=sanitize_snapshot({"agent_input_keys": list(agent_input.keys())}),
            )

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
            planner_trace = planning_response.reasoning_trace

            test_plan = None
            if planning_response.test_plan:
                test_plan = planning_response.test_plan
                logger.info(
                    f"Retrieved test plan from TestPlannerAgent: "
                    + f"workspace={test_plan.get('workspace_id')}, "
                    + f"tests={test_plan.get('total_tests', 0)}"
                )

                self.tracer.step(
                    "test_selection",
                    "decision",
                    "Test plan generated successfully",
                    output_snapshot=sanitize_snapshot(
                        {
                            "workspace_id": test_plan.get("workspace_id"),
                            "total_tests": test_plan.get("total_tests", 0),
                            "safe_tests": len(test_plan.get("safe_tests", [])),
                            "destructive_tests": len(test_plan.get("destructive_tests", [])),
                        }
                    ),
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

                orch_trace = self.tracer.get_trace()
                planner_trace = planning_response.reasoning_trace
                if orch_trace and planner_trace:
                    orch_trace["steps"].extend(planner_trace.get("steps", []))
                    planning_response.reasoning_trace = orch_trace
                elif orch_trace:
                    planning_response.reasoning_trace = orch_trace

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
            self.tracer.step(
                "execution_planning",
                "tool_call",
                "Dispatching test execution to test executor",
                input_snapshot=sanitize_snapshot(
                    {
                        "workspace_id": execution_request.workspace_id,
                        "mode": execution_request.mode,
                        "include_destructive": execution_request.include_destructive,
                    }
                ),
            )

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

            orch_trace = self.tracer.get_trace()
            if orch_trace:
                all_steps = orch_trace["steps"]

                if planner_trace:
                    all_steps.extend(planner_trace.get("steps", []))

                if execution_response.reasoning_trace:
                    all_steps.extend(execution_response.reasoning_trace.get("steps", []))

                execution_response.reasoning_trace = orch_trace

            return execution_response

        except Exception as e:
            logger.error(f"Error in test execution orchestration: {e}")
            self.tracer.step(
                "execution_planning",
                "inference",
                f"Error during test execution orchestration: {str(e)}",
                error=str(e),
                output_snapshot=sanitize_snapshot({"error_type": type(e).__name__}),
            )
            return ChatResponse(
                messages=[
                    ChatMessage(
                        role="assistant", content=f"Error orchestrating test execution: {str(e)}"
                    )
                ],
                reasoning_trace=self.tracer.get_trace(),
                metadata=None,
            )
