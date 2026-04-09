# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for ConversationHistoryProvider silent-tool-call sanitization and title generation."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent_framework import Message as AFMessage
from agent_framework._types import Content
from src.agents.providers.history_provider import ConversationHistoryProvider


def _af(role: str, contents: list[dict]) -> AFMessage:
    """Build an AFMessage from a role and raw content dicts."""
    return AFMessage.from_dict(
        {
            "type": "message",
            "role": role,
            "contents": contents,
            "additional_properties": {},
        }
    )


class TestSanitizeSilentToolCall:
    """Validate _sanitize_silent_tool_call injects text into silent assistant msgs."""

    def test_assistant_with_only_function_call_gets_text(self):
        msg = _af(
            "assistant",
            [
                {
                    "type": "function_call",
                    "call_id": "call_1",
                    "name": "list_workspaces",
                    "arguments": "{}",
                }
            ],
        )
        result = ConversationHistoryProvider._sanitize_silent_tool_call(msg)

        result_dict = result.to_dict()
        assert len(result_dict["contents"]) == 2
        assert result_dict["contents"][0]["type"] == "text"
        assert "list_workspaces" in result_dict["contents"][0]["text"]
        assert result_dict["contents"][1]["type"] == "function_call"

    def test_assistant_with_text_and_call_unchanged(self):
        msg = _af(
            "assistant",
            [
                {"type": "text", "text": "I'll check the workspaces."},
                {
                    "type": "function_call",
                    "call_id": "call_1",
                    "name": "list_workspaces",
                    "arguments": "{}",
                },
            ],
        )
        result = ConversationHistoryProvider._sanitize_silent_tool_call(msg)

        result_dict = result.to_dict()
        assert len(result_dict["contents"]) == 2
        assert result_dict["contents"][0]["type"] == "text"
        assert result_dict["contents"][0]["text"] == "I'll check the workspaces."

    def test_tool_role_message_unchanged(self):
        msg = _af(
            "tool",
            [
                {
                    "type": "function_result",
                    "call_id": "call_1",
                    "result": "data",
                }
            ],
        )
        result = ConversationHistoryProvider._sanitize_silent_tool_call(msg)
        assert result is msg

    def test_user_message_unchanged(self):
        msg = _af("user", [{"type": "text", "text": "hello"}])
        result = ConversationHistoryProvider._sanitize_silent_tool_call(msg)
        assert result is msg

    def test_assistant_text_only_unchanged(self):
        msg = _af("assistant", [{"type": "text", "text": "Here is the answer."}])
        result = ConversationHistoryProvider._sanitize_silent_tool_call(msg)

        result_dict = result.to_dict()
        assert len(result_dict["contents"]) == 1
        assert result_dict["contents"][0]["type"] == "text"

    def test_multiple_function_calls_listed(self):
        msg = _af(
            "assistant",
            [
                {
                    "type": "function_call",
                    "call_id": "c1",
                    "name": "list_workspaces",
                    "arguments": "{}",
                },
                {
                    "type": "function_call",
                    "call_id": "c2",
                    "name": "run_evidence_collector",
                    "arguments": "{}",
                },
            ],
        )
        result = ConversationHistoryProvider._sanitize_silent_tool_call(msg)

        result_dict = result.to_dict()
        assert len(result_dict["contents"]) == 3
        text = result_dict["contents"][0]["text"]
        assert "list_workspaces" in text
        assert "run_evidence_collector" in text

    def test_empty_contents_unchanged(self):
        msg = _af("assistant", [])
        result = ConversationHistoryProvider._sanitize_silent_tool_call(msg)
        assert result.to_dict()["contents"] == []

    def test_original_not_mutated(self):
        msg = _af(
            "assistant",
            [
                {
                    "type": "function_call",
                    "call_id": "call_1",
                    "name": "my_tool",
                    "arguments": "{}",
                }
            ],
        )
        original_len = len(msg.to_dict()["contents"])
        _ = ConversationHistoryProvider._sanitize_silent_tool_call(msg)
        assert len(msg.to_dict()["contents"]) == original_len


