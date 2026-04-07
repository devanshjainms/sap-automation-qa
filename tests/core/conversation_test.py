# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for conversation domain models (AF Message-based)."""

import pytest
from agent_framework import Message as AFMessage

from src.core.models.conversation import (
    Conversation,
    ConversationStatus,
)


class TestConversationStatus:
    """Unit tests for ConversationStatus enum."""

    def test_known_members(self) -> None:
        """Verify expected statuses exist."""
        expected = {"active", "archived"}
        actual = {m.value for m in ConversationStatus}
        assert actual == expected


class TestConversation:
    """Unit tests for Conversation state machine with AF Messages."""

    def _make_conversation(self) -> Conversation:
        """Create a conversation for testing."""
        return Conversation(workspace_id="WS-001")

    @staticmethod
    def _make_user_msg(text: str = "test") -> AFMessage:
        """Create a user AF message."""
        return AFMessage("user", [text])

    @staticmethod
    def _make_assistant_msg(text: str = "response") -> AFMessage:
        """Create an assistant AF message."""
        return AFMessage("assistant", [text])

    def test_defaults(self) -> None:
        """Verify new conversation has correct defaults."""
        conv = self._make_conversation()
        assert conv.status == ConversationStatus.ACTIVE.value
        assert conv.id is not None
        assert conv.messages == []
        assert conv.triage_session_ids == []
        assert conv.title == ""
        assert not conv.is_archived
        assert conv.message_count == 0

    def test_add_af_message(self) -> None:
        """Verify add_af_message appends and updates timestamp."""
        conv = self._make_conversation()
        msg = self._make_user_msg("Why is HANA down?")
        result = conv.add_af_message(msg)
        assert isinstance(result, dict)
        assert result["role"] == "user"
        assert len(conv.messages) == 1
        assert conv.message_count == 1

    def test_auto_title_from_first_user_message(self) -> None:
        """Verify title is auto-set from the first user message."""
        conv = self._make_conversation()
        conv.add_af_message(self._make_user_msg("Why is HANA not syncing?"))
        assert conv.title == "Why is HANA not syncing?"

    def test_title_truncated_at_80_chars(self) -> None:
        """Verify long first messages are truncated for title."""
        conv = self._make_conversation()
        conv.add_af_message(self._make_user_msg("x" * 200))
        assert len(conv.title) == 80

    def test_title_not_overwritten(self) -> None:
        """Verify title is not overwritten by subsequent messages."""
        conv = self._make_conversation()
        conv.add_af_message(self._make_user_msg("First question"))
        conv.add_af_message(self._make_user_msg("Second question"))
        assert conv.title == "First question"

    def test_title_not_set_by_assistant_message(self) -> None:
        """Verify assistant messages don't set the title."""
        conv = self._make_conversation()
        conv.add_af_message(self._make_assistant_msg("Hello"))
        assert conv.title == ""

    def test_add_af_message_rejected_after_archive(self) -> None:
        """Verify add_af_message raises after archival."""
        conv = self._make_conversation()
        conv.archive()
        with pytest.raises(ValueError, match="Cannot add messages to an archived conversation"):
            conv.add_af_message(self._make_user_msg())

    def test_link_triage_session(self) -> None:
        """Verify linking triage sessions."""
        conv = self._make_conversation()
        conv.link_triage_session("sess-1")
        assert conv.triage_session_ids == ["sess-1"]

    def test_link_triage_session_deduplication(self) -> None:
        """Verify duplicate session IDs are not added."""
        conv = self._make_conversation()
        conv.link_triage_session("sess-1")
        conv.link_triage_session("sess-1")
        assert conv.triage_session_ids == ["sess-1"]

    def test_link_triage_session_rejected_after_archive(self) -> None:
        """Verify linking rejected after archival."""
        conv = self._make_conversation()
        conv.archive()
        with pytest.raises(ValueError, match="archived"):
            conv.link_triage_session("sess-1")

    def test_archive(self) -> None:
        """Verify archive transitions to ARCHIVED."""
        conv = self._make_conversation()
        conv.archive()
        assert conv.is_archived
        assert conv.status == ConversationStatus.ARCHIVED.value

    def test_double_archive_raises(self) -> None:
        """Verify archiving already archived raises ValueError."""
        conv = self._make_conversation()
        conv.archive()
        with pytest.raises(ValueError, match="already archived"):
            conv.archive()

    def test_is_archived_property(self) -> None:
        """Verify is_archived reflects status."""
        conv = self._make_conversation()
        assert conv.is_archived is False
        conv.archive()
        assert conv.is_archived is True

    def test_message_count_property(self) -> None:
        """Verify message_count increments correctly."""
        conv = self._make_conversation()
        assert conv.message_count == 0
        conv.add_af_message(self._make_user_msg())
        assert conv.message_count == 1
        conv.add_af_message(self._make_assistant_msg())
        assert conv.message_count == 2

    def test_multiple_messages_ordering(self) -> None:
        """Verify messages are stored in order."""
        conv = self._make_conversation()
        conv.add_af_message(self._make_user_msg("q1"))
        conv.add_af_message(self._make_assistant_msg("a1"))
        conv.add_af_message(self._make_user_msg("q2"))
        roles = [m["role"] for m in conv.messages]
        assert roles == ["user", "assistant", "user"]

    def test_json_roundtrip(self) -> None:
        """Verify conversation serializes and deserializes."""
        conv = self._make_conversation()
        conv.add_af_message(self._make_user_msg("test"))
        data = conv.model_dump()
        restored = Conversation(**data)
        assert str(restored.id) == str(conv.id)
        assert restored.message_count == 1

    def test_metadata(self) -> None:
        """Verify metadata field works."""
        conv = Conversation(
            workspace_id="WS-001",
            metadata={"agent": "SapAgent"},
        )
        assert conv.metadata["agent"] == "SapAgent"
