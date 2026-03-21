# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for ChatService — multi-agent GroupChat workflow integration."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent_framework import WorkflowEvent, WorkflowRunResult

from src.core.services.chat import ChatEvent, ChatService
from src.core.models.conversation import (
    Conversation,
    Message,
    MessageRole,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_conversation(workspace_id: str = "WS-TEST") -> Conversation:
    """Create a test conversation."""
    return Conversation(workspace_id=workspace_id)


def _make_store(conversation: Conversation | None = None) -> MagicMock:
    """Create a mock ConversationStore."""
    store = MagicMock()
    store.get.return_value = conversation
    store.get_history.return_value = []
    store.add_message.side_effect = lambda _cid, msg: msg
    return store


def _make_workflow_result(text: str) -> WorkflowRunResult:
    """Build a WorkflowRunResult containing a single output event."""
    events = [WorkflowEvent.output("Triage-Agent", text)]
    return WorkflowRunResult(events=events)


def _make_factory(response_text: str = "Agent reply") -> MagicMock:
    """Create a mock SapAgentFactory with a predictable workflow."""
    result = _make_workflow_result(response_text)

    workflow = MagicMock()
    workflow.run = AsyncMock(return_value=result)

    factory = MagicMock()
    factory.create_workflow.return_value = workflow
    factory.registry = MagicMock()
    return factory


def _make_streaming_factory(chunks: list[str]) -> MagicMock:
    """Create a mock SapAgentFactory with a streaming workflow.

    Each chunk becomes a separate ``output`` WorkflowEvent in the
    streaming iterator.  The final response aggregates all chunks.
    """
    output_events = [
        WorkflowEvent.output("Triage-Agent", chunk) for chunk in chunks
    ]
    final_result = _make_workflow_result("".join(chunks))

    class FakeStream:
        """Async-iterable mock for Workflow ResponseStream."""

        def __init__(self) -> None:
            self._events = list(output_events)

        async def __aiter__(self):
            for evt in self._events:
                yield evt

        async def get_final_response(self):
            return final_result

    workflow = MagicMock()
    workflow.run.return_value = FakeStream()

    factory = MagicMock()
    factory.create_workflow.return_value = workflow
    factory.registry = MagicMock()
    return factory


# ---------------------------------------------------------------------------
# ChatEvent
# ---------------------------------------------------------------------------


class TestChatEvent:
    """Tests for the ChatEvent dataclass."""

    def test_to_sse_token_event(self):
        event = ChatEvent(event_type="token", data={"text": "Hello"})
        sse = event.to_sse()
        assert sse == 'event: token\ndata: {"text": "Hello"}\n\n'

    def test_to_sse_done_event(self):
        event = ChatEvent(event_type="done", data={"text": "Full reply"})
        sse = event.to_sse()
        assert "event: done" in sse
        assert '"Full reply"' in sse

    def test_to_sse_empty_data(self):
        event = ChatEvent(event_type="done")
        assert "data: {}" in event.to_sse()

    def test_frozen(self):
        event = ChatEvent(event_type="token", data={"text": "x"})
        with pytest.raises(AttributeError):
            event.event_type = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# ChatService.send_message
# ---------------------------------------------------------------------------


class TestSendMessage:
    """Tests for ChatService.send_message (non-streaming)."""

    @pytest.mark.asyncio
    async def test_returns_assistant_message(self):
        conv = _make_conversation()
        store = _make_store(conv)
        factory = _make_factory("The HANA cluster is healthy.")

        service = ChatService(factory, store)
        result = await service.send_message(str(conv.id), "Check HANA status")

        assert result.role == MessageRole.ASSISTANT
        assert result.content == "The HANA cluster is healthy."

    @pytest.mark.asyncio
    async def test_persists_user_and_assistant_messages(self):
        conv = _make_conversation()
        store = _make_store(conv)
        factory = _make_factory("reply")

        service = ChatService(factory, store)
        await service.send_message(str(conv.id), "hello")

        assert store.add_message.call_count == 2
        user_call = store.add_message.call_args_list[0]
        assert user_call[0][1].role == MessageRole.USER
        assert user_call[0][1].content == "hello"

        assistant_call = store.add_message.call_args_list[1]
        assert assistant_call[0][1].role == MessageRole.ASSISTANT

    @pytest.mark.asyncio
    async def test_passes_workspace_context_to_workflow(self):
        conv = _make_conversation(workspace_id="MY-SAP-WS")
        store = _make_store(conv)
        factory = _make_factory("ok")

        service = ChatService(factory, store)
        await service.send_message(str(conv.id), "hi")

        factory.create_workflow.assert_called_once_with(
            workspace_context="Workspace: MY-SAP-WS",
        )

    @pytest.mark.asyncio
    async def test_passes_task_to_workflow_run(self):
        conv = _make_conversation(workspace_id="WS1")
        store = _make_store(conv)
        factory = _make_factory("answer")

        service = ChatService(factory, store)
        await service.send_message(str(conv.id), "Check cluster")

        workflow = factory.create_workflow.return_value
        task_arg = workflow.run.call_args[0][0]
        assert "Current request: Check cluster" in task_arg
        assert "[Workspace: WS1]" in task_arg

    @pytest.mark.asyncio
    async def test_workflow_failure_returns_error_message(self):
        conv = _make_conversation()
        store = _make_store(conv)

        workflow = MagicMock()
        workflow.run = AsyncMock(side_effect=RuntimeError("LLM unavailable"))
        factory = MagicMock()
        factory.create_workflow.return_value = workflow
        factory.registry = MagicMock()

        service = ChatService(factory, store)
        result = await service.send_message(str(conv.id), "hello")

        assert result.role == MessageRole.ASSISTANT
        assert "error" in result.content.lower()

    @pytest.mark.asyncio
    async def test_conversation_not_found_raises(self):
        store = _make_store(None)
        factory = _make_factory()

        service = ChatService(factory, store)
        with pytest.raises(ValueError, match="not found"):
            await service.send_message("nonexistent", "hello")

    @pytest.mark.asyncio
    async def test_archived_conversation_raises(self):
        conv = _make_conversation()
        conv.archive()
        store = _make_store(conv)
        factory = _make_factory()

        service = ChatService(factory, store)
        with pytest.raises(ValueError, match="archived"):
            await service.send_message(str(conv.id), "hello")

    @pytest.mark.asyncio
    async def test_empty_workflow_output_persisted(self):
        conv = _make_conversation()
        store = _make_store(conv)
        factory = _make_factory("")

        service = ChatService(factory, store)
        result = await service.send_message(str(conv.id), "hello")

        assert result.content == ""


# ---------------------------------------------------------------------------
# ChatService.stream_response
# ---------------------------------------------------------------------------


class TestStreamResponse:
    """Tests for ChatService.stream_response (SSE streaming)."""

    @pytest.mark.asyncio
    async def test_yields_token_and_done_events(self):
        conv = _make_conversation()
        store = _make_store(conv)
        factory = _make_streaming_factory(["Hello", " world", "!"])

        service = ChatService(factory, store)
        events: list[ChatEvent] = []
        async for event in service.stream_response(str(conv.id), "hi"):
            events.append(event)

        token_events = [e for e in events if e.event_type == "token"]
        done_events = [e for e in events if e.event_type == "done"]

        assert len(token_events) == 3
        assert token_events[0].data["text"] == "Hello"
        assert token_events[1].data["text"] == " world"
        assert token_events[2].data["text"] == "!"

        assert len(done_events) == 1
        assert done_events[0].data["text"] == "Hello world!"

    @pytest.mark.asyncio
    async def test_persists_full_text_after_streaming(self):
        conv = _make_conversation()
        store = _make_store(conv)
        factory = _make_streaming_factory(["a", "b"])

        service = ChatService(factory, store)
        async for _ in service.stream_response(str(conv.id), "hello"):
            pass

        assert store.add_message.call_count == 2
        assistant_call = store.add_message.call_args_list[1]
        assert assistant_call[0][1].content == "ab"

    @pytest.mark.asyncio
    async def test_workflow_error_yields_error_event(self):
        conv = _make_conversation()
        store = _make_store(conv)

        class FailingStream:
            """Async iterator that raises on first iteration."""

            async def __aiter__(self):
                raise RuntimeError("boom")
                yield  # noqa: unreachable

        workflow = MagicMock()
        workflow.run.return_value = FailingStream()

        factory = MagicMock()
        factory.create_workflow.return_value = workflow
        factory.registry = MagicMock()

        service = ChatService(factory, store)
        events: list[ChatEvent] = []
        async for event in service.stream_response(str(conv.id), "hello"):
            events.append(event)

        error_events = [e for e in events if e.event_type == "error"]
        assert len(error_events) == 1
        assert "boom" in error_events[0].data["error"]

    @pytest.mark.asyncio
    async def test_conversation_not_found_raises(self):
        store = _make_store(None)
        factory = _make_factory()

        service = ChatService(factory, store)
        with pytest.raises(ValueError, match="not found"):
            async for _ in service.stream_response("missing", "hi"):
                pass

    @pytest.mark.asyncio
    async def test_archived_conversation_raises(self):
        conv = _make_conversation()
        conv.archive()
        store = _make_store(conv)
        factory = _make_factory()

        service = ChatService(factory, store)
        with pytest.raises(ValueError, match="archived"):
            async for _ in service.stream_response(str(conv.id), "hi"):
                pass


# ---------------------------------------------------------------------------
# ChatService._build_task
# ---------------------------------------------------------------------------


class TestBuildTask:
    """Tests for task message construction."""

    def test_current_query_only(self):
        task = ChatService._build_task([], "Check HANA", None)
        assert task == "Current request: Check HANA"

    def test_includes_workspace(self):
        task = ChatService._build_task([], "Check HANA", "WS1")
        assert "[Workspace: WS1]" in task
        assert "Current request: Check HANA" in task

    def test_includes_prior_conversation(self):
        history = [
            Message(role=MessageRole.USER, content="What is HANA?"),
            Message(role=MessageRole.ASSISTANT, content="A database."),
            Message(role=MessageRole.USER, content="Is it healthy?"),
        ]
        task = ChatService._build_task(history, "Is it healthy?", None)
        assert "Previous conversation:" in task
        assert "User: What is HANA?" in task
        assert "Assistant: A database." in task
        assert "Current request: Is it healthy?" in task

    def test_excludes_current_query_from_prior(self):
        history = [
            Message(role=MessageRole.USER, content="hello"),
        ]
        task = ChatService._build_task(history, "hello", None)
        assert "Previous conversation:" not in task

    def test_limits_prior_to_ten(self):
        history = [
            Message(role=MessageRole.USER, content=f"msg-{i}")
            for i in range(15)
        ]
        task = ChatService._build_task(history, "msg-99", None)
        # Only last 10 prior messages shown
        assert "msg-5" in task
        assert "msg-4" not in task

    def test_skips_tool_messages(self):
        history = [
            Message(role=MessageRole.USER, content="check"),
            Message(role=MessageRole.TOOL_CALL, content="{}"),
            Message(role=MessageRole.TOOL_RESULT, content="ok"),
            Message(role=MessageRole.ASSISTANT, content="done"),
        ]
        task = ChatService._build_task(history, "new query", None)
        assert "Previous conversation:" in task
        assert "User: check" in task
        assert "Assistant: done" in task
        assert "TOOL" not in task


# ---------------------------------------------------------------------------
# ChatService properties
# ---------------------------------------------------------------------------


class TestChatServiceProperties:
    """Tests for ChatService public interface."""

    def test_factory_property(self):
        factory = MagicMock()
        factory.registry = MagicMock()
        store = MagicMock()
        service = ChatService(factory, store)
        assert service.factory is factory
