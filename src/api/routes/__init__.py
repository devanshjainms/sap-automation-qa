# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""API routes package."""

from src.api.routes.agents import router as agents_router, set_agent_registry
from src.api.routes.chat import (
    router as chat_router,
    set_orchestrator,
    set_chat_conversation_manager,
)
from src.api.routes.conversations import router as conversations_router, set_conversation_manager
from src.api.routes.health import router as health_router

__all__ = [
    "agents_router",
    "chat_router",
    "conversations_router",
    "health_router",
    "set_agent_registry",
    "set_chat_conversation_manager",
    "set_conversation_manager",
    "set_orchestrator",
]
