# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""SQLite-based chat storage implementation.

This module provides a thread-safe, async-capable storage layer for
conversation persistence using SQLite as the backend. Designed for
local development and single-instance deployments.

For production multi-instance deployments, consider Azure Cosmos DB.
"""

import json
import logging
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Generator, Optional
from uuid import UUID

from src.agents.models import (
    Conversation,
    ConversationSummary,
    ConversationWithMessages,
    Message,
    MessageRole,
)
from src.agents.models.reasoning import ReasoningTrace

logger = logging.getLogger(__name__)


# SQL Schema
_SCHEMA = """
-- Conversations table
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    user_id TEXT,
    title TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    active_workspace_id TEXT,
    metadata TEXT DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_conversations_user_id ON conversations(user_id);
CREATE INDEX IF NOT EXISTS idx_conversations_updated_at ON conversations(updated_at);
CREATE INDEX IF NOT EXISTS idx_conversations_workspace ON conversations(active_workspace_id);

-- Messages table
CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    metadata TEXT DEFAULT '{}',
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation_id ON messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_messages_created_at ON messages(created_at);

-- Conversation summaries table
CREATE TABLE IF NOT EXISTS conversation_summaries (
    conversation_id TEXT PRIMARY KEY,
    summary TEXT NOT NULL,
    last_message_id TEXT,
    message_count INTEGER DEFAULT 0,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);

