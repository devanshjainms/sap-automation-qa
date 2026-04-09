# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""SQLite-backed storage for conversations and messages.

Messages are persisted as serialised Agent Framework ``Message``
dicts -- the canonical message type used across the agent stack.
Uses ``StafStore`` for the shared database connection.
"""

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional
from uuid import UUID, uuid4

from agent_framework import Message as AFMessage

from src.core.models.conversation import (
    Conversation,
    ConversationStatus,
)
from src.core.storage.staf_store import StafStore

logger = logging.getLogger(__name__)

CONVERSATIONS_SCHEMA = """
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
    content             TEXT NOT NULL DEFAULT '',
    af_message          TEXT NOT NULL DEFAULT '{}',
    timestamp           TEXT NOT NULL,
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


class ConversationStore:
    """Conversations and AF messages backed by ``StafStore``.

    :param db: Shared StafStore instance.
    """

    SCHEMA = CONVERSATIONS_SCHEMA

    def __init__(
        self,
        db: Optional[StafStore] = None,
        *,
        db_path: Optional[Path] = None,
    ) -> None:
        if db is None:
            if db_path is None:
                raise ValueError("Either db or db_path must be provided")
            db = StafStore(db_path)
            self._owns_db = True
        else:
            self._owns_db = False
        self._db = db
        self._conn = db.conn
        db.register_schema(self.SCHEMA)
        if self._owns_db:
            db.sync()

    def close(self) -> None:
        """Close the underlying database if this store owns it."""
        if self._owns_db:
            self._db.close()

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
                    self._db.dt_to_iso(conversation.created_at),
                    self._db.dt_to_iso(conversation.updated_at),
                    json.dumps(conversation.metadata, default=str),
                ),
            )
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

        msg_dicts = self._load_af_messages(str(conversation_id))
        return self._row_to_conversation(dict(row), msg_dicts)

    def list_all(
        self,
        include_archived: bool = False,
        limit: int = 50,
    ) -> List[Conversation]:
        """List conversations across all workspaces.

        :param include_archived: Whether to include archived conversations.
        :param limit: Maximum results.
        :returns: List of conversations (without message history).
        """
        self._conn.row_factory = sqlite3.Row
        if include_archived:
            cur = self._conn.execute(
                "SELECT * FROM conversations ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            )
        else:
            cur = self._conn.execute(
                "SELECT * FROM conversations " "WHERE status = ? ORDER BY updated_at DESC LIMIT ?",
                (ConversationStatus.ACTIVE.value, limit),
            )
        return [self._row_to_conversation(dict(r), []) for r in cur.fetchall()]

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
        :returns: List of conversations (without message history).
        """
        self._conn.row_factory = sqlite3.Row
        if include_archived:
            cur = self._conn.execute(
                "SELECT * FROM conversations "
                "WHERE workspace_id = ? ORDER BY updated_at DESC LIMIT ?",
                (workspace_id, limit),
            )
        else:
            cur = self._conn.execute(
                "SELECT * FROM conversations "
                "WHERE workspace_id = ? AND status = ? "
                "ORDER BY updated_at DESC LIMIT ?",
                (workspace_id, ConversationStatus.ACTIVE.value, limit),
            )
        return [self._row_to_conversation(dict(r), []) for r in cur.fetchall()]

    def update_title(self, conversation_id: UUID | str, title: str) -> bool:
        """Update the title of a conversation.

        :param conversation_id: Conversation identifier.
        :param title: New title string.
        :returns: True if conversation was found and updated.
        """
        cid = str(conversation_id)
        now = self._db.dt_to_iso(datetime.now(timezone.utc))
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

        now = self._db.dt_to_iso(datetime.now(timezone.utc))
        with self._conn:
            self._conn.execute(
                "UPDATE conversations SET status = ?, updated_at = ? WHERE id = ?",
                (ConversationStatus.ARCHIVED.value, now, str(conversation_id)),
            )
        return True

    def add_message(
        self,
        conversation_id: UUID | str,
        af_msg: AFMessage,
    ) -> AFMessage:
        """Add an AF message to an existing conversation.

        :param conversation_id: Conversation to add to.
        :param af_msg: Agent Framework Message to persist.
        :returns: The added message.
        :raises ValueError: If conversation not found or archived.
        """
        conv = self.get(conversation_id)
        if conv is None:
            raise ValueError(f"Conversation {conversation_id} not found")
        if conv.is_archived:
            raise ValueError("Cannot add messages to an archived conversation")

        cid = str(conversation_id)
        now = self._db.dt_to_iso(datetime.now(timezone.utc))

        with self._conn:
            msg_id = af_msg.message_id or str(uuid4())
            content = af_msg.text or ""
            self._conn.execute(
                """INSERT INTO messages
                   (id, conversation_id, role, content, af_message, timestamp)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    msg_id,
                    cid,
                    af_msg.role,
                    content,
                    json.dumps(af_msg.to_dict(), default=str),
                    now,
                ),
            )

            updates: dict[str, Any] = {"updated_at": now}
            if not conv.title and af_msg.role == "user" and af_msg.text:
                updates["title"] = af_msg.text[:80]

            set_clause = ", ".join(f"{k} = ?" for k in updates)
            self._conn.execute(
                f"UPDATE conversations SET {set_clause} WHERE id = ?",
                (*updates.values(), cid),
            )
        return af_msg

    def get_history(
        self,
        conversation_id: UUID | str,
        limit: Optional[int] = None,
    ) -> List[AFMessage]:
        """Get ordered AF messages for a conversation.

        :param conversation_id: Conversation identifier.
        :param limit: Optional limit on number of messages returned.
        :returns: List of AF Messages ordered by timestamp.
        """
        dicts = self._load_af_messages(str(conversation_id), limit=limit)
        messages: list[AFMessage] = []
        for d in dicts:
            try:
                # Strip DB metadata keys before deserializing to AFMessage.
                clean = {k: v for k, v in d.items() if not k.startswith("_")}
                messages.append(AFMessage.from_dict(clean))
            except Exception:
                pass
        return messages

    def _load_af_messages(
        self,
        conversation_id: str,
        limit: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        """Load AF message dicts enriched with DB ``id`` and ``timestamp``.

        The returned dicts contain the full AF message payload plus
        ``_id`` and ``_timestamp`` keys from the database row so that
        API serializers can include them in the response without a
        second query.
        """
        self._conn.row_factory = sqlite3.Row
        sql = (
            "SELECT id, af_message, timestamp FROM messages "
            "WHERE conversation_id = ? ORDER BY timestamp ASC"
        )
        params: tuple = (conversation_id,)
        if limit is not None:
            sql += " LIMIT ?"
            params = (conversation_id, limit)

        rows = self._conn.execute(sql, params).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            try:
                af_dict = json.loads(row["af_message"])
                af_dict["_id"] = row["id"]
                af_dict["_timestamp"] = row["timestamp"]
                result.append(af_dict)
            except (json.JSONDecodeError, KeyError):
                pass
        return result

    @staticmethod
    def _row_to_conversation(
        data: dict,
        messages: list[dict[str, Any]],
    ) -> Conversation:
        """Reconstruct a Conversation from a database row + message dicts."""
        return Conversation(
            id=data["id"],
            workspace_id=data["workspace_id"],
            status=data["status"],
            title=data["title"],
            messages=messages,
            triage_session_ids=json.loads(data.get("triage_session_ids", "[]")),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            metadata=json.loads(data.get("metadata", "{}")),
        )
