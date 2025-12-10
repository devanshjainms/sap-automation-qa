# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""API routes package."""

from src.api.routes.agents import router as agents_router, set_agent_registry
from src.api.routes.chat import (
    router as chat_router,
    set_orchestrator,
    set_chat_conversation_manager,
    set_chat_kernel,
)
from src.api.routes.conversations import router as conversations_router, set_conversation_manager
from src.api.routes.health import router as health_router
from src.api.routes.streaming import router as streaming_router, set_job_worker
from src.api.routes.workspaces import router as workspaces_router, set_workspace_store

__all__ = [
    "agents_router",
    "chat_router",
    "conversations_router",
    "health_router",
    "streaming_router",
    "workspaces_router",
    "set_agent_registry",
    "set_chat_conversation_manager",
    "set_chat_kernel",
    "set_conversation_manager",
    "set_job_worker",
    "set_orchestrator",
    "set_workspace_store",
]
