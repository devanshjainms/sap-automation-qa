# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""
Pydantic models for conversation persistence.

This module defines conversation-related entities for chat history persistence:
- Conversation: A chat session with metadata
- Message: Individual messages within a conversation
- ConversationSummary: Compressed summaries for context management
"""

from datetime import datetime
from typing import Any, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from src.agents.models.chat import MessageRole


class Message(BaseModel):
    """A single message in a conversation.

    Represents a persistent message with full metadata for storage
    and retrieval from the chat history database.

    :param id: Unique message identifier
    :type id: UUID
    :param conversation_id: Parent conversation ID
    :type conversation_id: UUID
    :param role: Message sender role (user, assistant, system, tool)
    :type role: MessageRole
    :param content: Message content
    :type content: str
    :param created_at: Timestamp when message was created
    :type created_at: datetime
    :param metadata: Additional metadata (agent name, phase, tool calls, etc.)
    :type metadata: dict[str, Any]
    """

    id: UUID = Field(default_factory=uuid4)
    conversation_id: UUID
    role: MessageRole
    content: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)

    class Config:
        """Pydantic configuration."""

        use_enum_values = True


class Conversation(BaseModel):
    """A conversation session containing multiple messages.

    Represents a persistent chat session with metadata for user association,
    workspace binding, and lifecycle management.

    :param id: Unique conversation identifier
    :type id: UUID
    :param user_id: User identifier (for multi-user support)
    :type user_id: Optional[str]
    :param title: Human-readable conversation title
    :type title: Optional[str]
    :param created_at: Timestamp when conversation was created
    :type created_at: datetime
    :param updated_at: Timestamp when conversation was last updated
    :type updated_at: datetime
    :param active_workspace_id: Currently active workspace (e.g., DEV-WEEU-SAP01-X00)
    :type active_workspace_id: Optional[str]
    :param metadata: Additional metadata (SID, environment, etc.)
    :type metadata: dict[str, Any]
    """

    id: UUID = Field(default_factory=uuid4)
    user_id: Optional[str] = None
    title: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    active_workspace_id: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    def update_timestamp(self) -> None:
        """Update the updated_at timestamp to now."""
        self.updated_at = datetime.utcnow()

    def set_workspace(self, workspace_id: str) -> None:
        """Set the active workspace for this conversation.

        :param workspace_id: Workspace identifier
        :type workspace_id: str
        """
        self.active_workspace_id = workspace_id
        self.update_timestamp()

    def set_metadata(self, key: str, value: Any) -> None:
        """Set a metadata value.

        :param key: Metadata key
        :type key: str
        :param value: Metadata value
        :type value: Any
        """
        self.metadata[key] = value
        self.update_timestamp()


class ConversationListItem(BaseModel):
    """Lightweight conversation item for list views.

    Used in conversation lists (like GitHub Copilot sidebar) to show
    just the essential info: id, title, and when it was last updated.

    :param id: Unique conversation identifier
    :type id: UUID
    :param title: Human-readable conversation title
    :type title: Optional[str]
    :param updated_at: Timestamp when conversation was last updated
    :type updated_at: datetime
    """

    id: UUID
    title: Optional[str] = None
    updated_at: datetime

    class Config:
        """Pydantic configuration."""

        from_attributes = True


class ConversationSummary(BaseModel):
    """Compressed summary of a conversation for context management.

    Used to provide conversation context to the LLM without
    exceeding token limits. Summaries are generated periodically
    as conversations grow.

    :param conversation_id: Parent conversation ID
    :type conversation_id: UUID
    :param summary: Compressed text summary of the conversation
    :type summary: str
    :param last_message_id: ID of the last message included in summary
    :type last_message_id: Optional[UUID]
    :param message_count: Number of messages summarized
    :type message_count: int
    :param updated_at: Timestamp when summary was last updated
    :type updated_at: datetime
    """

    conversation_id: UUID
    summary: str
    last_message_id: Optional[UUID] = None
    message_count: int = 0
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ConversationWithMessages(BaseModel):
    """Conversation with its messages for API responses.

    Combines conversation metadata with its messages for efficient
    retrieval and display operations.

    :param conversation: The conversation metadata
    :type conversation: Conversation
    :param messages: List of messages in the conversation
    :type messages: list[Message]
    :param summary: Optional conversation summary
    :type summary: Optional[ConversationSummary]
    """

    conversation: Conversation
    messages: list[Message] = Field(default_factory=list)
    summary: Optional[ConversationSummary] = None

    @property
    def message_count(self) -> int:
        """Get the number of messages in the conversation."""
        return len(self.messages)

    def get_recent_messages(self, limit: int = 20) -> list[Message]:
        """Get the most recent messages.

        :param limit: Maximum number of messages to return
        :type limit: int
        :returns: List of recent messages
        :rtype: list[Message]
        """
        return self.messages[-limit:] if self.messages else []
