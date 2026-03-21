# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for ConversationStore — CRUD, archival, message ordering, thinking."""

from datetime import datetime, timezone
from pathlib import Path
from typing import Generator

import pytest
from src.core.models.conversation import (
    Conversation,
    ConversationStatus,
    Message,
    MessageRole,
)
from src.core.storage.conversation_store import ConversationStore


@pytest.fixture
def store(tmp_path: Path) -> Generator[ConversationStore, None, None]:
    """Create a ConversationStore backed by a temp database."""
    s = ConversationStore(db_path=tmp_path / "test_conv.db")
    yield s
    s.close()


def _make_conversation(
    workspace_id: str = "WS-01",
    title: str = "",
) -> Conversation:
    """Build a minimal active conversation."""
    return Conversation(workspace_id=workspace_id, title=title)


def _make_message(
    role: MessageRole = MessageRole.USER,
    content: str = "Hello",
    thinking: str | None = None,
    triage_session_id: str | None = None,
) -> Message:
    """Build a minimal message."""
    return Message(
        role=role,
        content=content,
        thinking=thinking,
        triage_session_id=triage_session_id,
    )


# ─── Create + Get ─────────────────────────────────────────────


class TestCreateAndGet:
    """Tests for create() and get() round-trip."""

    def test_create_and_get(self, store: ConversationStore) -> None:
        """Verify a created conversation can be retrieved."""
        conv = _make_conversation(title="Test conversation")
        store.create(conv)

        loaded = store.get(conv.id)
        assert loaded is not None
        assert loaded.workspace_id == "WS-01"
        assert loaded.title == "Test conversation"
        assert loaded.status == ConversationStatus.ACTIVE.value

    def test_get_nonexistent(self, store: ConversationStore) -> None:
        """Verify get() returns None for unknown ID."""
        assert store.get("nonexistent-id") is None

    def test_create_with_messages(self, store: ConversationStore) -> None:
        """Verify conversation created with inline messages persists them."""
        msg = _make_message(content="inline msg")
        conv = Conversation(workspace_id="WS-01", messages=[msg])
        store.create(conv)

        loaded = store.get(conv.id)
        assert loaded is not None
        assert len(loaded.messages) == 1
        assert loaded.messages[0].content == "inline msg"


# ─── Add Message ──────────────────────────────────────────────


class TestAddMessage:
    """Tests for add_message()."""

    def test_add_message(self, store: ConversationStore) -> None:
        """Verify a message can be added to an active conversation."""
        conv = _make_conversation()
        store.create(conv)

        msg = _make_message(content="first message")
        store.add_message(conv.id, msg)

        loaded = store.get(conv.id)
        assert loaded is not None
        assert len(loaded.messages) == 1
        assert loaded.messages[0].content == "first message"

    def test_add_message_to_nonexistent(self, store: ConversationStore) -> None:
        """Verify adding to nonexistent conversation raises ValueError."""
        msg = _make_message()
        with pytest.raises(ValueError, match="not found"):
            store.add_message("no-such-id", msg)

    def test_add_message_to_archived(self, store: ConversationStore) -> None:
        """Verify adding to archived conversation raises ValueError."""
        conv = _make_conversation()
        store.create(conv)
        store.archive(conv.id)

        msg = _make_message()
        with pytest.raises(ValueError, match="archived"):
            store.add_message(conv.id, msg)

    def test_auto_title_from_first_user_message(self, store: ConversationStore) -> None:
        """Verify title auto-set from first USER message when empty."""
        conv = _make_conversation(title="")
        store.create(conv)

        msg = _make_message(role=MessageRole.USER, content="Why is HANA down?")
        store.add_message(conv.id, msg)

        loaded = store.get(conv.id)
        assert loaded is not None
        assert loaded.title == "Why is HANA down?"


# ─── Message Ordering ────────────────────────────────────────