-- Reasoning traces table
CREATE TABLE IF NOT EXISTS reasoning_traces (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    turn_index INTEGER NOT NULL,
    agent_name TEXT,
    trace_data TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_traces_conversation_id ON reasoning_traces(conversation_id);
CREATE INDEX IF NOT EXISTS idx_traces_turn_index ON reasoning_traces(conversation_id, turn_index);
"""


class ChatStorage:
    """SQLite-based storage for chat conversations.

    Thread-safe implementation using connection-per-thread pattern.
    Supports all CRUD operations for conversations, messages, summaries,
    and reasoning traces.

    :param db_path: Path to SQLite database file (default: chat_history.db)
    :type db_path: Path | str
    """

    def __init__(self, db_path: Path | str = "chat_history.db") -> None:
        """Initialize the chat storage.

        :param db_path: Path to SQLite database file
        :type db_path: Path | str
        """
        self._db_path = Path(db_path)
        self._local = threading.local()
        self._init_lock = threading.Lock()
        self._initialized = False

    def _get_connection(self) -> sqlite3.Connection:
        """Get thread-local database connection.

        :returns: SQLite connection for current thread
        :rtype: sqlite3.Connection
        """
        if not hasattr(self._local, "connection") or self._local.connection is None:
            self._local.connection = sqlite3.connect(
                str(self._db_path),
                detect_types=sqlite3.PARSE_DECLTYPES,
                check_same_thread=False,
            )
            self._local.connection.row_factory = sqlite3.Row
            # Enable foreign keys
            self._local.connection.execute("PRAGMA foreign_keys = ON")
        return self._local.connection

    @contextmanager
    def _transaction(self) -> Generator[sqlite3.Cursor, None, None]:
        """Context manager for database transactions.

        Yields a cursor and commits on success, rolls back on error.

        :yields: Database cursor
        :rtype: Generator[sqlite3.Cursor, None, None]
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            yield cursor
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()

    def initialize(self) -> None:
        """Initialize database schema.

        Creates tables and indexes if they don't exist.
        Thread-safe with double-checked locking.
        """
        if self._initialized:
            return

        with self._init_lock:
            if self._initialized:
                return

            conn = self._get_connection()
            conn.executescript(_SCHEMA)
            conn.commit()
            self._initialized = True
            logger.info("Chat storage initialized at %s", self._db_path)

    def close(self) -> None:
        """Close the thread-local database connection."""
        if hasattr(self._local, "connection") and self._local.connection:
            self._local.connection.close()
            self._local.connection = None

    # -------------------------------------------------------------------------
    # Conversation CRUD
    # -------------------------------------------------------------------------

    def create_conversation(
        self,
        user_id: Optional[str] = None,
        title: Optional[str] = None,
        workspace_id: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> Conversation:
        """Create a new conversation.

        :param user_id: User identifier
        :type user_id: Optional[str]
        :param title: Conversation title
        :type title: Optional[str]
        :param workspace_id: Active workspace ID
        :type workspace_id: Optional[str]
        :param metadata: Additional metadata
        :type metadata: Optional[dict[str, Any]]
        :returns: Created conversation
        :rtype: Conversation
        """
        conversation = Conversation(
            user_id=user_id,
            title=title,
            active_workspace_id=workspace_id,
            metadata=metadata or {},
        )

        with self._transaction() as cursor:
            cursor.execute(
                """
                INSERT INTO conversations 
                (id, user_id, title, created_at, updated_at, active_workspace_id, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(conversation.id),
                    conversation.user_id,
                    conversation.title,
                    conversation.created_at.isoformat(),
                    conversation.updated_at.isoformat(),
                    conversation.active_workspace_id,
                    json.dumps(conversation.metadata),
                ),
            )

        logger.debug("Created conversation %s", conversation.id)
        return conversation

    def get_conversation(self, conversation_id: UUID | str) -> Optional[Conversation]:
        """Get a conversation by ID.

        :param conversation_id: Conversation ID
        :type conversation_id: UUID | str
        :returns: Conversation if found, None otherwise
        :rtype: Optional[Conversation]
        """
        conn = self._get_connection()
        cursor = conn.execute("SELECT * FROM conversations WHERE id = ?", (str(conversation_id),))
        row = cursor.fetchone()
        cursor.close()

        if not row:
            return None

        return self._row_to_conversation(row)

    def update_conversation(self, conversation: Conversation) -> None:
        """Update an existing conversation.

        :param conversation: Conversation to update
        :type conversation: Conversation
        """
        conversation.update_timestamp()

        with self._transaction() as cursor:
            cursor.execute(
                """
                UPDATE conversations
                SET user_id = ?, title = ?, updated_at = ?, 
                    active_workspace_id = ?, metadata = ?
                WHERE id = ?
                """,
                (
                    conversation.user_id,
                    conversation.title,
                    conversation.updated_at.isoformat(),
                    conversation.active_workspace_id,
                    json.dumps(conversation.metadata),
                    str(conversation.id),
                ),
            )

        logger.debug("Updated conversation %s", conversation.id)

    def delete_conversation(self, conversation_id: UUID | str) -> bool:
        """Delete a conversation and all related data.

        :param conversation_id: Conversation ID to delete
        :type conversation_id: UUID | str
        :returns: True if deleted, False if not found
        :rtype: bool
        """
        with self._transaction() as cursor:
            cursor.execute("DELETE FROM conversations WHERE id = ?", (str(conversation_id),))
            deleted = cursor.rowcount > 0

        if deleted:
            logger.debug("Deleted conversation %s", conversation_id)
        return deleted

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
        :param limit: Maximum number of results
        :type limit: int
        :param offset: Number of results to skip
        :type offset: int
        :returns: List of conversations
        :rtype: list[Conversation]
        """
        query = "SELECT * FROM conversations WHERE 1=1"
        params: list[Any] = []

        if user_id:
            query += " AND user_id = ?"
            params.append(user_id)

        if workspace_id:
            query += " AND active_workspace_id = ?"
            params.append(workspace_id)

        query += " ORDER BY updated_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        conn = self._get_connection()
        cursor = conn.execute(query, params)
        rows = cursor.fetchall()
        cursor.close()

        return [self._row_to_conversation(row) for row in rows]

    # -------------------------------------------------------------------------
    # Message CRUD
    # -------------------------------------------------------------------------

    def add_message(
        self,
        conversation_id: UUID | str,
        role: MessageRole | str,
        content: str,
        metadata: Optional[dict[str, Any]] = None,
    ) -> Message:
        """Add a message to a conversation.

        :param conversation_id: Parent conversation ID
        :type conversation_id: UUID | str
        :param role: Message role
        :type role: MessageRole | str
        :param content: Message content
        :type content: str
        :param metadata: Additional metadata
        :type metadata: Optional[dict[str, Any]]
        :returns: Created message
        :rtype: Message
        """
        # Handle both enum and string role
        if isinstance(role, str):
            role_value = role
        else:
            role_value = role.value

        conv_id = (
            UUID(str(conversation_id)) if isinstance(conversation_id, str) else conversation_id
        )
        message = Message(
            conversation_id=conv_id,
            role=MessageRole(role_value),
            content=content,
            metadata=metadata or {},
        )

        with self._transaction() as cursor:
            cursor.execute(
                """
                INSERT INTO messages (id, conversation_id, role, content, created_at, metadata)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(message.id),
                    str(message.conversation_id),
                    role_value,
                    message.content,
                    message.created_at.isoformat(),
                    json.dumps(message.metadata),
                ),
            )

            # Update conversation timestamp
            cursor.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (datetime.utcnow().isoformat(), str(conversation_id)),
            )

        logger.debug("Added message %s to conversation %s", message.id, conversation_id)
        return message

    def get_messages(
        self,
        conversation_id: UUID | str,
        limit: int = 100,
        before_id: Optional[UUID | str] = None,
    ) -> list[Message]:
        """Get messages from a conversation.

        :param conversation_id: Conversation ID
        :type conversation_id: UUID | str
        :param limit: Maximum number of messages
        :type limit: int
        :param before_id: Get messages before this ID (for pagination)
        :type before_id: Optional[UUID | str]
        :returns: List of messages
        :rtype: list[Message]
        """
        query = "SELECT * FROM messages WHERE conversation_id = ?"
        params: list[Any] = [str(conversation_id)]

        if before_id:
            query += " AND created_at < (SELECT created_at FROM messages WHERE id = ?)"
            params.append(str(before_id))

        query += " ORDER BY created_at ASC LIMIT ?"
        params.append(limit)

        conn = self._get_connection()
        cursor = conn.execute(query, params)
        rows = cursor.fetchall()
        cursor.close()

        return [self._row_to_message(row) for row in rows]

    def get_conversation_with_messages(
        self, conversation_id: UUID | str, message_limit: int = 100
    ) -> Optional[ConversationWithMessages]:
        """Get a conversation with its messages.

        :param conversation_id: Conversation ID
        :type conversation_id: UUID | str
        :param message_limit: Maximum number of messages to include
        :type message_limit: int
        :returns: Conversation with messages, or None if not found
        :rtype: Optional[ConversationWithMessages]
        """
        conversation = self.get_conversation(conversation_id)
        if not conversation:
            return None

        messages = self.get_messages(conversation_id, limit=message_limit)
        summary = self.get_summary(conversation_id)

        return ConversationWithMessages(
            conversation=conversation,
            messages=messages,
            summary=summary,
        )

    # -------------------------------------------------------------------------
    # Summary CRUD
    # -------------------------------------------------------------------------

    def upsert_summary(
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
        :param last_message_id: ID of last message in summary
        :type last_message_id: Optional[UUID | str]
        :param message_count: Number of messages summarized
        :type message_count: int
        :returns: Created/updated summary
        :rtype: ConversationSummary
        """
        conv_id = (
            UUID(str(conversation_id)) if isinstance(conversation_id, str) else conversation_id
        )
        last_msg_id = UUID(str(last_message_id)) if last_message_id else None

        summary_obj = ConversationSummary(
            conversation_id=conv_id,
            summary=summary,
            last_message_id=last_msg_id,
            message_count=message_count,
        )

        with self._transaction() as cursor:
            cursor.execute(
                """
                INSERT OR REPLACE INTO conversation_summaries 
                (conversation_id, summary, last_message_id, message_count, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    str(summary_obj.conversation_id),
                    summary_obj.summary,
                    str(summary_obj.last_message_id) if summary_obj.last_message_id else None,
                    summary_obj.message_count,
                    summary_obj.updated_at.isoformat(),
                ),
            )

        logger.debug("Upserted summary for conversation %s", conversation_id)
        return summary_obj

    def get_summary(self, conversation_id: UUID | str) -> Optional[ConversationSummary]:
        """Get the summary for a conversation.

        :param conversation_id: Conversation ID
        :type conversation_id: UUID | str
        :returns: Summary if exists, None otherwise
        :rtype: Optional[ConversationSummary]
        """
        conn = self._get_connection()
        cursor = conn.execute(
            "SELECT * FROM conversation_summaries WHERE conversation_id = ?",
            (str(conversation_id),),
        )
        row = cursor.fetchone()
        cursor.close()

        if not row:
            return None

        return self._row_to_summary(row)

    # -------------------------------------------------------------------------
    # Reasoning Trace CRUD
    # -------------------------------------------------------------------------

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
        with self._transaction() as cursor:
            cursor.execute(
                """
                INSERT INTO reasoning_traces 
                (id, conversation_id, turn_index, agent_name, trace_data, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(trace.trace_id),
                    str(conversation_id),
                    turn_index,
                    trace.agent_name,
                    trace.model_dump_json(),
                    trace.created_at.isoformat(),
                ),
            )

        logger.debug("Added reasoning trace for turn %d", turn_index)

    def get_reasoning_traces(self, conversation_id: UUID | str) -> list[ReasoningTrace]:
        """Get all reasoning traces for a conversation.

        :param conversation_id: Conversation ID
        :type conversation_id: UUID | str
        :returns: List of reasoning traces
        :rtype: list[ReasoningTrace]
        """
        conn = self._get_connection()
        cursor = conn.execute(
            """
            SELECT * FROM reasoning_traces 
            WHERE conversation_id = ? 
            ORDER BY turn_index ASC
            """,
            (str(conversation_id),),
        )
        rows = cursor.fetchall()
        cursor.close()

        return [self._row_to_trace(row) for row in rows]

    # -------------------------------------------------------------------------
    # Row converters
    # -------------------------------------------------------------------------

    @staticmethod
    def _row_to_conversation(row: sqlite3.Row) -> Conversation:
        """Convert database row to Conversation model."""
        return Conversation(
            id=UUID(row["id"]),
            user_id=row["user_id"],
            title=row["title"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            active_workspace_id=row["active_workspace_id"],
            metadata=json.loads(row["metadata"]) if row["metadata"] else {},
        )

    @staticmethod
    def _row_to_message(row: sqlite3.Row) -> Message:
        """Convert database row to Message model."""
        return Message(
            id=UUID(row["id"]),
            conversation_id=UUID(row["conversation_id"]),
            role=MessageRole(row["role"]),
            content=row["content"],
            created_at=datetime.fromisoformat(row["created_at"]),
            metadata=json.loads(row["metadata"]) if row["metadata"] else {},
        )

    @staticmethod
    def _row_to_summary(row: sqlite3.Row) -> ConversationSummary:
        """Convert database row to ConversationSummary model."""
        return ConversationSummary(
            conversation_id=UUID(row["conversation_id"]),
            summary=row["summary"],
            last_message_id=UUID(row["last_message_id"]) if row["last_message_id"] else None,
            message_count=row["message_count"],
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    @staticmethod
    def _row_to_trace(row: sqlite3.Row) -> ReasoningTrace:
        """Convert database row to ReasoningTrace model."""
        trace_data = json.loads(row["trace_data"])
        return ReasoningTrace.model_validate(trace_data)
