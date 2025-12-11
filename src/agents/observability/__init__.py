# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""
Observability module for SAP QA Agent Framework.

This module provides production-grade observability with OOP design:

Classes:
- ObservabilityContextManager: Singleton for context management
- ObservabilityScope/AgentScope/ExecutionScope: Context managers
- StructuredLogger: Logger with context injection
- LoggerFactory: Factory for creating loggers
- JSONFormatter/ConsoleFormatter: Log formatters

Events:
- ServiceEvent: HTTP/API layer events
- AgentEvent: Agent/plugin events
- ExecutionEvent: Ansible/test events

Usage:
    from src.agents.observability import (
        LoggerFactory,
        get_logger,
        AgentScope,
        create_agent_event,
    )

    # Initialize once at startup
    LoggerFactory.initialize(level=logging.INFO, log_format="json")

    # Get logger
    logger = get_logger(__name__)

    # Use scoped context
    with AgentScope(agent_name="test_planner"):
        logger.info("Processing request")
        logger.event(create_agent_event("agent_start"))
"""

# Context management
from src.agents.observability.context import (
    # Data classes
    ContextData,
    # Manager
    ObservabilityContextManager,
    # Context providers
    ContextVarProvider,
    IContextProvider,
    # Scopes
    ObservabilityScope,
    AgentScope,
    ExecutionScope,
    # Backward compatibility aliases
    ObservabilityContext,
    AgentContext,
    ExecutionContext,
    # Convenience functions
    get_correlation_id,
    set_correlation_id,
    get_conversation_id,
    set_conversation_id,
    get_agent_invocation_id,
    get_agent_name,
    set_agent_name,
    get_workspace_id,
    set_workspace_id,
    get_execution_id,
    clear_context,
)

# Events
from src.agents.observability.events import (
    LogStream,
    LogLevel,
    ServiceEvent,
    AgentEvent,
    ExecutionEvent,
    create_service_event,
    create_agent_event,
    create_execution_event,
)

# Logger
from src.agents.observability.logger import (
    # Classes
    LogFormatter,
    JSONFormatter,
    ConsoleFormatter,
    StructuredLogger,
    LoggerFactory,
    # Functions
    initialize_logging,
    get_logger,
    clear_correlation_id,
)

# Middleware
from src.agents.observability.middleware import (
    ObservabilityMiddleware,
    add_observability_middleware,
    CORRELATION_ID_HEADER,
    CONVERSATION_ID_HEADER,
    WORKSPACE_ID_HEADER,
)


__all__ = [
    # Context - Classes
    "ContextData",
    "ObservabilityContextManager",
    "ContextVarProvider",
    "IContextProvider",
    "ObservabilityScope",
    "AgentScope",
    "ExecutionScope",
    # Context - Backward compatibility
    "ObservabilityContext",
    "AgentContext",
    "ExecutionContext",
    # Context - Functions
    "get_correlation_id",
    "set_correlation_id",
    "get_conversation_id",
    "set_conversation_id",
    "get_agent_invocation_id",
    "get_agent_name",
    "set_agent_name",
    "get_workspace_id",
    "set_workspace_id",
    "get_execution_id",
    "clear_context",
    "clear_correlation_id",
    # Events
    "LogStream",
    "LogLevel",
    "ServiceEvent",
    "AgentEvent",
    "ExecutionEvent",
    "create_service_event",
    "create_agent_event",
    "create_execution_event",
    # Logger - Classes
    "LogFormatter",
    "JSONFormatter",
    "ConsoleFormatter",
    "StructuredLogger",
    "LoggerFactory",
    # Logger - Functions
    "initialize_logging",
    "get_logger",
    # Middleware
    "ObservabilityMiddleware",
    "add_observability_middleware",
    "CORRELATION_ID_HEADER",
    "CONVERSATION_ID_HEADER",
    "WORKSPACE_ID_HEADER",
]