class TestGetHistory:
    """Tests for get_history() — ordered messages and limit."""

    def test_messages_ordered_by_timestamp(self, store: ConversationStore) -> None:
        """Verify messages returned in timestamp order."""
        conv = _make_conversation()
        store.create(conv)

        m1 = Message(
            role=MessageRole.USER,
            content="first",
            timestamp=datetime(2025, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
        )
        m2 = Message(
            role=MessageRole.ASSISTANT,
            content="second",
            timestamp=datetime(2025, 1, 1, 10, 0, 1, tzinfo=timezone.utc),
        )
        m3 = Message(
            role=MessageRole.USER,
            content="third",
            timestamp=datetime(2025, 1, 1, 10, 0, 2, tzinfo=timezone.utc),
        )
        # Insert out of order
        store.add_message(conv.id, m3)
        store.add_message(conv.id, m1)
        store.add_message(conv.id, m2)

        history = store.get_history(conv.id)
        assert [m.content for m in history] == ["first", "second", "third"]

    def test_history_limit(self, store: ConversationStore) -> None:
        """Verify limit caps results."""
        conv = _make_conversation()
        store.create(conv)

        for i in range(5):
            store.add_message(
                conv.id,
                Message(
                    role=MessageRole.USER,
                    content=f"msg-{i}",
                    timestamp=datetime(2025, 1, 1, 10, 0, i, tzinfo=timezone.utc),
                ),
            )

        history = store.get_history(conv.id, limit=3)
        assert len(history) == 3

    def test_history_empty_conversation(self, store: ConversationStore) -> None:
        """Verify empty history for new conversation."""
        conv = _make_conversation()
        store.create(conv)
        assert store.get_history(conv.id) == []


# ─── Thinking column ──────────────────────────────────────────


class TestThinkingColumn:
    """Tests for nullable thinking field persistence."""

    def test_thinking_stored_and_retrieved(self, store: ConversationStore) -> None:
        """Verify thinking is persisted in the messages table."""
        conv = _make_conversation()
        store.create(conv)

        msg = _make_message(
            role=MessageRole.ASSISTANT,
            content="The root cause is fencing timeout.",
            thinking="I need to check the corosync logs for timeout evidence.",
        )
        store.add_message(conv.id, msg)

        history = store.get_history(conv.id)
        assert len(history) == 1
        assert history[0].thinking == ("I need to check the corosync logs for timeout evidence.")

    def test_thinking_null_when_absent(self, store: ConversationStore) -> None:
        """Verify thinking is None for messages without it."""
        conv = _make_conversation()
        store.create(conv)

        msg = _make_message(role=MessageRole.USER, content="What happened?")
        store.add_message(conv.id, msg)

        history = store.get_history(conv.id)
        assert history[0].thinking is None


# ─── List conversations ───────────────────────────────────────


class TestListConversations:
    """Tests for list_conversations(workspace_id)."""

    def test_filter_by_workspace(self, store: ConversationStore) -> None:
        """Verify only conversations for the given workspace are returned."""
        store.create(_make_conversation(workspace_id="WS-A"))
        store.create(_make_conversation(workspace_id="WS-A"))
        store.create(_make_conversation(workspace_id="WS-B"))

        result = store.list_conversations("WS-A")
        assert len(result) == 2

    def test_exclude_archived_by_default(self, store: ConversationStore) -> None:
        """Verify archived conversations excluded by default."""
        c1 = _make_conversation(workspace_id="WS-A")
        c2 = _make_conversation(workspace_id="WS-A")
        store.create(c1)
        store.create(c2)
        store.archive(c1.id)

        result = store.list_conversations("WS-A")
        assert len(result) == 1

    def test_include_archived(self, store: ConversationStore) -> None:
        """Verify include_archived=True returns everything."""
        c1 = _make_conversation(workspace_id="WS-A")
        c2 = _make_conversation(workspace_id="WS-A")
        store.create(c1)
        store.create(c2)
        store.archive(c1.id)

        result = store.list_conversations("WS-A", include_archived=True)
        assert len(result) == 2

    def test_limit(self, store: ConversationStore) -> None:
        """Verify limit caps results."""
        for _ in range(5):
            store.create(_make_conversation(workspace_id="WS-A"))

        result = store.list_conversations("WS-A", limit=3)
        assert len(result) == 3


# ─── Archive ──────────────────────────────────────────────────


class TestArchive:
    """Tests for archive() state transition."""

    def test_archive_conversation(self, store: ConversationStore) -> None:
        """Verify archive sets status to archived."""
        conv = _make_conversation()
        store.create(conv)

        result = store.archive(conv.id)
        assert result is True

        loaded = store.get(conv.id)
        assert loaded is not None
        assert loaded.status == ConversationStatus.ARCHIVED.value

    def test_archive_already_archived_raises(self, store: ConversationStore) -> None:
        """Verify archiving an already archived conversation raises."""
        conv = _make_conversation()
        store.create(conv)
        store.archive(conv.id)

        with pytest.raises(ValueError, match="already archived"):
            store.archive(conv.id)

    def test_archive_nonexistent_returns_false(self, store: ConversationStore) -> None:
        """Verify archiving nonexistent conversation returns False."""
        assert store.archive("no-such-id") is False


# ─── Triage session linkage ───────────────────────────────────


class TestTriageSessionLink:
    """Tests for triage_session_id on messages."""

    def test_triage_session_id_persisted(self, store: ConversationStore) -> None:
        """Verify message triage_session_id round-trips through DB."""
        conv = _make_conversation()
        store.create(conv)

        msg = _make_message(
            role=MessageRole.ASSISTANT,
            content="Starting triage...",
            triage_session_id="TS-001",
        )
        store.add_message(conv.id, msg)

        history = store.get_history(conv.id)
        assert history[0].triage_session_id == "TS-001"