class TestTitleGeneration:
    """Validate _set_title fire-and-forget behaviour."""

    @pytest.mark.asyncio
    async def test_set_title_calls_generator_and_updates_store(self):
        """Title generator result is persisted via store.update_title."""
        store = MagicMock()
        store.update_title = MagicMock(return_value=True)
        gen = AsyncMock(return_value="X02 SCS Cluster Health")

        provider = ConversationHistoryProvider(store, title_generator=gen)
        await provider._set_title("conv-123", "is the x02 scs cluster stable?")

        gen.assert_awaited_once_with("is the x02 scs cluster stable?")
        store.update_title.assert_called_once_with("conv-123", "X02 SCS Cluster Health")

    @pytest.mark.asyncio
    async def test_set_title_strips_quotes(self):
        """Surrounding quotes from LLM output are stripped."""
        store = MagicMock()
        store.update_title = MagicMock(return_value=True)
        gen = AsyncMock(return_value='"Check X02 DB nodes"')

        provider = ConversationHistoryProvider(store, title_generator=gen)
        await provider._set_title("c1", "check the db nodes")

        store.update_title.assert_called_once_with("c1", "Check X02 DB nodes")

    @pytest.mark.asyncio
    async def test_set_title_truncates_to_80_chars(self):
        """Title is truncated to 80 characters max."""
        store = MagicMock()
        store.update_title = MagicMock(return_value=True)
        gen = AsyncMock(return_value="A" * 100)

        provider = ConversationHistoryProvider(store, title_generator=gen)
        await provider._set_title("c1", "long question")

        title_arg = store.update_title.call_args[0][1]
        assert len(title_arg) == 80

    @pytest.mark.asyncio
    async def test_set_title_swallows_generator_errors(self):
        """Generator exceptions are logged but do not propagate."""
        store = MagicMock()
        gen = AsyncMock(side_effect=RuntimeError("LLM down"))

        provider = ConversationHistoryProvider(store, title_generator=gen)
        # Should not raise.
        await provider._set_title("c1", "test")

        store.update_title.assert_not_called()

    @pytest.mark.asyncio
    async def test_set_title_skips_empty_result(self):
        """Empty generator results do not update the store."""
        store = MagicMock()
        store.update_title = MagicMock(return_value=True)
        gen = AsyncMock(return_value="   ")

        provider = ConversationHistoryProvider(store, title_generator=gen)
        await provider._set_title("c1", "test")

        store.update_title.assert_not_called()

    def test_no_title_generator_means_no_title(self):
        """Provider without title_generator skips title generation."""
        store = MagicMock()
        provider = ConversationHistoryProvider(store)
        assert provider._title_generator is None


class TestConversationIdAndSaveEnabled:
    """Validate conversation_id and save_enabled parameters."""

    def test_explicit_conversation_id_returned(self):
        """_get_conv_id returns explicit conversation_id when set."""
        store = MagicMock()
        provider = ConversationHistoryProvider(
            store,
            conversation_id="explicit-123",
        )
        session = MagicMock()
        context = MagicMock()
        context.service_session_id = "should-be-ignored"
        assert provider._get_conv_id(session, context) == "explicit-123"

    def test_fallback_to_session_when_no_explicit_id(self):
        """_get_conv_id falls back to session lookup when no explicit id."""
        store = MagicMock()
        provider = ConversationHistoryProvider(store)
        session = MagicMock()
        session.service_session_id = "from-session"
        context = MagicMock(spec=[])
        context.session_id = ""
        assert provider._get_conv_id(session, context) == "from-session"

    @pytest.mark.asyncio
    async def test_save_disabled_skips_after_run(self):
        """after_run is a no-op when save_enabled=False."""
        store = MagicMock()
        provider = ConversationHistoryProvider(
            store,
            conversation_id="conv-1",
            save_enabled=False,
        )
        await provider.after_run(
            agent=MagicMock(),
            session=MagicMock(),
            context=MagicMock(),
            state={},
        )
        store.add_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_save_enabled_saves_messages(self):
        """after_run saves messages when save_enabled=True."""
        store = MagicMock()
        store.add_message = MagicMock()

        provider = ConversationHistoryProvider(
            store,
            conversation_id="conv-2",
            save_enabled=True,
        )

        msg = MagicMock()
        msg.role = "user"
        msg.text = "hello"

        context = MagicMock()
        context.input_messages = [msg]
        response = MagicMock()
        response.messages = []
        response.text = "response text"
        context.response = response
        context.context_messages = {}

        await provider.after_run(
            agent=MagicMock(),
            session=MagicMock(),
            context=context,
            state={},
        )
        assert store.add_message.call_count >= 1
