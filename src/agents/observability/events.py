# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""
Typed event definitions for structured logging.

Events are categorized into three streams:
- service_logs: HTTP/API layer events
- agent_logs: Agent and plugin operation events
- execution_logs: Ansible and test execution events

All events share common fields (timestamp, correlation_id, etc.) and have
stream-specific fields. This enables efficient querying in log backends
like Loki, Azure Log Analytics, or Elasticsearch.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class LogStream(str, Enum):
    """Log stream identifiers (indexed labels in Loki)."""

    SERVICE = "service_logs"
    AGENT = "agent_logs"
    EXECUTION = "execution_logs"


class LogLevel(str, Enum):
    """Standard log levels."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARN = "WARN"
    ERROR = "ERROR"


ServiceEventType = Literal[
    "request_start",
    "request_end",
    "llm_call",
    "routing_decision",
    "health_check",
    "error",
]


class ServiceEvent(BaseModel):
    """
    Service-level log event for HTTP/API operations.

    Captures request lifecycle, LLM calls, and routing decisions.
    """

    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    stream: Literal[LogStream.SERVICE] = LogStream.SERVICE
    conversation_id: Optional[str] = None
    correlation_id: Optional[str] = None
    level: LogLevel = LogLevel.INFO
    event: ServiceEventType
    duration_ms: Optional[int] = None
    status: Optional[Literal["success", "failed", "error"]] = None
    error: Optional[str] = None

    http_method: Optional[str] = None
    http_path: Optional[str] = None
    http_status_code: Optional[int] = None
    client_ip: Optional[str] = None
    user_id: Optional[str] = None
    user_agent: Optional[str] = None
    request_body_size: Optional[int] = None
    response_body_size: Optional[int] = None

    llm_model: Optional[str] = None
    llm_tokens_prompt: Optional[int] = None
    llm_tokens_completion: Optional[int] = None
    llm_duration_ms: Optional[int] = None

    routed_agent: Optional[str] = None
    routing_reason: Optional[str] = None

    workspace_id: Optional[str] = None
    sap_sid: Optional[str] = None
    env: Optional[str] = None

    class Config:
        use_enum_values = True


AgentEventType = Literal[
    "agent_start",
    "agent_end",
    "tool_call",
    "tool_result",
    "planning_complete",
    "error",
]


class AgentEvent(BaseModel):
    """
    Agent-level log event for agent and plugin operations.

    Captures agent lifecycle, tool/function calls, and planning results.
    """

    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    stream: Literal[LogStream.AGENT] = LogStream.AGENT
    conversation_id: Optional[str] = None
    correlation_id: Optional[str] = None
    level: LogLevel = LogLevel.INFO
    event: AgentEventType
    duration_ms: Optional[int] = None
    status: Optional[Literal["success", "failed", "error"]] = None
    error: Optional[str] = None

    agent_name: Optional[str] = None
    agent_invocation_id: Optional[str] = None

    phase: Optional[str] = None
    kind: Optional[Literal["tool_call", "inference", "decision"]] = None

    workspace_id: Optional[str] = None
    sap_sid: Optional[str] = None
    env: Optional[str] = None

    selected_safe_tests: Optional[int] = None
    selected_destructive_tests: Optional[int] = None
    skipped_tests: Optional[int] = None
    total_tests: Optional[int] = None

    tool_name: Optional[str] = None
    tool_function: Optional[str] = None
    tool_args_summary: Optional[str] = None
    tool_result_summary: Optional[str] = None
    tool_duration_ms: Optional[int] = None

    class Config:
        use_enum_values = True


ExecutionEventType = Literal[
    "execution_start",
    "execution_end",
    "ansible_start",
    "ansible_end",
    "test_start",
    "test_end",
    "config_check",
    "command_exec",
    "error",
]


class ExecutionEvent(BaseModel):
    """
    Execution-level log event for Ansible and test operations.

    Captures playbook runs, test executions, and SSH commands.
    """

    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    stream: Literal[LogStream.EXECUTION] = LogStream.EXECUTION
    conversation_id: Optional[str] = None
    correlation_id: Optional[str] = None
    level: LogLevel = LogLevel.INFO
    event: ExecutionEventType
    duration_ms: Optional[int] = None
    status: Optional[Literal["success", "failed", "skipped", "error"]] = None
    error: Optional[str] = None

    execution_id: Optional[str] = None
    workspace_id: Optional[str] = None
    sap_sid: Optional[str] = None
    env: Optional[str] = None

    test_id: Optional[str] = None
    test_name: Optional[str] = None
    test_group: Optional[str] = None
    test_type: Optional[Literal["safe", "destructive"]] = None
    action_type: Optional[Literal["test", "config_check", "command", "log_parse"]] = None

    playbook_path: Optional[str] = None
    inventory_path: Optional[str] = None
    role: Optional[str] = None
    hosts: Optional[str] = None
    ansible_rc: Optional[int] = None
    ansible_hosts_ok: Optional[int] = None
    ansible_hosts_changed: Optional[int] = None
    ansible_hosts_failed: Optional[int] = None
    ansible_hosts_unreachable: Optional[int] = None

    command: Optional[str] = None
    command_validated: Optional[bool] = None
    exit_code: Optional[int] = None
    host: Optional[str] = None

    stdout_snippet: Optional[str] = None
    stderr_snippet: Optional[str] = None
    output_lines: Optional[int] = None

    class Config:
        use_enum_values = True


def truncate(text: Optional[str], max_length: int = 200) -> Optional[str]:
    """Truncate text to max length with ellipsis.

    :param text: Text to truncate
    :type text: Optional[str]
    :param max_length: Maximum length
    :type max_length: int
    :returns: Truncated text or None
    :rtype: Optional[str]
    """
    if text is None:
        return None
    if len(text) <= max_length:
        return text
    return text[: max_length - 3] + "..."


def create_service_event(
    event: ServiceEventType,
    level: LogLevel = LogLevel.INFO,
    **kwargs: Any,
) -> ServiceEvent:
    """Create a service event with context auto-populated.

    :param event: Event type
    :type event: ServiceEventType
    :param level: Log level
    :type level: LogLevel
    :param kwargs: Additional event fields
    :returns: ServiceEvent instance
    :rtype: ServiceEvent
    """
    from src.agents.observability.context import (
        get_correlation_id,
        get_conversation_id,
        get_workspace_id,
    )

    return ServiceEvent(
        event=event,
        level=level,
        correlation_id=kwargs.pop("correlation_id", get_correlation_id()),
        conversation_id=kwargs.pop("conversation_id", get_conversation_id()),
        workspace_id=kwargs.pop("workspace_id", get_workspace_id()),
        **kwargs,
    )


def create_agent_event(
    event: AgentEventType,
    level: LogLevel = LogLevel.INFO,
    **kwargs: Any,
) -> AgentEvent:
    """Create an agent event with context auto-populated.

    :param event: Event type
    :type event: AgentEventType
    :param level: Log level
    :type level: LogLevel
    :param kwargs: Additional event fields
    :returns: AgentEvent instance
    :rtype: AgentEvent
    """
    from src.agents.observability.context import (
        get_correlation_id,
        get_conversation_id,
        get_agent_invocation_id,
        get_agent_name,
        get_workspace_id,
    )

    return AgentEvent(
        event=event,
        level=level,
        correlation_id=kwargs.pop("correlation_id", get_correlation_id()),
        conversation_id=kwargs.pop("conversation_id", get_conversation_id()),
        agent_invocation_id=kwargs.pop("agent_invocation_id", get_agent_invocation_id()),
        agent_name=kwargs.pop("agent_name", get_agent_name()),
        workspace_id=kwargs.pop("workspace_id", get_workspace_id()),
        **kwargs,
    )


def create_execution_event(
    event: ExecutionEventType,
    level: LogLevel = LogLevel.INFO,
    **kwargs: Any,
) -> ExecutionEvent:
    """Create an execution event with context auto-populated.

    :param event: Event type
    :type event: ExecutionEventType
    :param level: Log level
    :type level: LogLevel
    :param kwargs: Additional event fields
    :returns: ExecutionEvent instance
    :rtype: ExecutionEvent
    """
    from src.agents.observability.context import (
        get_correlation_id,
        get_conversation_id,
        get_execution_id,
        get_workspace_id,
    )

    return ExecutionEvent(
        event=event,
        level=level,
        correlation_id=kwargs.pop("correlation_id", get_correlation_id()),
        conversation_id=kwargs.pop("conversation_id", get_conversation_id()),
        execution_id=kwargs.pop("execution_id", get_execution_id()),
        workspace_id=kwargs.pop("workspace_id", get_workspace_id()),
        **kwargs,
    )
