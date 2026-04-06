# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""AG-UI integration — exposes the SAP workflow via the official
``add_agent_framework_fastapi_endpoint`` from the Agent Framework.

Uses a ``SapWorkflow`` subclass of ``AgentFrameworkWorkflow`` that
handles conversation persistence at the workflow boundary, so
individual agent sessions inside ``SequentialBuilder`` do not need
to know about the AG-UI ``thread_id``.
"""

from __future__ import annotations
import asyncio
import logging
from collections.abc import AsyncGenerator
from typing import Any, cast
from uuid import UUID, uuid4
from fastapi import FastAPI
from ag_ui.core.events import (
    StepStartedEvent,
    StepFinishedEvent,
    TextMessageStartEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    ThinkingStartEvent,
    ThinkingEndEvent,
    ThinkingTextMessageStartEvent,
    ThinkingTextMessageContentEvent,
    ThinkingTextMessageEndEvent,
    ToolCallStartEvent,
    ToolCallArgsEvent,
    ToolCallEndEvent,
    ToolCallResultEvent,
    RunFinishedEvent,
    MessagesSnapshotEvent,
)
from ag_ui.core.events import BaseEvent
from ag_ui.core.types import (
    Message as AGMessage,
    UserMessage as AGUserMessage,
    AssistantMessage as AGAssistantMessage,
)
from agent_framework_ag_ui import (
    AgentFrameworkWorkflow,
    add_agent_framework_fastapi_endpoint,
)

from src.agents.agent import SapAgentFactory
from src.agents.agent_config import TRIAGE_CONFIG
from src.core.models.conversation import (
    Conversation,
    Message,
    MessageRole,
)
from src.core.storage.conversation_store import ConversationStore

logger = logging.getLogger(__name__)


class SapWorkflow(AgentFrameworkWorkflow):
    """Workflow that persists messages at the workflow boundary.

    Wraps ``AgentFrameworkWorkflow`` and intercepts ``run()`` to:
    1. Auto-create the conversation if it does not exist.
    2. Save the user message and final assistant response.
    3. Fire-and-forget title generation on first turn.

    :param factory: Agent factory with MCP connections.
    :param conversation_store: SQLite conversation store.
    """

    def __init__(
        self,
        factory: SapAgentFactory,
        conversation_store: ConversationStore | None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            workflow_factory=lambda thread_id: factory.create_workflow(
                config=TRIAGE_CONFIG,
                thread_id=thread_id,
            ),
            **kwargs,
        )
        self._factory = factory
        self._store = conversation_store

    _THINKING_STEPS = frozenset({"Planner"})

    async def run(
        self,
        input_data: dict[str, Any],
    ) -> AsyncGenerator[BaseEvent]:
        """Run the workflow, convert intermediate text to thinking, persist.

        Planner/Executor text is re-emitted as ``ThinkingTextMessage*``
        events so the UI can show it as small ephemeral text (like
        VS Code Copilot's reasoning display).  Tool call events pass
        through unchanged for progress visibility.  Only the Analyst's
        text becomes the permanent assistant response.

        :param input_data: AG-UI input dict with ``thread_id`` and
            ``messages``.
        :yields: AG-UI events from the underlying workflow.
        """
        thread_id = input_data.get("thread_id", "")
        run_id = input_data.get("run_id", str(uuid4()))
        user_text = self._extract_user_text(input_data)

        logger.info(
            "AG-UI run: thread_id=%r, run_id=%s, user_text=%s, "
            "msg_count=%d, keys=%s",
            thread_id,
            run_id[:12] if run_id else "(none)",
            bool(user_text),
            len(input_data.get("messages", [])),
            list(input_data.keys()),
        )

        if self._store and thread_id:
            self._ensure_conversation(thread_id)

        snapshot = self._build_messages_snapshot(thread_id)
        if snapshot:
            logger.info(
                "Replaying snapshot with %d messages for thread %s",
                len(snapshot.messages),
                thread_id[:12],
            )
            yield snapshot
            if not user_text:
                yield RunFinishedEvent(
                    thread_id=thread_id,
                    run_id=run_id,
                )
                return

        assistant_chunks: list[str] = []
        current_step: str = ""
        thinking_msg_ids: set[str] = set()
        thinking_step_open: bool = False
        open_tool_call_ids: list[str] = []
        tool_call_names: dict[str, str] = {}

        async for event in super().run(input_data):
            if open_tool_call_ids and not isinstance(event, (ToolCallArgsEvent, ToolCallEndEvent)):
                for tc_id in open_tool_call_ids:
                    yield ToolCallEndEvent(tool_call_id=tc_id)
                    yield ToolCallResultEvent(
                        message_id=str(uuid4()),
                        tool_call_id=tc_id,
                        content=f"{tool_call_names.get(tc_id, 'tool')} completed",
                        role="tool",
                    )
                open_tool_call_ids.clear()

            if isinstance(event, ToolCallStartEvent):
                open_tool_call_ids.append(event.tool_call_id)
                tool_call_names[event.tool_call_id] = event.tool_call_name or "tool"
                yield event
                continue

            if isinstance(event, ToolCallEndEvent):
                if event.tool_call_id in open_tool_call_ids:
                    open_tool_call_ids.remove(event.tool_call_id)
                yield event
                yield ToolCallResultEvent(
                    message_id=str(uuid4()),
                    tool_call_id=event.tool_call_id,
                    content=f"{tool_call_names.get(event.tool_call_id, 'tool')} completed",
                    role="tool",
                )
                continue

            if isinstance(event, StepStartedEvent):
                current_step = event.step_name or ""
                logger.info("Step started: %r", current_step)
                yield event
                continue
            if isinstance(event, StepFinishedEvent):
                logger.info("Step finished: %r", current_step)
                current_step = ""
                yield event
                continue

            if isinstance(event, TextMessageEndEvent):
                if event.message_id in thinking_msg_ids:
                    thinking_msg_ids.discard(event.message_id)
                    yield ThinkingTextMessageEndEvent()
                    if not thinking_msg_ids:
                        yield ThinkingEndEvent()
                        thinking_step_open = False
                    continue

            if current_step in self._THINKING_STEPS:
                if isinstance(event, TextMessageStartEvent):
                    thinking_msg_ids.add(event.message_id)
                    if not thinking_step_open:
                        yield ThinkingStartEvent()
                        thinking_step_open = True
                    yield ThinkingTextMessageStartEvent()
                    continue
                if isinstance(event, TextMessageContentEvent):
                    if event.message_id in thinking_msg_ids:
                        yield ThinkingTextMessageContentEvent(
                            delta=event.delta,
                        )
                        continue

            if isinstance(event, TextMessageContentEvent):
                assistant_chunks.append(event.delta)

            yield event

        for tc_id in open_tool_call_ids:
            yield ToolCallEndEvent(tool_call_id=tc_id)
            yield ToolCallResultEvent(
                message_id=str(uuid4()),
                tool_call_id=tc_id,
                content=f"{tool_call_names.get(tc_id, 'tool')} completed",
                role="tool",
            )

        if self._store and thread_id:
            if user_text:
                self._save_user_message(thread_id, user_text)
            if assistant_chunks:
                assistant_text = "".join(assistant_chunks)
                self._save_assistant_message(thread_id, assistant_text)

            if user_text:
                asyncio.create_task(
                    self._factory._generate_title(user_text),
                ).add_done_callback(
                    lambda fut: self._apply_title(thread_id, fut),
                )

    def _ensure_conversation(self, thread_id: str) -> None:
        """Create conversation row if it doesn't exist."""
        assert self._store is not None
        try:
            existing = self._store.get(thread_id)
            if existing:
                return
            self._store.create(Conversation(id=UUID(thread_id), workspace_id=""))
            logger.info("Created conversation %s", thread_id[:8])
        except Exception:
            logger.debug(
                "Could not ensure conversation %s",
                thread_id[:8],
                exc_info=True,
            )

    def _build_messages_snapshot(
        self,
        thread_id: str,
    ) -> MessagesSnapshotEvent | None:
        """Build a ``MessagesSnapshotEvent`` from stored conversation history.

        Returns ``None`` when there is no store, no thread, or no prior
        messages.
        """
        if not self._store or not thread_id:
            return None
        try:
            stored = self._store.get_history(thread_id)
            if not stored:
                return None
            ag_msgs: list[AGUserMessage | AGAssistantMessage] = []
            for msg in stored:
                if msg.role == MessageRole.USER:
                    ag_msgs.append(AGUserMessage(id=str(uuid4()), content=msg.content))
                elif msg.role == MessageRole.ASSISTANT:
                    ag_msgs.append(AGAssistantMessage(id=str(uuid4()), content=msg.content))
            if not ag_msgs:
                return None
            logger.debug(
                "Replaying %d messages for thread %s",
                len(ag_msgs),
                thread_id[:8],
            )
            return MessagesSnapshotEvent(
                messages=cast(list[AGMessage], ag_msgs),
            )
        except Exception:
            logger.debug(
                "Could not build messages snapshot",
                exc_info=True,
            )
            return None

    def _save_user_message(self, conv_id: str, text: str) -> None:
        """Persist the user message."""
        assert self._store is not None
        try:
            self._store.add_message(
                conv_id,
                Message(role=MessageRole.USER, content=text),
            )
        except Exception:
            logger.debug("Could not save user message", exc_info=True)

    def _save_assistant_message(self, conv_id: str, text: str) -> None:
        """Persist the assistant response."""
        assert self._store is not None
        try:
            self._store.add_message(
                conv_id,
                Message(role=MessageRole.ASSISTANT, content=text),
            )
        except Exception:
            logger.debug("Could not save assistant message", exc_info=True)

    def _apply_title(self, conv_id: str, fut: asyncio.Future) -> None:
        """Callback for the title-generation task."""
        try:
            title = str(fut.result()).strip().strip('"').strip("'")[:80]
            if title and self._store:
                self._store.update_title(conv_id, title)
                logger.info("Set title for %s: %s", conv_id[:8], title)
        except Exception:
            logger.debug("Title generation failed", exc_info=True)

    @staticmethod
    def _extract_user_text(input_data: dict[str, Any]) -> str:
        """Extract the last user message text from AG-UI input."""
        for msg in reversed(input_data.get("messages", [])):
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, str):
                    return content
                if isinstance(content, list):
                    parts = [
                        p.get("text", "")
                        for p in content
                        if isinstance(p, dict) and p.get("type") == "text"
                    ]
                    return " ".join(parts)
        return ""


def register_ag_ui(
    app: FastAPI,
    factory: SapAgentFactory,
    path: str = "/ag-ui",
    allow_origins: list[str] | None = None,
    conversation_store: ConversationStore | None = None,
) -> None:
    """Register the AG-UI workflow endpoint.

    Uses ``SapWorkflow`` so persistence is handled at the workflow
    boundary — each AG-UI ``thread_id`` maps to a conversation.

    :param app: The FastAPI application.
    :param factory: Agent factory with MCP connections.
    :param path: Endpoint path (default ``/ag-ui``).
    :param allow_origins: CORS origins.
    :param conversation_store: SQLite conversation store.
    """
    ag_ui_workflow = SapWorkflow(
        factory=factory,
        conversation_store=conversation_store,
        name="SAP-Agent",
        description=(
            "SAP infrastructure specialist — investigates system "
            "health, runs diagnostics, manages HA tests and schedules."
        ),
    )

    add_agent_framework_fastapi_endpoint(
        app,
        ag_ui_workflow,
        path,
        allow_origins=allow_origins,
    )
    logger.info("AG-UI workflow endpoint registered at %s", path)
