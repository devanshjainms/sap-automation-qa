# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""
Agent abstraction for SAP QA backend.

This module provides:
- Agent: Abstract base class for all agents
- BaseSKAgent: Base class for Semantic Kernel-powered agents with function calling
- AgentRegistry: Registry for managing and routing to available agents
- AgentTracer: Wrapper for ReasoningTracer with agent context
"""

from abc import ABC, abstractmethod
from pathlib import Path
import time
from typing import Optional, Literal, Any

from semantic_kernel import Kernel
from semantic_kernel.contents import ChatHistory

from src.agents.models.chat import ChatMessage, ChatResponse
from src.agents.models.reasoning import ReasoningTracer, TracingPhase, sanitize_snapshot
from src.agents.observability import (
    get_logger,
    AgentContext,
    create_agent_event,
    LogLevel,
)

logger = get_logger(__name__)


class AgentTracer:
    """
    Wrapper for ReasoningTracer that automatically includes agent name.

    This provides a clean interface for agents to record reasoning steps
    without having to pass agent name every time.
    """

    def __init__(self, agent_name: str):
        """
        Initialize AgentTracer with agent name.

        :param agent_name: Name of the agent using this tracer
        :type agent_name: str
        """
        self.agent_name = agent_name
        self._tracer: Optional[ReasoningTracer] = None

    def start(self) -> None:
        """
        Start a new reasoning trace.
        """
        self._tracer = ReasoningTracer(agent_name=self.agent_name)
        self._tracer.__enter__()

    def step(
        self,
        phase: Literal[
            "input_understanding",
            "workspace_resolution",
            "system_capabilities",
            "test_selection",
            "execution_planning",
            "execution_run",
            "execution_async",
            "diagnostics",
            "routing",
            "documentation_retrieval",
            "response_generation",
        ],
        kind: Literal["tool_call", "inference", "decision"],
        description: str,
        input_snapshot: Optional[dict[str, Any]] = None,
        output_snapshot: Optional[dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> None:
        """
        Add a reasoning step to the current trace.

        :param phase: Workflow phase this step belongs to
        :type phase: Literal
        :param kind: Type of step (tool_call, inference, decision)
        :type kind: Literal
        :param description: Human-readable description of the step
        :type description: str
        :param input_snapshot: Small summary of inputs
        :type input_snapshot: Optional[dict[str, Any]]
        :param output_snapshot: Small summary of outputs
        :type output_snapshot: Optional[dict[str, Any]]
        :param error: Error message if step failed
        :type error: Optional[str]
        """
        if self._tracer:
            self._tracer.step(
                phase,
                kind,
                description,
                agent=self.agent_name,
                input_snapshot=input_snapshot,
                output_snapshot=output_snapshot,
                error=error,
            )

    def get_trace(self) -> Optional[dict]:
        """
        Get the trace as a dictionary for inclusion in responses.

        :return: Trace dictionary or None if no trace started
        :rtype: Optional[dict]
        """
        return self._tracer.get_trace() if self._tracer else None

    def finish(self) -> None:
        """Finish the current trace."""
        if self._tracer:
            self._tracer.__exit__(None, None, None)
            self._tracer = None


class Agent(ABC):
    """
    Abstract base class for agents.

    :param ABC: Abstract base class from abc module
    :type ABC: ABC
    """

    def __init__(self, name: str, description: str) -> None:
        """Initialize agent with name and description.

        :param name: Unique identifier for the agent
        :param description: Human-readable description of agent capabilities
        """
        self.name = name
        self.description = description
        self.tracer = AgentTracer(agent_name=name)

    @abstractmethod
    async def run(
        self,
        messages: list[ChatMessage],
        context: Optional[dict] = None,
    ) -> ChatResponse:
        """Execute agent logic and return response.

        :param messages: Full conversation history
        :param context: Optional metadata (user, session, etc.)
        :returns: ChatResponse with agent's reply
        """
        pass


class BaseSKAgent(Agent):
    """
    Base class for Semantic Kernel-powered agents with function calling.

    This class handles the common SK boilerplate:
    - ChatHistory setup with system prompt
    - SK chat completion with function calling
    - Structured error handling and tracing
    - Configurable model deployment per agent

    Subclasses should:
    - Call super().__init__() with name, description, kernel, system_prompt
    - Register plugins in __init__ after calling super()
    - Override _get_tracing_phase() to return the phase name for tracing
    - Optionally override _process_response() for custom response handling
    """

    def __init__(
        self,
        name: str,
        description: str,
        kernel: Kernel,
        system_prompt: str,
        max_tokens: int = 2000,
        service_id: str = "azure_openai_chat",
    ) -> None:
        """Initialize BaseSKAgent with Semantic Kernel.

        :param name: Unique identifier for the agent
        :type name: str
        :param description: Human-readable description of agent capabilities
        :type description: str
        :param kernel: Configured Semantic Kernel instance
        :type kernel: Kernel
        :param system_prompt: System prompt for the agent
        :type system_prompt: str
        :param max_tokens: Maximum tokens for completion (default: 2000)
        :type max_tokens: int
        :param service_id: SK service ID for chat completion (default: azure_openai_chat)
        :type service_id: str
        """
        super().__init__(name=name, description=description)
        self.kernel = kernel
        self.system_prompt = system_prompt
        self.max_tokens = max_tokens
        self.service_id = service_id

        logger.info(f"{self.__class__.__name__} initialized with SK service '{service_id}'")

    def _get_tracing_phase(self) -> TracingPhase:
        """Return the primary tracing phase for this agent.

        Override in subclasses to provide a specific phase name.

        :returns: Phase name for tracing (e.g., 'documentation_retrieval', 'workspace_resolution')
        :rtype: TracingPhase
        """
        return "response_generation"

    def _build_chat_history(self, messages: list[ChatMessage]) -> ChatHistory:
        """Build SK ChatHistory from conversation messages.

        :param messages: List of ChatMessage objects from the conversation
        :type messages: list[ChatMessage]
        :returns: Configured ChatHistory with system prompt and messages
        :rtype: ChatHistory
        """
        chat_history = ChatHistory()
        chat_history.add_system_message(self.system_prompt)

        for msg in messages:
            if msg.role == "user":
                chat_history.add_user_message(msg.content)
            elif msg.role == "assistant":
                chat_history.add_assistant_message(msg.content)

        return chat_history

    async def _get_sk_response(self, chat_history: ChatHistory) -> str:
        """Execute SK chat completion with function calling.

        :param chat_history: Prepared ChatHistory
        :type chat_history: ChatHistory
        :returns: Response content string
        :rtype: str
        """
        chat_service = self.kernel.get_service(service_id=self.service_id)
        execution_settings = chat_service.get_prompt_execution_settings_class()(
            function_choice_behavior="auto",
            max_completion_tokens=self.max_tokens,
        )

        logger.info(f"Calling SK chat completion for {self.name}")
        response = await chat_service.get_chat_message_content(
            chat_history=chat_history,
            settings=execution_settings,
            kernel=self.kernel,
        )

        return str(response.content) if response and response.content else ""

    def _process_response(
        self,
        response_content: str,
        context: Optional[dict] = None,
    ) -> ChatResponse:
        """Process SK response into ChatResponse.

        Override in subclasses for custom response handling (e.g., extracting test plans).

        :param response_content: Raw response content from SK
        :type response_content: str
        :param context: Optional context dictionary
        :type context: Optional[dict]
        :returns: Formatted ChatResponse
        :rtype: ChatResponse
        """
        return ChatResponse(
            messages=[ChatMessage(role="assistant", content=response_content)],
            reasoning_trace=self.tracer.get_trace(),
            metadata=None,
        )

    async def run(
        self,
        messages: list[ChatMessage],
        context: Optional[dict] = None,
    ) -> ChatResponse:
        """Execute the agent using Semantic Kernel with function calling.

        This method handles the common SK workflow:
        1. Build ChatHistory with system prompt
        2. Execute SK chat completion with function calling
        3. Process and return response

        :param messages: List of ChatMessage objects from the conversation
        :type messages: list[ChatMessage]
        :param context: Optional context dictionary
        :type context: Optional[dict]
        :returns: ChatResponse with the agent's response
        :rtype: ChatResponse
        """
        workspace_id = context.get("workspace_id") if context else None
        start_time = time.perf_counter()
        with AgentContext(agent_name=self.name, workspace_id=workspace_id):
            logger.info(f"{self.__class__.__name__}.run called with {len(messages)} messages")
            logger.event(
                create_agent_event(
                    event="agent_start",
                    phase=self._get_tracing_phase(),
                )
            )

            self.tracer.start()

            try:
                self.tracer.step(
                    self._get_tracing_phase(),
                    "tool_call",
                    f"Processing request with SK for {self.name}",
                    input_snapshot=sanitize_snapshot(
                        {"message_count": len(messages), "has_context": context is not None}
                    ),
                )

                chat_history = self._build_chat_history(messages)
                logger.info(f"Chat history prepared with {len(chat_history.messages)} messages")

                response_content = await self._get_sk_response(chat_history)

                self.tracer.step(
                    "response_generation",
                    "inference",
                    f"Generated response for {self.name}",
                    output_snapshot=sanitize_snapshot(
                        {
                            "response_length": len(response_content),
                            "has_content": bool(response_content),
                        }
                    ),
                )

                duration_ms = int((time.perf_counter() - start_time) * 1000)
                logger.event(
                    create_agent_event(
                        event="agent_end",
                        status="success",
                        duration_ms=duration_ms,
                        phase=self._get_tracing_phase(),
                    )
                )

                return self._process_response(response_content, context)

            except Exception as e:
                duration_ms = int((time.perf_counter() - start_time) * 1000)

                logger.error(
                    f"Error in {self.__class__.__name__}: {type(e).__name__}: {e}",
                    exc_info=e,
                )
                logger.event(
                    create_agent_event(
                        event="agent_end",
                        level=LogLevel.ERROR,
                        status="error",
                        duration_ms=duration_ms,
                        error=str(e),
                        phase=self._get_tracing_phase(),
                    )
                )

                self.tracer.step(
                    self._get_tracing_phase(),
                    "inference",
                    f"Error in {self.name}: {str(e)}",
                    error=str(e),
                    output_snapshot=sanitize_snapshot({"error_type": type(e).__name__}),
                )
                raise

            finally:
                self.tracer.finish()


class AgentRegistry:
    """Registry for managing and routing to available agents."""

    def __init__(self) -> None:
        """Initialize empty agent registry."""
        self._agents: dict[str, Agent] = {}

    def register(self, agent: Agent) -> None:
        """Register an agent by its name.

        :param agent: Agent instance to register
        :raises ValueError: If agent with same name already registered
        """
        if agent.name in self._agents:
            raise ValueError(f"Agent '{agent.name}' already registered")
        self._agents[agent.name] = agent

    def get(self, name: str) -> Optional[Agent]:
        """Get agent by name.

        :param name: Agent name to retrieve
        :returns: Agent instance or None if not found
        """
        return self._agents.get(name)

    def list_agents(self) -> list[dict[str, str]]:
        """List all available agents.

        :returns: List of dicts with agent name and description
        """
        return [
            {"name": agent.name, "description": agent.description}
            for agent in self._agents.values()
        ]

    def __contains__(self, name: str) -> bool:
        """Check if agent is registered.

        :param name: Agent name to check
        :returns: True if agent exists in registry
        """
        return name in self._agents


def create_default_agent_registry() -> "AgentRegistry":
    """
    Create and populate default agent registry.
    All agents now use Semantic Kernel for function calling.

    :return: An AgentRegistry with default agents registered
    :rtype: AgentRegistry
    """
    from src.agents.agents.echo_agent import EchoAgentSK
    from src.agents.agents.test_planner_agent import TestPlannerAgentSK
    from src.agents.agents.system_context_agent import SystemContextAgentSK
    from src.agents.agents.test_executor_agent import TestExecutorAgent
    from src.agents.workspace.workspace_store import WorkspaceStore
    from src.agents.plugins.execution import ExecutionPlugin
    from src.agents.plugins.keyvault import KeyVaultPlugin
    from src.agents.plugins.ssh import SSHPlugin
    from src.agents.ansible_runner import AnsibleRunner
    from src.agents.sk_kernel import create_kernel

    kernel = create_kernel()
    workspace_root = Path(__file__).parent.parent.parent.parent / "WORKSPACES" / "SYSTEM"
    workspace_store = WorkspaceStore(workspace_root)
    src_dir = Path(__file__).parent.parent.parent
    ansible_runner = AnsibleRunner(base_dir=src_dir)
    keyvault_plugin = KeyVaultPlugin()
    ssh_plugin = SSHPlugin()

    execution_plugin = ExecutionPlugin(
        workspace_store=workspace_store,
        ansible_runner=ansible_runner,
        keyvault_plugin=keyvault_plugin,
    )
    kernel.add_plugin(execution_plugin, plugin_name="execution")
    kernel.add_plugin(keyvault_plugin, plugin_name="keyvault")
    kernel.add_plugin(ssh_plugin, plugin_name="ssh")

    registry = AgentRegistry()
    registry.register(EchoAgentSK(kernel=kernel))
    registry.register(TestPlannerAgentSK(kernel=kernel, workspace_store=workspace_store))
    registry.register(SystemContextAgentSK(kernel=kernel, workspace_store=workspace_store))
    registry.register(
        TestExecutorAgent(
            kernel=kernel, workspace_store=workspace_store, execution_plugin=execution_plugin
        )
    )
    return registry
