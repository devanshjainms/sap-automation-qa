# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""API request and response models for REST endpoints.

This module contains Pydantic models for API-layer data transfer objects,
separate from domain models but in the same models package for consistency.
"""

from typing import Any, Optional

from pydantic import BaseModel, Field

from src.agents.models.conversation import Conversation, ConversationListItem, Message


# -------------------------------------------------------------------------
# Health & Status Models
# -------------------------------------------------------------------------


class StatusResponse(BaseModel):
    """Simple status response."""

    status: str = Field(..., description="Status message")


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = Field(default="healthy", description="Health status")


class DebugEnvResponse(BaseModel):
    """Debug environment response."""

    AZURE_OPENAI_ENDPOINT: str = Field(..., description="Azure OpenAI endpoint")
    AZURE_OPENAI_DEPLOYMENT: str = Field(..., description="Azure OpenAI deployment")
    AZURE_OPENAI_API_KEY: str = Field(..., description="Masked API key status")


# -------------------------------------------------------------------------
# Agent Models
# -------------------------------------------------------------------------


class AgentInfo(BaseModel):
    """Information about a single agent."""

    name: str = Field(..., description="Agent name")
    description: str = Field(..., description="Agent description")


class AgentListResponse(BaseModel):
    """Response containing list of agents."""

    agents: list[AgentInfo] = Field(default_factory=list, description="List of agents")
    error: Optional[str] = Field(None, description="Error message if any")


# -------------------------------------------------------------------------
# Conversation Request/Response Models
# -------------------------------------------------------------------------


class CreateConversationRequest(BaseModel):
    """Request to create a new conversation."""

    title: Optional[str] = Field(None, description="Optional title for the conversation")
    workspace_id: Optional[str] = Field(
        None, description="Optional workspace to bind to conversation"
    )
    metadata: Optional[dict[str, Any]] = Field(
        None, description="Optional metadata for the conversation"
    )


class UpdateConversationRequest(BaseModel):
    """Request to update a conversation."""

    title: Optional[str] = Field(None, description="New title for the conversation")
    workspace_id: Optional[str] = Field(
        None, description="New workspace to bind to conversation"
    )


class SendMessageRequest(BaseModel):
    """Request to send a message in a conversation."""

    content: str = Field(..., description="Message content")
    metadata: Optional[dict[str, Any]] = Field(
        None, description="Optional metadata for the message"
    )


class ConversationResponse(BaseModel):
    """Response containing a single conversation."""

    conversation: Conversation

    class Config:
        """Pydantic config."""

        from_attributes = True


class ConversationListResponse(BaseModel):
    """Response containing a list of conversations for sidebar display.

    Like GitHub Copilot, returns only id, title, and updated_at
    for efficient list rendering.
    """

    conversations: list[ConversationListItem]
    total: int = Field(..., description="Total number of conversations matching filters")
    limit: int = Field(..., description="Maximum results per page")
    offset: int = Field(..., description="Number of results skipped")

    class Config:
        """Pydantic config."""

        from_attributes = True


class ConversationDetailResponse(BaseModel):
    """Response containing a conversation with its messages."""

    conversation: Conversation
    messages: list[Message]
    message_count: int

    class Config:
        """Pydantic config."""

        from_attributes = True


class MessageResponse(BaseModel):
    """Response containing a single message."""

    message: Message

    class Config:
        """Pydantic config."""

        from_attributes = True


class MessageListResponse(BaseModel):
    """Response containing a list of messages."""

    messages: list[Message]
    conversation_id: str

    class Config:
        """Pydantic config."""

        from_attributes = True
