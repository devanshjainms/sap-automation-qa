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
        workflow._ensure_conversation("thread-1")

        store.create.assert_called_once()
        created = store.create.call_args[0][0]
        assert str(created.id) == "thread-1"

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
        assert msg.content == "hello"
        assert msg.role.value == "user"

    def test_save_assistant_message(self):
        """_save_assistant_message persists an assistant message."""
        store = MagicMock()
        factory = MagicMock()

        workflow = SapWorkflow(
            factory=factory,
            conversation_store=store,
            name="test",
        )
        workflow._save_assistant_message("conv-1", "the answer")

        store.add_message.assert_called_once()
        msg = store.add_message.call_args[0][1]
        assert msg.content == "the answer"
        assert msg.role.value == "assistant"
