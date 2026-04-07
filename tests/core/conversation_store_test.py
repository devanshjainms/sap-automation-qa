# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for ConversationStore (AF Message-based)."""

from pathlib import Path
from typing import Generator
from uuid import uuid4

import pytest
from agent_framework import Message as AFMessage

from src.core.models.conversation import (
    Conversation,
    ConversationStatus,
)
from src.core.storage.conversation_store import ConversationStore


@pytest.fixture
def store(tmp_path: Path) -> Generator[ConversationStore, None, None]:
    """Create a ConversationStore backed by a temp database."""
    s = ConversationStore(db_path=tmp_path / "test_conversations.db")
    yield s
    s.close()


def _make_conversation(
    workspace_id: str = "WS-001",
    title: str = "",
) -> Conversation:
    """Build a Conversation with sensible defaults."""
    return Conversation(workspace_id=workspace_id, title=title)


def _make_af_msg(role: str = "user", text: str = "Hello, world!") -> AFMessage:
    """Build an AF Message with sensible defaults."""
    return AFMessage(role, [text])


class TestConversationStoreCreate:
    """Tests for create and get."""

    def test_create_and_get(self, store: ConversationStore) -> None:
        """Verify conversation round-trip through SQLite."""
        conv = _make_conversation()
        store.create(conv)

        loaded = store.get(conv.id)
        assert loaded is not None
        assert loaded.workspace_id == "WS-001"
        assert loaded.status == ConversationStatus.ACTIVE.value

    def test_get_not_found(self, store: ConversationStore) -> None:
        """Verify get returns None for missing conversation."""
        assert store.get(uuid4()) is None


class TestConversationStoreAddMessage:
    """Tests for add_message (AF Message)."""

    def test_add_message(self, store: ConversationStore) -> None:
        """Verify AF message is appended to existing conversation."""
        conv = _make_conversation()
        store.create(conv)

        store.add_message(conv.id, _make_af_msg(text="new message"))

        loaded = store.get(conv.id)
        assert loaded is not None
        assert len(loaded.messages) == 1
        # Messages are AF message dicts
        assert loaded.messages[0]["role"] == "user"

    def test_auto_title_from_first_user_message(self, store: ConversationStore) -> None:
        """Verify title auto-set from first user message."""
        conv = _make_conversation(title="")
        store.create(conv)

        store.add_message(conv.id, _make_af_msg(text="HANA failover investigation"))
        loaded = store.get(conv.id)
        assert loaded is not None
        assert loaded.title == "HANA failover investigation"

    def test_add_message_to_archived_raises(self, store: ConversationStore) -> None:
        """Verify adding to archived conversation raises ValueError."""
        conv = _make_conversation()
        store.create(conv)
        store.archive(conv.id)

        with pytest.raises(ValueError, match="archived"):
            store.add_message(conv.id, _make_af_msg(text="should fail"))

    def test_add_message_not_found_raises(self, store: ConversationStore) -> None:
        """Verify adding to non-existent conversation raises."""
        with pytest.raises(ValueError, match="not found"):
            store.add_message(uuid4(), _make_af_msg(text="nope"))


class TestConversationStoreHistory:
    """Tests for get_history (returns List[AFMessage])."""

    def test_history_ordered_by_timestamp(self, store: ConversationStore) -> None:
        """Verify messages returned in timestamp order."""
        conv = _make_conversation()
        store.create(conv)

        store.add_message(conv.id, _make_af_msg(text="first"))
        store.add_message(conv.id, _make_af_msg(text="second"))
        store.add_message(conv.id, _make_af_msg(text="third"))

        history = store.get_history(conv.id)
        texts = [m.text for m in history]
        assert texts == ["first", "second", "third"]

    def test_history_with_limit(self, store: ConversationStore) -> None:
        """Verify limit caps returned messages."""
        conv = _make_conversation()
        store.create(conv)

        for i in range(10):
            store.add_message(conv.id, _make_af_msg(text=f"msg-{i}"))

        history = store.get_history(conv.id, limit=3)
        assert len(history) == 3

    def test_history_empty_conversation(self, store: ConversationStore) -> None:
        """Verify empty list for conversation with no messages."""
        conv = _make_conversation()
        store.create(conv)
        assert store.get_history(conv.id) == []

    def test_history_returns_af_messages(self, store: ConversationStore) -> None:
        """Verify get_history returns AFMessage objects."""
        conv = _make_conversation()
        store.create(conv)
        store.add_message(conv.id, _make_af_msg(role="user", text="hello"))
        store.add_message(conv.id, _make_af_msg(role="assistant", text="hi"))

        history = store.get_history(conv.id)
        assert len(history) == 2
        assert all(isinstance(m, AFMessage) for m in history)
        assert history[0].role == "user"
        assert history[1].role == "assistant"


class TestConversationStoreList:
    """Tests for list_conversations."""

    def test_list_by_workspace(self, store: ConversationStore) -> None:
        """Verify filtering by workspace_id."""
        store.create(_make_conversation(workspace_id="WS-A"))
        store.create(_make_conversation(workspace_id="WS-A"))
        store.create(_make_conversation(workspace_id="WS-B"))

        results = store.list_conversations(workspace_id="WS-A")
        assert len(results) == 2
        assert all(c.workspace_id == "WS-A" for c in results)

    def test_list_excludes_archived(self, store: ConversationStore) -> None:
        """Verify archived conversations are excluded by default."""
        conv = _make_conversation()
        store.create(conv)
        store.archive(conv.id)

        store.create(_make_conversation())

        results = store.list_conversations(workspace_id="WS-001", include_archived=False)
        assert len(results) == 1

    def test_list_includes_archived(self, store: ConversationStore) -> None:
        """Verify include_archived flag includes archived."""
        conv = _make_conversation()
        store.create(conv)
        store.archive(conv.id)

        results = store.list_conversations(workspace_id="WS-001", include_archived=True)
        assert len(results) == 1

    def test_list_respects_limit(self, store: ConversationStore) -> None:
        """Verify limit on list_conversations."""
        for _ in range(10):
            store.create(_make_conversation())

        results = store.list_conversations(workspace_id="WS-001", limit=3)
        assert len(results) == 3

    def test_list_no_messages_loaded(self, store: ConversationStore) -> None:
        """Verify listed conversations don't include full message history."""
        conv = _make_conversation()
        store.create(conv)
        store.add_message(conv.id, _make_af_msg(text="hello"))

        results = store.list_conversations(workspace_id="WS-001")
        assert len(results) == 1
        assert results[0].messages == []


class TestConversationStoreArchive:
    """Tests for archive."""

    def test_archive(self, store: ConversationStore) -> None:
        """Verify archiving sets status to archived."""
        conv = _make_conversation()
        store.create(conv)

        result = store.archive(conv.id)
        assert result is True

        loaded = store.get(conv.id)
        assert loaded is not None
        assert loaded.status == ConversationStatus.ARCHIVED.value

    def test_archive_nonexistent(self, store: ConversationStore) -> None:
        """Verify archive returns False for missing conversation."""
        assert store.archive(uuid4()) is False

    def test_double_archive_raises(self, store: ConversationStore) -> None:
        """Verify archiving an already-archived conversation raises."""
        conv = _make_conversation()
        store.create(conv)
        store.archive(conv.id)

        with pytest.raises(ValueError, match="already archived"):
            store.archive(conv.id)
