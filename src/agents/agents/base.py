# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""
Agent abstraction for SAP QA backend.

This module provides:
- SAPAutomationAgent: Base class for Semantic Kernel ChatCompletionAgent agents
- AgentRegistry: Registry for managing and routing to available agents
- AgentTracer: Wrapper for ReasoningTracer with agent context
"""

from pathlib import Path
from typing import Optional, Literal, Any

from pydantic import ConfigDict
from semantic_kernel import Kernel
from semantic_kernel.agents import Agent, ChatCompletionAgent
from semantic_kernel.connectors.ai.function_choice_behavior import FunctionChoiceBehavior

from src.agents.models.reasoning import ReasoningTracer, ReasoningStep, TracingPhase
from src.agents.observability import get_logger
from src.agents.plugins.glossary import GlossaryPlugin
from src.agents.plugins.memory import MemoryPlugin

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
        phase: TracingPhase,
        kind: Literal["tool_call", "inference", "decision"],
        description: str,
        parent_step_id: Optional[str] = None,
        input_snapshot: Optional[dict[str, Any]] = None,
        output_snapshot: Optional[dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> Optional[ReasoningStep]:
        """
        Add a reasoning step to the current trace.

        :param phase: Workflow phase this step belongs to
        :type phase: TracingPhase
        :param kind: Type of step (tool_call, inference, decision)
        :type kind: Literal
        :param description: Human-readable description of the step
        :type description: str
        :param parent_step_id: Optional ID of parent step
        :type parent_step_id: Optional[str]
        :param input_snapshot: Small summary of inputs
        :type input_snapshot: Optional[dict[str, Any]]
        :param output_snapshot: Small summary of outputs
        :type output_snapshot: Optional[dict[str, Any]]
        :param error: Error message if step failed
        :type error: Optional[str]
        :return: The created ReasoningStep or None
        :rtype: Optional[ReasoningStep]
        """
        if self._tracer:
            return self._tracer.step(
                phase,
                kind,
                description,
                agent=self.agent_name,
                parent_step_id=parent_step_id,
                input_snapshot=input_snapshot,
                output_snapshot=output_snapshot,
                error=error,
            )
        return None

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


class SAPAutomationAgent(ChatCompletionAgent):
    """Base class for SAP automation agents using Semantic Kernel's ChatCompletionAgent.

    All agents automatically have:
    - FunctionChoiceBehavior.Auto() for autonomous tool calling
    - GlossaryPlugin for SAP terminology understanding
    - MemoryPlugin for LLM-controlled explicit memory within a conversation

    Pydantic Configuration:
    - extra='allow': Permits subclasses to add instance attributes without declaring them as fields
    - arbitrary_types_allowed: Allows non-Pydantic types (WorkspaceStore, plugins, etc.)
    """

    model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True)

    def __init__(
        self,
        *,
        name: str,
        description: str,
        kernel: Kernel,
        instructions: str,
        plugins: Optional[list[object]] = None,
        enable_auto_function_calling: bool = True,
    ) -> None:
        all_plugins = list(plugins) if plugins else []
        has_glossary = any(isinstance(p, GlossaryPlugin) for p in all_plugins)
        if not has_glossary:
            all_plugins.append(GlossaryPlugin())
        has_memory = any(isinstance(p, MemoryPlugin) for p in all_plugins)
        if not has_memory:
            all_plugins.append(MemoryPlugin())

        function_choice = (
            FunctionChoiceBehavior.Auto(auto_invoke_kernel_functions=True)
            if enable_auto_function_calling
            else None
        )

        super().__init__(
            name=name,
            description=description,
            kernel=kernel,
            instructions=instructions,
            plugins=all_plugins,
            function_choice_behavior=function_choice,
        )
        logger.info(
            f"{self.__class__.__name__} initialized with Semantic Kernel agents framework "
            f"(auto_function_calling={enable_auto_function_calling}, plugins={len(all_plugins)})"
        )


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
            {"name": agent.name, "description": agent.description or ""}
            for agent in self._agents.values()
        ]

    def all_agents(self) -> list[Agent]:
        """Return all registered agent instances."""
        return list(self._agents.values())

    def __contains__(self, name: str) -> bool:
        """Check if agent is registered.

        :param name: Agent name to check
        :returns: True if agent exists in registry
        """
        return name in self._agents


def create_default_agent_registry(kernel: Optional[Kernel] = None) -> "AgentRegistry":
    """
    Create and populate default agent registry.
    All agents now use Semantic Kernel for function calling.

    :return: An AgentRegistry with default agents registered
    :rtype: AgentRegistry
    """
    from src.agents.agents.echo_agent import EchoAgentSK
    from src.agents.agents.action_planner_agent import ActionPlannerAgentSK
    from src.agents.agents.system_context_agent import SystemContextAgentSK
    from src.agents.agents.test_advisor_agent import TestAdvisorAgentSK
    from src.agents.agents.action_executor_agent import ActionExecutorAgent
    from src.agents.workspace.workspace_store import WorkspaceStore
    from src.agents.plugins.execution import ExecutionPlugin
    from src.agents.plugins.workspace import WorkspacePlugin
    from src.agents.plugins.keyvault import KeyVaultPlugin
    from src.agents.ansible_runner import AnsibleRunner
    from src.agents.sk_kernel import create_kernel

    kernel = kernel or create_kernel()
    workspace_root = Path(__file__).parent.parent.parent.parent / "WORKSPACES" / "SYSTEM"
    workspace_store = WorkspaceStore(workspace_root)
    src_dir = Path(__file__).parent.parent.parent
    ansible_runner = AnsibleRunner(base_dir=src_dir)
    workspace_plugin = WorkspacePlugin(store=workspace_store)
    keyvault_plugin = KeyVaultPlugin()
    execution_plugin = ExecutionPlugin(
        workspace_store=workspace_store,
        ansible_runner=ansible_runner,
        workspace_plugin=workspace_plugin,
        keyvault_plugin=keyvault_plugin,
    )

    registry = AgentRegistry()
    registry.register(EchoAgentSK(kernel=kernel))
    registry.register(TestAdvisorAgentSK(kernel=kernel, workspace_store=workspace_store))
    registry.register(ActionPlannerAgentSK(kernel=kernel, workspace_store=workspace_store))
    registry.register(SystemContextAgentSK(kernel=kernel, workspace_store=workspace_store))
    registry.register(
        ActionExecutorAgent(
            kernel=kernel,
            workspace_store=workspace_store,
            execution_plugin=execution_plugin,
        )
    )
    return registry
