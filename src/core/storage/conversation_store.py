# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""SQLite-backed storage for conversations and messages."""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional
from uuid import UUID

from src.core.models.conversation import (
    Conversation,
    ConversationStatus,
    Message,
    MessageRole,
)

_CONVERSATIONS_SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id                  TEXT PRIMARY KEY,
    workspace_id        TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'active',
    title               TEXT NOT NULL DEFAULT '',
    triage_session_ids  TEXT NOT NULL DEFAULT '[]',
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    metadata            TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS messages (
    id                  TEXT PRIMARY KEY,
    conversation_id     TEXT NOT NULL,
    role                TEXT NOT NULL,
    content             TEXT NOT NULL,
    thinking            TEXT,
    timestamp           TEXT NOT NULL,
    triage_session_id   TEXT,
    tool_name           TEXT,
    metadata            TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (conversation_id) REFERENCES conversations(id)
);

CREATE INDEX IF NOT EXISTS idx_conversations_workspace
    ON conversations(workspace_id);
CREATE INDEX IF NOT EXISTS idx_conversations_status
    ON conversations(status);
CREATE INDEX IF NOT EXISTS idx_messages_conversation
    ON messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_messages_timestamp
    ON messages(timestamp);
"""


def _dt_to_iso(dt: Optional[datetime]) -> Optional[str]:
    """Convert datetime to ISO-8601 string for SQLite storage."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


