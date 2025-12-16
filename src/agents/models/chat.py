# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""
Pydantic models for chat messages and requests.

This module defines the core chat message models used throughout the agent framework
for communication between users, agents, and tools.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class MessageRole(str, Enum):
    """Role of the message sender.

    :cvar USER: Message from the user
    :cvar ASSISTANT: Message from the AI assistant
    :cvar SYSTEM: System prompt or instruction
    :cvar TOOL: Response from a tool invocation
    """

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


class ChatMessage(BaseModel):
    """Chat message with role and content.

    :param role: Message sender role
    :type role: str
    :param content: Message content
    :type content: str
    """

    role: str
    content: str

    @classmethod
    def from_role(cls, role: MessageRole, content: str) -> "ChatMessage":
        """Create a ChatMessage from a MessageRole enum.

        :param role: Message role enum value
        :type role: MessageRole
        :param content: Message content
        :type content: str
        :returns: New ChatMessage instance
        :rtype: ChatMessage
        """
        return cls(role=role.value, content=content)


class ChatRequest(BaseModel):
    """Chat request containing a list of messages."""

    messages: list[ChatMessage]
    correlation_id: Optional[str] = None
    workspace_ids: Optional[list[str]] = Field(
        None, description="List of workspace IDs to use as context for this request"
    )


class ChatResponse(BaseModel):
    """Chat response containing a list of messages."""

    messages: list[ChatMessage]
    test_plan: Optional[dict] = None
    action_plan: Optional[dict] = None
    correlation_id: Optional[str] = None
    reasoning_trace: Optional[dict] = Field(
        None, description="Reasoning trace showing agent's chain-of-thought"
    )
    metadata: Optional[dict] = Field(
        None, description="Additional metadata (e.g., job_id for streaming)"
    )
