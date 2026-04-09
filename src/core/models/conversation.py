# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Conversation domain models for the chat layer.

Messages are stored as Agent Framework ``Message`` objects -- the
canonical message type used across the entire agent stack.  This
module defines only the *conversation envelope* (metadata, status,
title) and the API request schema.  ``agent_framework.Message`` is
used directly for all message persistence and serialization.
"""

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4
from agent_framework import Message as AFMessage
from pydantic import BaseModel, ConfigDict, Field


class ConversationStatus(str, Enum):
    """Status of a conversation."""

    ACTIVE = "active"
    ARCHIVED = "archived"


class Conversation(BaseModel):
    """A chat conversation with state machine (active -> archived).

    Messages are stored separately in the database as serialized AF
    ``Message`` dicts.  The ``messages`` field is populated only when
    the full conversation is loaded (``ConversationStore.get``); list
    endpoints leave it empty for performance.

    :param id: Unique conversation identifier.
    :param workspace_id: SAP system workspace this conversation is about.
    :param status: Current conversation status.
    :param title: Conversation title (auto-generated from first message).
    :param messages: Ordered list of AF message dicts (loaded on demand).
    :param triage_session_ids: IDs of triage sessions linked.
    :param created_at: When the conversation was created.
    :param updated_at: When the conversation was last modified.
    :param metadata: Additional context.
    """

    model_config = ConfigDict(populate_by_name=True, use_enum_values=True)

    id: UUID = Field(default_factory=uuid4)
    workspace_id: str
    status: ConversationStatus = ConversationStatus.ACTIVE
    title: str = ""
    messages: list[dict[str, Any]] = Field(default_factory=list)
    triage_session_ids: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def add_af_message(self, af_msg: AFMessage) -> dict[str, Any]:
        """Append an AF message dict to the conversation.

        :param af_msg: Agent Framework Message to add.
        :returns: The serialized message dict.
        :raises ValueError: If the conversation is archived.
        """
        if ConversationStatus(self.status) == ConversationStatus.ARCHIVED:
            raise ValueError("Cannot add messages to an archived conversation")
        msg_dict = af_msg.to_dict()
        self.messages.append(msg_dict)
        self.updated_at = datetime.utcnow()
        if not self.title and af_msg.role == "user" and af_msg.text:
            self.title = af_msg.text[:80]
        return msg_dict

    def link_triage_session(self, session_id: str) -> None:
        """Link a triage session to this conversation.

        :param session_id: Triage session identifier.
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


class CreateConversationRequest(BaseModel):
    """Request to create a new conversation.

    :param workspace_id: Optional SAP system workspace for this conversation.
    """

    workspace_id: str = ""

