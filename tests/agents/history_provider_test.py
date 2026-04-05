# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for ConversationHistoryProvider silent-tool-call sanitization and title generation."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.providers.history_provider import ConversationHistoryProvider


class TestSanitizeSilentToolCall:
    """Validate _sanitize_silent_tool_call injects text into silent assistant msgs."""

    def test_assistant_with_only_function_call_gets_text(self):
        msg = {
            "type": "message",
            "role": "assistant",
            "contents": [
                {
                    "type": "function_call",
                    "call_id": "call_1",
                    "name": "list_workspaces",
                    "arguments": "{}",
                }
            ],
        }
        result = ConversationHistoryProvider._sanitize_silent_tool_call(msg)

        # Should have text prepended.
        assert len(result["contents"]) == 2
        assert result["contents"][0]["type"] == "text"
        assert "list_workspaces" in result["contents"][0]["text"]
        # Original function_call preserved.
        assert result["contents"][1]["type"] == "function_call"

    def test_assistant_with_text_and_call_unchanged(self):
        msg = {
            "type": "message",
            "role": "assistant",
            "contents": [
                {"type": "text", "text": "I'll check the workspaces."},
                {
                    "type": "function_call",
                    "call_id": "call_1",
                    "name": "list_workspaces",
                    "arguments": "{}",
                },
            ],
        }
        result = ConversationHistoryProvider._sanitize_silent_tool_call(msg)

        # Should be unchanged — already has text.
        assert len(result["contents"]) == 2
        assert result["contents"][0]["type"] == "text"
        assert result["contents"][0]["text"] == "I'll check the workspaces."

    def test_tool_role_message_unchanged(self):
        msg = {
            "type": "message",
            "role": "tool",
            "contents": [
                {
                    "type": "function_result",
                    "call_id": "call_1",
                    "result": "data",
                }
            ],
        }
        result = ConversationHistoryProvider._sanitize_silent_tool_call(msg)
        assert result is msg  # Exact same reference, not modified.

    def test_user_message_unchanged(self):
        msg = {
            "type": "message",
            "role": "user",
            "contents": [{"type": "text", "text": "hello"}],
        }
        result = ConversationHistoryProvider._sanitize_silent_tool_call(msg)
        assert result is msg

    def test_assistant_text_only_unchanged(self):
        msg = {
            "type": "message",
            "role": "assistant",
            "contents": [{"type": "text", "text": "Here is the answer."}],
        }
        result = ConversationHistoryProvider._sanitize_silent_tool_call(msg)
        assert len(result["contents"]) == 1
        assert result["contents"][0]["type"] == "text"

    def test_multiple_function_calls_listed(self):
        msg = {
            "type": "message",
            "role": "assistant",
            "contents": [
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
        }
        result = ConversationHistoryProvider._sanitize_silent_tool_call(msg)

        assert len(result["contents"]) == 3
        text = result["contents"][0]["text"]
        assert "list_workspaces" in text
        assert "run_evidence_collector" in text

    def test_empty_contents_unchanged(self):
        msg = {"type": "message", "role": "assistant", "contents": []}
        result = ConversationHistoryProvider._sanitize_silent_tool_call(msg)
        assert result["contents"] == []

    def test_original_dict_not_mutated(self):
        msg = {
            "type": "message",
            "role": "assistant",
            "contents": [
                {
                    "type": "function_call",
                    "call_id": "call_1",
                    "name": "my_tool",
                    "arguments": "{}",
                }
            ],
        }
        original_len = len(msg["contents"])
        _ = ConversationHistoryProvider._sanitize_silent_tool_call(msg)
        # Original dict should not be mutated.
        assert len(msg["contents"]) == original_len


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
