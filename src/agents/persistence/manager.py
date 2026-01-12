# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Conversation manager service for coordinating chat persistence with agent orchestration.

This module provides the ConversationManager class which acts as the central
coordinator for:
- Creating and managing conversations
- Persisting messages and reasoning traces
- Providing conversation history to agents
- Managing conversation lifecycle (create, update, archive)
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from uuid import UUID

from src.agents.models import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    Conversation,
    ConversationListItem,
    ConversationSummary,
    ConversationWithMessages,
    Message,
    MessageRole,
    ReasoningTrace,
)
from src.agents.persistence.storage import ChatStorage

logger = logging.getLogger(__name__)


class ConversationManager:
    """Manages conversation lifecycle and persistence.

    This class coordinates between the chat storage layer and the agent
    orchestration layer, ensuring all messages and reasoning traces are
    properly persisted.

    :param storage: ChatStorage instance for persistence
    :type storage: ChatStorage
    :param db_path: Path to SQLite database (used if storage not provided)
    :type db_path: Optional[Path | str]
    """

    def __init__(
        self,
        storage: Optional[ChatStorage] = None,
        db_path: Optional[Path | str] = None,
    ) -> None:
        """Initialize conversation manager.

        :param storage: Optional pre-configured ChatStorage instance
        :type storage: Optional[ChatStorage]
        :param db_path: Path to SQLite database file
        :type db_path: Optional[Path | str]
        """
        if storage:
            self._storage = storage
        else:
            db_path = db_path or Path("data/chat_history.db")
            if isinstance(db_path, str):
                db_path = Path(db_path)
            db_path.parent.mkdir(parents=True, exist_ok=True)
            self._storage = ChatStorage(db_path)

        self._storage.initialize()
        logger.info("ConversationManager initialized with storage at %s", self._storage._db_path)

    @property
    def storage(self) -> ChatStorage:
        """Get the underlying storage instance.

        :returns: ChatStorage instance
        :rtype: ChatStorage
        """
        return self._storage

    def create_conversation(
        self,
        user_id: Optional[str] = None,
        title: Optional[str] = None,
        workspace_id: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> Conversation:
        """Create a new conversation.

        :param user_id: User identifier for multi-user support
        :type user_id: Optional[str]
        :param title: Human-readable conversation title
        :type title: Optional[str]
        :param workspace_id: Initial workspace to bind to conversation
        :type workspace_id: Optional[str]
        :param metadata: Additional metadata
        :type metadata: Optional[dict[str, Any]]
        :returns: Created conversation
        :rtype: Conversation
        """
        conversation = self._storage.create_conversation(
            user_id=user_id,
            title=title,
            workspace_id=workspace_id,
            metadata=metadata,
        )
        logger.info(
            "Created conversation %s for user %s",
            conversation.id,
            user_id or "anonymous",
        )
        return conversation

    def get_conversation(self, conversation_id: UUID | str) -> Optional[Conversation]:
        """Get a conversation by ID.

        :param conversation_id: Conversation ID
        :type conversation_id: UUID | str
        :returns: Conversation if found
        :rtype: Optional[Conversation]
        """
        return self._storage.get_conversation(conversation_id)

    def get_conversation_with_messages(
        self,
        conversation_id: UUID | str,
        message_limit: int = 100,
    ) -> Optional[ConversationWithMessages]:
        """Get a conversation with its messages.

        :param conversation_id: Conversation ID
        :type conversation_id: UUID | str
        :param message_limit: Maximum messages to include
        :type message_limit: int
        :returns: Conversation with messages if found
        :rtype: Optional[ConversationWithMessages]
        """
        return self._storage.get_conversation_with_messages(conversation_id, message_limit)

    def list_conversations(
        self,
        user_id: Optional[str] = None,
        workspace_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Conversation]:
        """List conversations with optional filters.

        :param user_id: Filter by user ID
        :type user_id: Optional[str]
        :param workspace_id: Filter by workspace ID
        :type workspace_id: Optional[str]
        :param limit: Maximum results
        :type limit: int
        :param offset: Results to skip
        :type offset: int
        :returns: List of conversations
        :rtype: list[Conversation]
        """
        return self._storage.list_conversations(
            user_id=user_id,
            workspace_id=workspace_id,
            limit=limit,
            offset=offset,
        )

    def list_conversation_items(
        self,
        user_id: Optional[str] = None,
        workspace_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ConversationListItem]:
        """List conversations as lightweight items for sidebar display.

        Returns only id, title, and updated_at like GitHub Copilot.

        :param user_id: Filter by user ID
        :type user_id: Optional[str]
        :param workspace_id: Filter by workspace ID
        :type workspace_id: Optional[str]
        :param limit: Maximum results
        :type limit: int
        :param offset: Results to skip
        :type offset: int
        :returns: List of conversation items
        :rtype: list[ConversationListItem]
        """
        conversations = self._storage.list_conversations(
            user_id=user_id,
            workspace_id=workspace_id,
            limit=limit,
            offset=offset,
        )
        return [
            ConversationListItem(
                id=conv.id,
                title=conv.title,
                updated_at=conv.updated_at,
            )
            for conv in conversations
        ]

    def delete_conversation(self, conversation_id: UUID | str) -> bool:
        """Delete a conversation and all related data.

        :param conversation_id: Conversation ID
        :type conversation_id: UUID | str
        :returns: True if deleted
        :rtype: bool
        """
        deleted = self._storage.delete_conversation(conversation_id)
        if deleted:
            logger.info("Deleted conversation %s", conversation_id)
        return deleted

    def update_conversation_title(
        self,
        conversation_id: UUID | str,
        title: str,
    ) -> Optional[Conversation]:
        """Update conversation title.

        :param conversation_id: Conversation ID
        :type conversation_id: UUID | str
        :param title: New title
        :type title: str
        :returns: Updated conversation or None if not found
        :rtype: Optional[Conversation]
        """
        conversation = self._storage.get_conversation(conversation_id)
        if not conversation:
            return None

        conversation.title = title
        self._storage.update_conversation(conversation)
        return conversation

    def set_workspace(
        self,
        conversation_id: UUID | str,
        workspace_id: str,
    ) -> Optional[Conversation]:
        """Set the active workspace for a conversation.

        :param conversation_id: Conversation ID
        :type conversation_id: UUID | str
        :param workspace_id: Workspace ID to bind
        :type workspace_id: str
        :returns: Updated conversation or None if not found
        :rtype: Optional[Conversation]
        """
        conversation = self._storage.get_conversation(conversation_id)
        if not conversation:
            return None

        conversation.set_workspace(workspace_id)
        self._storage.update_conversation(conversation)
        logger.info(
            "Set workspace %s for conversation %s",
            workspace_id,
            conversation_id,
        )
        return conversation

    def update_conversation_context(
        self,
        conversation_id: UUID | str,
        sid: Optional[str] = None,
        workspace_id: Optional[str] = None,
    ) -> Optional[Conversation]:
        """Update the conversation context (SID and workspace).

        This persists the context to the database so it survives across
        requests handled by different worker processes.

        :param conversation_id: Conversation ID
        :type conversation_id: UUID | str
        :param sid: SAP System ID to store
        :type sid: Optional[str]
        :param workspace_id: Workspace ID to store
        :type workspace_id: Optional[str]
        :returns: Updated conversation or None if not found
        :rtype: Optional[Conversation]
        """
        conversation = self._storage.get_conversation(conversation_id)
        if not conversation:
            return None

        if sid is not None:
            conversation.metadata["resolved_sid"] = sid
        if workspace_id is not None:
            conversation.active_workspace_id = workspace_id
            conversation.metadata["resolved_workspace"] = workspace_id

        self._storage.update_conversation(conversation)
        logger.debug(
            "Updated context for conversation %s: SID=%s, workspace=%s",
            conversation_id,
            sid,
            workspace_id,
        )
        return conversation

    def get_conversation_context(
        self,
        conversation_id: UUID | str,
    ) -> dict[str, Any]:
        """Get the persisted context for a conversation.

        :param conversation_id: Conversation ID
        :type conversation_id: UUID | str
        :returns: Dict with resolved_sid, resolved_workspace, and any other context
        :rtype: dict[str, Any]
        """
        conversation = self._storage.get_conversation(conversation_id)
        if not conversation:
            return {}

        return {
            "resolved_sid": conversation.metadata.get("resolved_sid"),
            "resolved_workspace": conversation.active_workspace_id
            or conversation.metadata.get("resolved_workspace"),
        }

    def add_user_message(
        self,
        conversation_id: UUID | str,
        content: str,
        metadata: Optional[dict[str, Any]] = None,
    ) -> Message:
        """Add a user message to a conversation.

        :param conversation_id: Conversation ID
        :type conversation_id: UUID | str
        :param content: Message content
        :type content: str
        :param metadata: Additional metadata
        :type metadata: Optional[dict[str, Any]]
        :returns: Created message
        :rtype: Message
        """
        return self._storage.add_message(
            conversation_id=conversation_id,
            role=MessageRole.USER,
            content=content,
            metadata=metadata,
        )

    def add_assistant_message(
        self,
        conversation_id: UUID | str,
        content: str,
        metadata: Optional[dict[str, Any]] = None,
    ) -> Message:
        """Add an assistant message to a conversation.

        :param conversation_id: Conversation ID
        :type conversation_id: UUID | str
        :param content: Message content
        :type content: str
        :param metadata: Additional metadata
        :type metadata: Optional[dict[str, Any]]
        :returns: Created message
        :rtype: Message
        """
        return self._storage.add_message(
            conversation_id=conversation_id,
            role=MessageRole.ASSISTANT,
            content=content,
            metadata=metadata,
        )

    def add_system_message(
        self,
        conversation_id: UUID | str,
        content: str,
        metadata: Optional[dict[str, Any]] = None,
    ) -> Message:
        """Add a system message to a conversation.

        :param conversation_id: Conversation ID
        :type conversation_id: UUID | str
        :param content: Message content
        :type content: str
        :param metadata: Additional metadata
        :type metadata: Optional[dict[str, Any]]
        :returns: Created message
        :rtype: Message
        """
        return self._storage.add_message(
            conversation_id=conversation_id,
            role=MessageRole.SYSTEM,
            content=content,
            metadata=metadata,
        )

    def get_messages(
        self,
        conversation_id: UUID | str,
        limit: int = 100,
    ) -> list[Message]:
        """Get messages from a conversation.

        :param conversation_id: Conversation ID
        :type conversation_id: UUID | str
        :param limit: Maximum messages to return
        :type limit: int
        :returns: List of messages
        :rtype: list[Message]
        """
        return self._storage.get_messages(conversation_id, limit=limit)

    def get_chat_history(
        self,
        conversation_id: UUID | str,
        limit: int = 50,
    ) -> list[ChatMessage]:
        """Get conversation history as ChatMessage list for agent consumption.

        Converts persisted Messages to lightweight ChatMessage DTOs
        suitable for passing to agents.

        :param conversation_id: Conversation ID
        :type conversation_id: UUID | str
        :param limit: Maximum messages to return
        :type limit: int
        :returns: List of ChatMessages
        :rtype: list[ChatMessage]
        """
        messages = self._storage.get_messages(conversation_id, limit=limit)
        return [
            ChatMessage(
                role=msg.role.value if hasattr(msg.role, "value") else msg.role, content=msg.content
            )
            for msg in messages
        ]

    def add_reasoning_trace(
        self,
        conversation_id: UUID | str,
        turn_index: int,
        trace: ReasoningTrace,
    ) -> None:
        """Add a reasoning trace for a conversation turn.

        :param conversation_id: Conversation ID
        :type conversation_id: UUID | str
        :param turn_index: Turn index (0-based)
        :type turn_index: int
        :param trace: Reasoning trace to store
        :type trace: ReasoningTrace
        """
        self._storage.add_reasoning_trace(conversation_id, turn_index, trace)

    def get_reasoning_traces(
        self,
        conversation_id: UUID | str,
    ) -> list[ReasoningTrace]:
        """Get all reasoning traces for a conversation.

        :param conversation_id: Conversation ID
        :type conversation_id: UUID | str
        :returns: List of reasoning traces
        :rtype: list[ReasoningTrace]
        """
        return self._storage.get_reasoning_traces(conversation_id)

    def update_summary(
        self,
        conversation_id: UUID | str,
        summary: str,
        last_message_id: Optional[UUID | str] = None,
        message_count: int = 0,
    ) -> ConversationSummary:
        """Create or update a conversation summary.

        :param conversation_id: Conversation ID
        :type conversation_id: UUID | str
        :param summary: Summary text
        :type summary: str
        :param last_message_id: Last message included in summary
        :type last_message_id: Optional[UUID | str]
        :param message_count: Number of messages summarized
        :type message_count: int
        :returns: Created/updated summary
        :rtype: ConversationSummary
        """
        return self._storage.upsert_summary(
            conversation_id=conversation_id,
            summary=summary,
            last_message_id=last_message_id,
            message_count=message_count,
        )

    def get_summary(
        self,
        conversation_id: UUID | str,
    ) -> Optional[ConversationSummary]:
        """Get the summary for a conversation.

        :param conversation_id: Conversation ID
        :type conversation_id: UUID | str
        :returns: Summary if exists
        :rtype: Optional[ConversationSummary]
        """
        return self._storage.get_summary(conversation_id)

    def process_chat_request(
        self,
        conversation_id: UUID | str,
        user_message: str,
        user_metadata: Optional[dict[str, Any]] = None,
    ) -> tuple[list[ChatMessage], int]:
        """Process incoming chat request - persist user message and get history.

        This is the entry point for handling a new user message:
        1. Persists the user message
        2. Returns the full chat history for agent consumption
        3. Returns the turn index for reasoning trace storage

        :param conversation_id: Conversation ID
        :type conversation_id: UUID | str
        :param user_message: User's message content
        :type user_message: str
        :param user_metadata: Optional metadata for the user message
        :type user_metadata: Optional[dict[str, Any]]
        :returns: Tuple of (chat_history, turn_index)
        :rtype: tuple[list[ChatMessage], int]
        """
        self.add_user_message(
            conversation_id=conversation_id,
            content=user_message,
            metadata=user_metadata,
        )

        chat_history = self.get_chat_history(conversation_id)
        turn_index = sum(1 for msg in chat_history if msg.role == "user") - 1

        return chat_history, turn_index

    def process_chat_response(
        self,
        conversation_id: UUID | str,
        response: ChatResponse,
        turn_index: int,
    ) -> Message:
        """Process outgoing chat response - persist assistant message and trace.

        This is the exit point after agent produces a response:
        1. Persists the assistant message
        2. Persists the reasoning trace if present
        3. Updates conversation timestamp

        :param conversation_id: Conversation ID
        :type conversation_id: UUID | str
        :param response: Agent's ChatResponse
        :type response: ChatResponse
        :param turn_index: Turn index for reasoning trace
        :type turn_index: int
        :returns: Created assistant message
        :rtype: Message
        """
        assistant_content = ""
        if response.messages:
            assistant_content = response.messages[-1].content
        metadata: dict[str, Any] = {}
        if response.test_plan:
            metadata["has_test_plan"] = True
            metadata["test_count"] = response.test_plan.total_tests
        message = self.add_assistant_message(
            conversation_id=conversation_id,
            content=assistant_content,
            metadata=metadata,
        )
        if response.reasoning_trace:
            trace = ReasoningTrace(
                agent_name=response.reasoning_trace.get("agent_name"),
                steps=response.reasoning_trace.get("steps", []),
            )
            self.add_reasoning_trace(
                conversation_id=conversation_id,
                turn_index=turn_index,
                trace=trace,
            )

        return message

    def generate_title_from_first_message(
        self,
        conversation_id: UUID | str,
    ) -> Optional[str]:
        """Generate a title from the first user message.

        Truncates to first 50 characters of first user message.

        :param conversation_id: Conversation ID
        :type conversation_id: UUID | str
        :returns: Generated title or None if no messages
        :rtype: Optional[str]
        """
        messages = self.get_messages(conversation_id, limit=5)
        for msg in messages:
            role_value = msg.role.value if hasattr(msg.role, "value") else msg.role
            if role_value == "user":
                title = msg.content[:50]
                if len(msg.content) > 50:
                    title += "..."
                self.update_conversation_title(conversation_id, title)
                return title
        return None

    def get_turn_count(self, conversation_id: UUID | str) -> int:
        """Get the number of turns in a conversation.

        A turn is defined as a user message followed by an assistant response.

        :param conversation_id: Conversation ID
        :type conversation_id: UUID | str
        :returns: Number of turns
        :rtype: int
        """
        messages = self.get_messages(conversation_id)
        user_count = sum(
            1
            for msg in messages
            if (msg.role.value if hasattr(msg.role, "value") else msg.role) == "user"
        )
        return user_count

    def close(self) -> None:
        """Close the storage connection."""
        self._storage.close()
