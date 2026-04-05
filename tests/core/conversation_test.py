# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for conversation and message models."""

import pytest
from src.core.models.conversation import (
    Conversation,
    ConversationStatus,
    Message,
    MessageRole,
)


class TestMessageRole:
    """Unit tests for MessageRole enum."""

    def test_known_members(self) -> None:
        """Verify expected roles exist."""
        expected = {"user", "assistant", "system", "tool_call", "tool_result"}
        actual = {m.value for m in MessageRole}
        assert actual == expected


class TestConversationStatus:
    """Unit tests for ConversationStatus enum."""

    def test_known_members(self) -> None:
        """Verify expected statuses exist."""
        expected = {"active", "archived"}
        actual = {m.value for m in ConversationStatus}
        assert actual == expected


class TestMessage:
    """Unit tests for Message model."""

    def test_create_user_message(self) -> None:
        """Verify user message creation."""
        msg = Message(
            role=MessageRole.USER,
            content="Why is HANA down?",
        )
        assert msg.role == MessageRole.USER.value
        assert msg.content == "Why is HANA down?"
        assert msg.id is not None
        assert msg.timestamp is not None

    def test_create_assistant_message(self) -> None:
        """Verify assistant message creation."""
        msg = Message(
            role=MessageRole.ASSISTANT,
            content="I found 3 issues...",
        )
        assert msg.role == MessageRole.ASSISTANT.value

    def test_create_tool_call(self) -> None:
        """Verify tool_call message with tool_name."""
        msg = Message(
            role=MessageRole.TOOL_CALL,
            content='{"workspace_id": "WS-001"}',
            tool_name="collect_evidence",
        )
        assert msg.tool_name == "collect_evidence"

    def test_create_tool_result(self) -> None:
        """Verify tool_result message."""
        msg = Message(
            role=MessageRole.TOOL_RESULT,
            content='{"session_id": "sess-1", "status": "collecting"}',
            tool_name="collect_evidence",
            triage_session_id="sess-1",
        )
        assert msg.triage_session_id == "sess-1"

    def test_metadata(self) -> None:
        """Verify metadata field works."""
        msg = Message(
            role=MessageRole.ASSISTANT,
            content="response",
            metadata={"tokens": 150, "model": "gpt-4o"},
        )
        assert msg.metadata["tokens"] == 150

    def test_metadata_stores_agent_responses(self) -> None:
        """Verify metadata can store raw agent framework responses."""
        agent_responses = [
            {
                "type": "agent_response",
                "agent_id": "Triage-Agent",
                "messages": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "contents": [
                            {"type": "text_reasoning", "text": "Checking CIB..."},
                            {"type": "text", "text": "Root cause found."},
                        ],
                    }
                ],
            }
        ]
        msg = Message(
            role=MessageRole.ASSISTANT,
            content="Root cause found.",
            metadata={"agent_responses": agent_responses},
        )
        assert msg.metadata["agent_responses"][0]["agent_id"] == "Triage-Agent"
        contents = msg.metadata["agent_responses"][0]["messages"][0]["contents"]
        reasoning = [c for c in contents if c["type"] == "text_reasoning"]
        assert reasoning[0]["text"] == "Checking CIB..."

    def test_metadata_survives_roundtrip(self) -> None:
        """Verify metadata survives JSON serialization."""
        msg = Message(
            role=MessageRole.ASSISTANT,
            content="answer",
            metadata={"agent_responses": [{"agent_id": "Triage-Agent"}]},
        )
        data = msg.model_dump()
        restored = Message(**data)
        assert restored.metadata["agent_responses"][0]["agent_id"] == "Triage-Agent"

    def test_json_roundtrip(self) -> None:
        """Verify message serializes and deserializes."""
        msg = Message(role=MessageRole.USER, content="test")
        data = msg.model_dump()
        restored = Message(**data)
        assert str(restored.id) == str(msg.id)
        assert restored.content == "test"


class TestConversation:
    """Unit tests for Conversation state machine."""

    def _make_conversation(self) -> Conversation:
        """Create a conversation for testing."""
        return Conversation(workspace_id="WS-001")

    def _make_user_message(self, content: str = "test") -> Message:
        """Create a user message helper."""
        return Message(role=MessageRole.USER, content=content)

    def _make_assistant_message(self, content: str = "response") -> Message:
        """Create an assistant message helper."""
        return Message(role=MessageRole.ASSISTANT, content=content)

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

    def test_add_message(self) -> None:
        """Verify add_message appends and updates timestamp."""
        conv = self._make_conversation()
        msg = self._make_user_message("Why is HANA down?")
        result = conv.add_message(msg)
        assert result is msg
        assert len(conv.messages) == 1
        assert conv.message_count == 1

    def test_auto_title_from_first_user_message(self) -> None:
        """Verify title is auto-set from the first user message."""
        conv = self._make_conversation()
        conv.add_message(self._make_user_message("Why is HANA not syncing?"))
        assert conv.title == "Why is HANA not syncing?"

    def test_title_truncated_at_80_chars(self) -> None:
        """Verify long first messages are truncated for title."""
        conv = self._make_conversation()
        long_msg = "x" * 200
        conv.add_message(self._make_user_message(long_msg))
        assert len(conv.title) == 80

    def test_title_not_overwritten(self) -> None:
        """Verify title is not overwritten by subsequent messages."""
        conv = self._make_conversation()
        conv.add_message(self._make_user_message("First question"))
        conv.add_message(self._make_user_message("Second question"))
        assert conv.title == "First question"

    def test_title_not_set_by_assistant_message(self) -> None:
        """Verify assistant messages don't set the title."""
        conv = self._make_conversation()
        conv.add_message(self._make_assistant_message("Hello"))
        assert conv.title == ""

    def test_add_message_rejected_after_archive(self) -> None:
        """Verify add_message raises after archival."""
        conv = self._make_conversation()
        conv.archive()
        with pytest.raises(ValueError, match="Cannot add messages to an archived conversation"):
            conv.add_message(self._make_user_message())

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
        conv.add_message(self._make_user_message())
        assert conv.message_count == 1
        conv.add_message(self._make_assistant_message())
        assert conv.message_count == 2

    def test_multiple_messages_ordering(self) -> None:
        """Verify messages are stored in order."""
        conv = self._make_conversation()
        conv.add_message(self._make_user_message("q1"))
        conv.add_message(self._make_assistant_message("a1"))
        conv.add_message(self._make_user_message("q2"))
        assert [m.content for m in conv.messages] == ["q1", "a1", "q2"]
        assert [m.role for m in conv.messages] == [
            MessageRole.USER.value,
            MessageRole.ASSISTANT.value,
            MessageRole.USER.value,
        ]

    def test_json_roundtrip(self) -> None:
        """Verify conversation serializes and deserializes."""
        conv = self._make_conversation()
        conv.add_message(self._make_user_message("test"))
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