class ConversationStore:
    """SQLite-backed repository for conversations and messages.

    :param db_path: Path to the SQLite database file.
    """

    def __init__(self, db_path: Path | str = "data/conversations.db") -> None:
        """Initialize the conversation store.

        :param db_path: Path to SQLite database file.
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._conn = sqlite3.connect(
            str(self.db_path),
            isolation_level="DEFERRED",
            check_same_thread=False,
        )
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.executescript(_CONVERSATIONS_SCHEMA)

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()

    def create(self, conversation: Conversation) -> Conversation:
        """Create a new conversation.

        :param conversation: Conversation to persist.
        :returns: The persisted conversation.
        """
        with self._conn:
            self._conn.execute(
                """INSERT INTO conversations
                   (id, workspace_id, status, title,
                    triage_session_ids, created_at, updated_at, metadata)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(conversation.id),
                    conversation.workspace_id,
                    (
                        conversation.status
                        if isinstance(conversation.status, str)
                        else conversation.status.value
                    ),
                    conversation.title,
                    json.dumps(conversation.triage_session_ids),
                    _dt_to_iso(conversation.created_at),
                    _dt_to_iso(conversation.updated_at),
                    json.dumps(conversation.metadata, default=str),
                ),
            )
            for msg in conversation.messages:
                self._insert_message(str(conversation.id), msg)
        return conversation

    def get(self, conversation_id: UUID | str) -> Optional[Conversation]:
        """Get a conversation by ID, including all messages.

        :param conversation_id: Conversation identifier.
        :returns: Conversation with messages, or None if not found.
        """
        self._conn.row_factory = sqlite3.Row
        row = self._conn.execute(
            "SELECT * FROM conversations WHERE id = ?",
            (str(conversation_id),),
        ).fetchone()
        if not row:
            return None

        conv_data = dict(row)
        messages = self._load_messages(str(conversation_id))
        return self._row_to_conversation(conv_data, messages)

    def add_message(
        self,
        conversation_id: UUID | str,
        message: Message,
    ) -> Message:
        """Add a message to an existing conversation.

        :param conversation_id: Conversation to add to.
        :param message: Message to add.
        :returns: The added message.
        :raises ValueError: If conversation not found or archived.
        """
        conv = self.get(conversation_id)
        if conv is None:
            raise ValueError(f"Conversation {conversation_id} not found")
        if conv.is_archived:
            raise ValueError("Cannot add messages to an archived conversation")

        cid = str(conversation_id)
        now = _dt_to_iso(datetime.now(timezone.utc))

        with self._conn:
            self._insert_message(cid, message)

            updates = {"updated_at": now}
            if not conv.title and message.role == MessageRole.USER:
                updates["title"] = message.content[:80]

            set_clause = ", ".join(f"{k} = ?" for k in updates)
            self._conn.execute(
                f"UPDATE conversations SET {set_clause} WHERE id = ?",
                (*updates.values(), cid),
            )
        return message

    def get_history(
        self,
        conversation_id: UUID | str,
        limit: Optional[int] = None,
    ) -> List[Message]:
        """Get ordered messages for a conversation.

        :param conversation_id: Conversation identifier.
        :param limit: Optional limit on number of messages returned.
        :returns: List of messages ordered by timestamp.
        """
        return self._load_messages(str(conversation_id), limit=limit)

    def list_all(
        self,
        include_archived: bool = False,
        limit: int = 50,
    ) -> List[Conversation]:
        """List conversations across all workspaces.

        :param include_archived: Whether to include archived conversations.
        :param limit: Maximum results.
        :returns: List of conversations (without full message history).
        """
        self._conn.row_factory = sqlite3.Row
        if include_archived:
            cur = self._conn.execute(
                "SELECT * FROM conversations " "ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            )
        else:
            cur = self._conn.execute(
                "SELECT * FROM conversations "
                "WHERE status = ? "
                "ORDER BY updated_at DESC LIMIT ?",
                (ConversationStatus.ACTIVE.value, limit),
            )

        results: list[Conversation] = []
        for row in cur.fetchall():
            results.append(self._row_to_conversation(dict(row), []))
        return results

    def list_conversations(
        self,
        workspace_id: str,
        include_archived: bool = False,
        limit: int = 50,
    ) -> List[Conversation]:
        """List conversations for a workspace.

        :param workspace_id: Workspace identifier.
        :param include_archived: Whether to include archived conversations.
        :param limit: Maximum results.
        :returns: List of conversations (without full message history).
        """
        self._conn.row_factory = sqlite3.Row
        if include_archived:
            cur = self._conn.execute(
                "SELECT * FROM conversations "
                "WHERE workspace_id = ? "
                "ORDER BY updated_at DESC LIMIT ?",
                (workspace_id, limit),
            )
        else:
            cur = self._conn.execute(
                "SELECT * FROM conversations "
                "WHERE workspace_id = ? AND status = ? "
                "ORDER BY updated_at DESC LIMIT ?",
                (workspace_id, ConversationStatus.ACTIVE.value, limit),
            )

        results: list[Conversation] = []
        for row in cur.fetchall():
            results.append(self._row_to_conversation(dict(row), []))
        return results

    def update_title(
        self,
        conversation_id: UUID | str,
        title: str,
    ) -> bool:
        """Update the title of a conversation.

        :param conversation_id: Conversation identifier.
        :param title: New title string.
        :returns: True if conversation was found and updated.
        """
        cid = str(conversation_id)
        now = _dt_to_iso(datetime.now(timezone.utc))
        with self._conn:
            cur = self._conn.execute(
                "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
                (title, now, cid),
            )
        return cur.rowcount > 0

    def archive(self, conversation_id: UUID | str) -> bool:
        """Archive a conversation.

        :param conversation_id: Conversation to archive.
        :returns: True if conversation was found and archived.
        :raises ValueError: If conversation is already archived.
        """
        conv = self.get(conversation_id)
        if conv is None:
            return False
        if conv.is_archived:
            raise ValueError("Conversation is already archived")

        now = _dt_to_iso(datetime.now(timezone.utc))
        with self._conn:
            self._conn.execute(
                "UPDATE conversations SET status = ?, updated_at = ? " "WHERE id = ?",
                (
                    ConversationStatus.ARCHIVED.value,
                    now,
                    str(conversation_id),
                ),
            )
        return True

    def _insert_message(self, conversation_id: str, msg: Message) -> None:
        """Insert a single message row."""
        self._conn.execute(
            """INSERT INTO messages
               (id, conversation_id, role, content, thinking,
                timestamp, triage_session_id, tool_name, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(msg.id),
                conversation_id,
                msg.role if isinstance(msg.role, str) else msg.role.value,
                msg.content,
                msg.thinking,
                _dt_to_iso(msg.timestamp),
                msg.triage_session_id,
                msg.tool_name,
                json.dumps(msg.metadata, default=str),
            ),
        )

    def _load_messages(
        self,
        conversation_id: str,
        limit: Optional[int] = None,
    ) -> List[Message]:
        """Load messages for a conversation, ordered by timestamp."""
        self._conn.row_factory = sqlite3.Row
        sql = "SELECT * FROM messages " "WHERE conversation_id = ? " "ORDER BY timestamp ASC"
        params: tuple = (conversation_id,)
        if limit is not None:
            sql += " LIMIT ?"
            params = (conversation_id, limit)

        rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_message(dict(row)) for row in rows]

    @staticmethod
    def _row_to_message(data: dict) -> Message:
        """Reconstruct a Message from a database row."""
        return Message(
            id=data["id"],
            role=data["role"],
            content=data["content"],
            thinking=data.get("thinking"),
            timestamp=datetime.fromisoformat(data["timestamp"]),
            triage_session_id=data.get("triage_session_id"),
            tool_name=data.get("tool_name"),
            metadata=json.loads(data["metadata"]),
        )

    @staticmethod
    def _row_to_conversation(data: dict, messages: List[Message]) -> Conversation:
        """Reconstruct a Conversation from a database row + messages."""
        return Conversation(
            id=data["id"],
            workspace_id=data["workspace_id"],
            status=data["status"],
            title=data["title"],
            messages=messages,
            triage_session_ids=json.loads(data["triage_session_ids"]),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            metadata=json.loads(data["metadata"]),
        )
