# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for ``SapWorkflow`` and ``register_ag_ui``."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.ag_ui import SapWorkflow


class TestSapWorkflowExtractUserText:
    """Validate _extract_user_text static method."""

    def test_extracts_last_user_string(self):
        input_data = {
            "messages": [
                {"role": "user", "content": "first"},
                {"role": "assistant", "content": "ok"},
                {"role": "user", "content": "second"},
            ]
        }
        assert SapWorkflow._extract_user_text(input_data) == "second"

    def test_extracts_from_content_parts(self):
        input_data = {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "hello"},
                        {"type": "text", "text": "world"},
                    ],
                }
            ]
        }
        assert SapWorkflow._extract_user_text(input_data) == "hello world"

    def test_empty_messages(self):
        assert SapWorkflow._extract_user_text({"messages": []}) == ""

    def test_no_user_messages(self):
        input_data = {
            "messages": [{"role": "assistant", "content": "hi"}]
        }
        assert SapWorkflow._extract_user_text(input_data) == ""


class TestSapWorkflowPersistence:
    """Validate SapWorkflow persistence at workflow boundary."""

    def test_ensure_conversation_creates_new(self):
        """_ensure_conversation creates conv when none exists."""
        store = MagicMock()
        store.get.return_value = None
        factory = MagicMock()

        workflow = SapWorkflow(
            factory=factory,
            conversation_store=store,
            name="test",
        )
        thread_id = "a1b2c3d4-0000-0000-0000-000000000001"
        workflow._ensure_conversation(thread_id)

        store.create.assert_called_once()
        created = store.create.call_args[0][0]
        assert str(created.id) == thread_id

    def test_ensure_conversation_skips_existing(self):
        """_ensure_conversation does not create when conv exists."""
        store = MagicMock()
        store.get.return_value = MagicMock()  # exists
        factory = MagicMock()

        workflow = SapWorkflow(
            factory=factory,
            conversation_store=store,
            name="test",
        )
        workflow._ensure_conversation("thread-2")

        store.create.assert_not_called()

    def test_save_user_message(self):
        """_save_user_message persists a user message."""
        store = MagicMock()
        factory = MagicMock()

        workflow = SapWorkflow(
            factory=factory,
            conversation_store=store,
            name="test",
        )
        workflow._save_user_message("conv-1", "hello")

        store.add_message.assert_called_once()
        msg = store.add_message.call_args[0][1]
        assert msg.role == "user"

    def test_save_assistant_message(self):
        """_save_assistant_message persists an assistant message with ordered parts."""
        store = MagicMock()
        factory = MagicMock()

        workflow = SapWorkflow(
            factory=factory,
            conversation_store=store,
            name="test",
        )
        ordered_parts = [{"type": "text", "text": "the answer"}]
        workflow._save_assistant_message("conv-1", ordered_parts, [])

        store.add_message.assert_called_once()
        msg = store.add_message.call_args[0][1]
        assert msg.role == "assistant"
        # Text should be in the contents
        contents = msg.to_dict().get("contents", [])
        text_parts = [c for c in contents if c.get("type") == "text"]
        assert len(text_parts) == 1
        assert text_parts[0]["text"] == "the answer"
