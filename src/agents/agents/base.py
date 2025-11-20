# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""
Agent abstraction for SAP QA backend
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional, Literal, Any

from src.agents.models.chat import ChatMessage, ChatResponse
from src.agents.models.reasoning import ReasoningTracer


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
    from src.agents.ansible_runner import AnsibleRunner
    from src.agents.sk_kernel import create_kernel

    kernel = create_kernel()
    workspace_root = Path(__file__).parent.parent.parent.parent / "WORKSPACES" / "SYSTEM"
    workspace_store = WorkspaceStore(workspace_root)
    src_dir = Path(__file__).parent.parent.parent
    ansible_runner = AnsibleRunner(base_dir=src_dir)
    execution_plugin = ExecutionPlugin(
        workspace_store=workspace_store, ansible_runner=ansible_runner
    )
    kernel.add_plugin(execution_plugin, plugin_name="execution")

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
