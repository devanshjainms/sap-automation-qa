# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""
Reasoning trace models for agent transparency and debuggability.

This module provides first-class support for capturing the chain-of-thought
and decision-making process of agents in the SAP QA framework.
"""

from datetime import datetime
from typing import Any, Literal, Optional
from uuid import uuid4
from contextvars import ContextVar

from pydantic import BaseModel, Field

_current_trace: ContextVar[Optional["ReasoningTrace"]] = ContextVar("_current_trace", default=None)

TracingPhase = Literal[
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
]


class ReasoningStep(BaseModel):
    """
    A single step in an agent's reasoning process.

    Captures what the agent did (tool call, inference, decision) and why,
    with snapshots of input/output for debugging.
    """

    id: str = Field(default_factory=lambda: str(uuid4()))
    parent_step_id: Optional[str] = Field(
        None, description="ID of the parent step for nested reasoning"
    )
    agent: str = Field(..., description="Name of the agent that created this step")
    phase: TracingPhase = Field(..., description="Phase of agent workflow this step belongs to")
    kind: Literal["tool_call", "inference", "decision"] = Field(
        ..., description="Type of reasoning step"
    )
    description: str = Field(..., description="Human-readable description of what happened")
    input_snapshot: dict[str, Any] = Field(
        default_factory=dict,
        description="Small summary of inputs (keys, counts, not full data)",
    )
    output_snapshot: dict[str, Any] = Field(
        default_factory=dict,
        description="Small summary of outputs (keys, counts, not full data)",
    )
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    error: Optional[str] = Field(None, description="Error message if step failed")

    class Config:
        """
        Pydantic configuration.
        """

        json_encoders = {datetime: lambda v: v.isoformat()}


class ReasoningTrace(BaseModel):
    """
    Complete trace of an agent's reasoning process.

    Captures the full chain-of-thought from request to response,
    enabling inspection, debugging, and auditing of agent behavior.
    """

    trace_id: str = Field(default_factory=lambda: str(uuid4()))
    steps: list[ReasoningStep] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    agent_name: Optional[str] = Field(None, description="Primary agent for this trace")

    class Config:
        """
        Pydantic configuration.
        """

        json_encoders = {datetime: lambda v: v.isoformat()}

    def add_step(
        self,
        agent: str,
        phase: TracingPhase,
        kind: Literal["tool_call", "inference", "decision"],
        description: str,
        parent_step_id: Optional[str] = None,
        input_snapshot: Optional[dict[str, Any]] = None,
        output_snapshot: Optional[dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> ReasoningStep:
        """
        Add a reasoning step to the trace.

        :param agent: Name of the agent creating this step
        :type agent: str
        :param phase: Workflow phase this step belongs to
        :type phase: TracingPhase
        :param kind: Type of step (tool_call, inference, decision)
        :type kind: Literal
        :param description: Human-readable description of the step
        :type description: str
        :param parent_step_id: Optional ID of parent step
        :type parent_step_id: Optional[str]
        :param input_snapshot: Small summary of inputs (optional)
        :type input_snapshot: Optional[dict[str, Any]]
        :param output_snapshot: Small summary of outputs (optional)
        :type output_snapshot: Optional[dict[str, Any]]
        :param error: Error message if step failed (optional)
        :type error: Optional[str]
        :return: The created ReasoningStep
        :rtype: ReasoningStep

        Example:
            >>> trace = ReasoningTrace()
            >>> trace.add_step(
            ...     agent="test_planner",
            ...     phase="workspace_resolution",
            ...     kind="tool_call",
            ...     description="Finding workspace by SID",
            ...     input_snapshot={"sid": "X00", "env": "DEV"},
            ...     output_snapshot={"workspace_count": 1, "workspace_id": "DEV-WEEU-SAP01-X00"}
            ... )
        """
        step = ReasoningStep(
            agent=agent,
            phase=phase,
            kind=kind,
            description=description,
            parent_step_id=parent_step_id,
            input_snapshot=input_snapshot or {},
            output_snapshot=output_snapshot or {},
            error=error,
        )
        self.steps.append(step)
        return step

    def get_steps_by_phase(
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
    ) -> list[ReasoningStep]:
        """
        Get all steps for a specific phase.

        :param phase: Phase to filter by
        :type phase: Literal
        :return: List of steps in that phase
        :rtype: list[ReasoningStep]
        """
        return [step for step in self.steps if step.phase == phase]

    def get_steps_by_agent(self, agent: str) -> list[ReasoningStep]:
        """
        Get all steps created by a specific agent.

        :param agent: Agent name to filter by
        :type agent: str
        :return: List of steps from that agent
        :rtype: list[ReasoningStep]
        """
        return [step for step in self.steps if step.agent == agent]

    def get_errors(self) -> list[ReasoningStep]:
        """
        Get all steps that encountered errors.

        :return: List of steps with errors
        :rtype: list[ReasoningStep]
        """
        return [step for step in self.steps if step.error is not None]

    def to_summary(self) -> dict[str, Any]:
        """
        Generate a compact summary of the trace.

        :return: Summary with counts and key information
        :rtype: dict[str, Any]
        """
        phases = {}
        for step in self.steps:
            phases[step.phase] = phases.get(step.phase, 0) + 1

        agents = {}
        for step in self.steps:
            agents[step.agent] = agents.get(step.agent, 0) + 1

        return {
            "trace_id": self.trace_id,
            "total_steps": len(self.steps),
            "phases": phases,
            "agents": agents,
            "errors": len(self.get_errors()),
            "duration_seconds": (
                (self.steps[-1].timestamp - self.steps[0].timestamp).total_seconds()
                if self.steps
                else 0
            ),
        }

    def to_markdown(self) -> str:
        """
        Generate a human-readable markdown representation of the trace.

        :return: Markdown formatted trace
        :rtype: str
        """
        lines = [
            f"# Reasoning Trace: {self.trace_id}",
            f"**Created**: {self.created_at.isoformat()}",
            f"**Total Steps**: {len(self.steps)}",
            "",
            "## Steps",
            "",
        ]

        for i, step in enumerate(self.steps, 1):
            lines.append(f"### {i}. {step.description}")
            lines.append(f"- **Agent**: {step.agent}")
            lines.append(f"- **Phase**: {step.phase}")
            lines.append(f"- **Kind**: {step.kind}")
            lines.append(f"- **Timestamp**: {step.timestamp.isoformat()}")

            if step.input_snapshot:
                lines.append(f"- **Input**: {step.input_snapshot}")

            if step.output_snapshot:
                lines.append(f"- **Output**: {step.output_snapshot}")

            if step.error:
                lines.append(f"- **Error**:  {step.error}")

            lines.append("")

        return "\n".join(lines)


def sanitize_snapshot(data: dict[str, Any], max_items: int = 5) -> dict[str, Any]:
    """
    Create a sanitized snapshot of data for reasoning traces.

    Removes secrets, truncates large collections, and summarizes complex objects.

    :param data: Original data dictionary
    :type data: dict[str, Any]
    :param max_items: Maximum items to include in lists/dicts
    :type max_items: int
    :return: Sanitized snapshot safe for logging
    :rtype: dict[str, Any]
    """
    SECRET_KEYS = {
        "password",
        "api_key",
        "secret",
        "token",
        "credential",
        "auth",
        "private_key",
    }

    def sanitize_value(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                k: (
                    "***REDACTED***"
                    if any(s in k.lower() for s in SECRET_KEYS)
                    else sanitize_value(v)
                )
                for k, v in list(value.items())[:max_items]
            }
        elif isinstance(value, list):
            if len(value) > max_items:
                return [sanitize_value(v) for v in value[:max_items]] + [
                    f"... {len(value) - max_items} more items"
                ]
            return [sanitize_value(v) for v in value]
        elif isinstance(value, str) and len(value) > 200:
            return value[:200] + "... (truncated)"
        else:
            return value

    return sanitize_value(data)


class ReasoningTracer:
    """
    Context manager for reasoning trace capture.

    Provides a clean interface for agents to record reasoning steps
    without explicit trace passing.

    Usage:
        with ReasoningTracer(agent_name="echo") as tracer:
            tracer.step("documentation_retrieval", "tool_call", "Searching docs")
            # ... agent logic ...
            response = ChatResponse(...)
            response.reasoning_trace = tracer.get_trace()
    """

    def __init__(self, agent_name: Optional[str] = None, trace_id: Optional[str] = None):
        """
        Initialize reasoning tracer.

        :param agent_name: Name of the primary agent
        :type agent_name: Optional[str]
        :param trace_id: Optional trace ID (generates new if not provided)
        :type trace_id: Optional[str]
        """
        self.trace = ReasoningTrace(agent_name=agent_name, trace_id=trace_id or str(uuid4()))
        self._token = None

    def __enter__(self) -> "ReasoningTracer":
        """Enter context manager and set current trace."""
        self._token = _current_trace.set(self.trace)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit context manager and clear current trace."""
        if self._token:
            try:
                _current_trace.reset(self._token)
            except ValueError:
                pass
            finally:
                self._token = None

    def step(
        self,
        phase: TracingPhase,
        kind: Literal["tool_call", "inference", "decision"],
        description: str,
        agent: Optional[str] = None,
        parent_step_id: Optional[str] = None,
        input_snapshot: Optional[dict[str, Any]] = None,
        output_snapshot: Optional[dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> ReasoningStep:
        """
        Add a reasoning step to the trace.

        :param phase: Workflow phase
        :type phase: TracingPhase
        :param kind: Type of step
        :type kind: Literal
        :param description: Human-readable description
        :type description: str
        :param agent: Agent name (uses trace agent_name if not provided)
        :type agent: Optional[str]
        :param parent_step_id: Optional ID of parent step
        :type parent_step_id: Optional[str]
        :param input_snapshot: Small summary of inputs
        :type input_snapshot: Optional[dict[str, Any]]
        :param output_snapshot: Small summary of outputs
        :type output_snapshot: Optional[dict[str, Any]]
        :param error: Error message if step failed
        :type error: Optional[str]
        :return: The created ReasoningStep
        :rtype: ReasoningStep
        """
        return self.trace.add_step(
            agent=agent or self.trace.agent_name or "unknown",
            phase=phase,
            kind=kind,
            description=description,
            parent_step_id=parent_step_id,
            input_snapshot=input_snapshot,
            output_snapshot=output_snapshot,
            error=error,
        )

    def get_trace(self) -> Optional[dict]:
        """
        Get the trace as a dictionary for inclusion in responses.

        :return: Trace dictionary or None if no steps
        :rtype: Optional[dict]
        """
        return self.trace.dict() if self.trace.steps else None


def get_current_tracer() -> Optional[ReasoningTracer]:
    """
    Get the current reasoning tracer from context.

    :return: Current tracer or None if not in tracing context
    :rtype: Optional[ReasoningTracer]
    """
    trace = _current_trace.get()
    if trace:
        tracer = ReasoningTracer.__new__(ReasoningTracer)
        tracer.trace = trace
        tracer._token = None
        return tracer
    return None


def trace_step(
    phase: TracingPhase,
    kind: Literal["tool_call", "inference", "decision"],
    description: str,
    agent: Optional[str] = None,
    parent_step_id: Optional[str] = None,
    input_snapshot: Optional[dict[str, Any]] = None,
    output_snapshot: Optional[dict[str, Any]] = None,
    error: Optional[str] = None,
) -> Optional[ReasoningStep]:
    """
    Add a reasoning step to the current trace (if active).

    This is a convenience function that can be called anywhere in agent code
    without explicitly passing the tracer around.

    :param phase: Workflow phase
    :type phase: TracingPhase
    :param kind: Type of step
    :type kind: Literal
    :param description: Human-readable description
    :type description: str
    :param agent: Agent name
    :type agent: Optional[str]
    :param parent_step_id: Optional ID of parent step
    :type parent_step_id: Optional[str]
    :param input_snapshot: Small summary of inputs
    :type input_snapshot: Optional[dict[str, Any]]
    :param output_snapshot: Small summary of outputs
    :type output_snapshot: Optional[dict[str, Any]]
    :param error: Error message if step failed
    :type error: Optional[str]
    :return: The created ReasoningStep or None if no active trace
    :rtype: Optional[ReasoningStep]
    """
    tracer = get_current_tracer()
    if tracer:
        return tracer.step(
            phase=phase,
            kind=kind,
            description=description,
            agent=agent,
            parent_step_id=parent_step_id,
            input_snapshot=input_snapshot,
            output_snapshot=output_snapshot,
            error=error,
        )
    return None
