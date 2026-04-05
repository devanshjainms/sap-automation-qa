# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Conversation and message models for the chat layer.

Domain models (``Message``, ``Conversation``) and API request schemas
live together — there is no separate DTO layer. Pydantic v2's
``model_dump(mode="json")`` handles serialization to JSON-safe types
(UUID → str, datetime → ISO-8601).
"""

from datetime import datetime
from enum import Enum
from typing import Any, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class MessageRole(str, Enum):
    """Role of a message in a conversation."""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"


class ConversationStatus(str, Enum):
    """Status of a conversation."""

    ACTIVE = "active"
    ARCHIVED = "archived"


# ---------------------------------------------------------------------------
# Domain models
# ---------------------------------------------------------------------------


class Message(BaseModel):
    """A single message within a conversation.

    :param id: Unique message identifier.
    :param role: Who produced this message.
    :param content: Message text content (orchestrator's final response).
    :param timestamp: When the message was created.
    :param triage_session_id: Optional link to the triage session.
    :param tool_name: Tool name (for TOOL_CALL/TOOL_RESULT messages).
    :param metadata: For assistant messages holds the raw agent
        framework outputs as ``{"agent_responses": [<AgentResponse.to_dict()>, ...]}``.
        Each entry preserves the full framework schema including
        ``text_reasoning`` content blocks, tool calls, usage, and
        agent identity.  UI/API layers parse what they need.
    """

    model_config = ConfigDict(use_enum_values=True)

    id: UUID = Field(default_factory=uuid4)
    role: MessageRole
    content: str
    thinking: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    triage_session_id: Optional[str] = None
    tool_name: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class Conversation(BaseModel):
    """A chat conversation with state machine (active -> archived).

    Follows the same pattern as ``Job`` and ``TriageSession``:
    mutable Pydantic model with explicit state transitions.

    :param id: Unique conversation identifier.
    :param workspace_id: SAP system workspace this conversation is about.
    :param status: Current conversation status.
    :param title: Conversation title (auto-generated from first message).
    :param messages: Ordered list of messages.
    :param triage_session_ids: IDs of triage sessions linked to this conversation.
    :param created_at: When the conversation was created.
    :param updated_at: When the conversation was last modified.
    :param metadata: Additional context.
    """

    model_config = ConfigDict(populate_by_name=True, use_enum_values=True)

    id: UUID = Field(default_factory=uuid4)
    workspace_id: str
    status: ConversationStatus = ConversationStatus.ACTIVE
    title: str = ""
    messages: list[Message] = Field(default_factory=list)
    triage_session_ids: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def add_message(self, message: Message) -> Message:
        """Append a message to the conversation.

        :param message: Message to add.
        :type message: Message
        :returns: The added message.
        :rtype: Message
        :raises ValueError: If the conversation is archived.
        """
        if ConversationStatus(self.status) == ConversationStatus.ARCHIVED:
            raise ValueError("Cannot add messages to an archived conversation")
        self.messages.append(message)
        self.updated_at = datetime.utcnow()
        if not self.title and message.role == MessageRole.USER:
            self.title = message.content[:80]
        return message

    def link_triage_session(self, session_id: str) -> None:
        """Link a triage session to this conversation.

        :param session_id: Triage session identifier.
        :type session_id: str
        :raises ValueError: If the conversation is archived.
        """
        if ConversationStatus(self.status) == ConversationStatus.ARCHIVED:
            raise ValueError("Cannot link triage sessions to an archived conversation")
        if session_id not in self.triage_session_ids:
            self.triage_session_ids.append(session_id)
            self.updated_at = datetime.utcnow()

    def archive(self) -> None:
        """Archive the conversation.

        :raises ValueError: If already archived.
        """
        if ConversationStatus(self.status) == ConversationStatus.ARCHIVED:
            raise ValueError("Conversation is already archived")
        self.status = ConversationStatus.ARCHIVED
        self.updated_at = datetime.utcnow()

    @property
    def is_archived(self) -> bool:
        """Check if the conversation is archived."""
        return ConversationStatus(self.status) == ConversationStatus.ARCHIVED

    @property
    def message_count(self) -> int:
        """Number of messages in the conversation."""
        return len(self.messages)


# ---------------------------------------------------------------------------
# API request schemas
# ---------------------------------------------------------------------------


class CreateConversationRequest(BaseModel):
    """Request to create a new conversation.

    :param workspace_id: Optional SAP system workspace for this conversation.
    """

    workspace_id: str = ""


class SendMessageRequest(BaseModel):
    """Request to send a message in a conversation.

    :param message: User message text.
    """

    message: str = Field(min_length=1, max_length=10000)
