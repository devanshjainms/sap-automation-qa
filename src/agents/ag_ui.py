# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""AG-UI integration — exposes the SAP workflow via the official
``add_agent_framework_fastapi_endpoint`` from the Agent Framework.

Uses a ``SapWorkflow`` subclass of ``AgentFrameworkWorkflow`` that
handles conversation persistence at the workflow boundary, so
agent sessions do not need to know about the AG-UI ``thread_id``.

Architecture:
- **TRIAGE/TEST**: HandoffBuilder with Coordinator → Investigator / TestRunner.
  Specialist text is emitted as ThinkingText events; Coordinator's final
  response becomes the user-visible answer.
- **GENERAL/KNOWLEDGE**: Single agent with all tools. All text is user-visible.
  Tool calls stream naturally between reasoning segments.
"""

from __future__ import annotations
import asyncio
import logging
from collections.abc import AsyncGenerator
from typing import Any
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
)
from ag_ui.core.events import BaseEvent
from agent_framework_ag_ui import (
    AgentFrameworkWorkflow,
    add_agent_framework_fastapi_endpoint,
)
from agent_framework_ag_ui._workflow_run import run_workflow_stream

from agent_framework import Message as AFMessage
from agent_framework._types import Content

from src.agents.agent import SapAgentFactory
from src.agents.agent_config import config_for_intent
from src.core.models.conversation import Conversation
from src.core.storage.conversation_store import ConversationStore

logger = logging.getLogger(__name__)


class SapWorkflow(AgentFrameworkWorkflow):
    """Workflow that classifies intent per request and persists messages.

    Overrides ``run()`` to bypass ``workflow_factory`` entirely.
    Instead, each request:

    1. Extracts the user message from the AG-UI input.
    2. Classifies intent via ``classify()`` (regex heuristics).
    3. Builds a fresh ``Workflow`` via ``SapAgentFactory.create_workflow()``
       with the correct ``AgentConfig``, ``user_query``, and ``thread_id``.
    4. Calls ``run_workflow_stream()`` directly to convert workflow
       events into AG-UI events.
    5. Persists user + assistant messages to SQLite.

    :param factory: Agent factory with MCP connections.
    :param conversation_store: SQLite conversation store.
    """

    def __init__(
        self,
        factory: SapAgentFactory,
        conversation_store: ConversationStore | None,
        **kwargs: Any,
    ) -> None:
        # No workflow or workflow_factory — we create workflows in run().
        super().__init__(**kwargs)
        self._factory = factory
        self._store = conversation_store

    _THINKING_AGENTS = frozenset({"Investigator", "TestRunner"})

    async def run(
        self,
        input_data: dict[str, Any],
    ) -> AsyncGenerator[BaseEvent]:
        """Run the workflow, stream events, and persist messages.

        Creates a fresh workflow per request with dynamic intent
        classification.  Specialist text (Investigator/TestRunner)
        is emitted as ``ThinkingTextMessage*`` events; Coordinator
        and single-agent text is user-visible.

        :param input_data: AG-UI input dict with ``thread_id`` and
            ``messages``.
        :yields: AG-UI events from the underlying workflow.
        """
        thread_id = input_data.get("thread_id", "")
        run_id = input_data.get("run_id", str(uuid4()))
        user_text = self._extract_user_text(input_data)

        # Classify intent from the actual user message via LLM.
        intent = await self._factory.classify_intent(user_text)
        config = config_for_intent(intent)

        logger.info(
            "AG-UI run: thread_id=%r, run_id=%s, intent=%s, "
            "user_text=%s, msg_count=%d",
            thread_id,
            run_id[:12] if run_id else "(none)",
            intent.value,
            bool(user_text),
            len(input_data.get("messages", [])),
        )

        if self._store and thread_id:
            self._ensure_conversation(thread_id)

        # Build a fresh workflow with the classified config.
        workflow = self._factory.create_workflow(
            config=config,
            user_query=user_text,
            thread_id=thread_id,
        )

        ordered_parts: list[dict[str, Any]] = []
        pending_text: list[str] = []
        current_agent: str = ""
        thinking_msg_ids: set[str] = set()
        thinking_open: bool = False
        open_tool_call_ids: list[str] = []
        tool_call_names: dict[str, str] = {}
        tool_call_args: dict[str, list[str]] = {}
        completed_tools: list[dict[str, str]] = []

        async for event in run_workflow_stream(input_data, workflow):
            # ── Skip handoff tool calls (internal routing) ──
            if isinstance(event, ToolCallStartEvent):
                name = event.tool_call_name or ""
                if name.startswith("handoff_to_"):
                    tool_call_names[event.tool_call_id] = name
                    continue
            if isinstance(
                event, (ToolCallArgsEvent, ToolCallEndEvent, ToolCallResultEvent),
            ):
                tc_id = event.tool_call_id
                if tool_call_names.get(tc_id, "").startswith("handoff_to_"):
                    continue
            # ── Flush orphan tool calls when a non-tool event arrives ──
            if open_tool_call_ids and not isinstance(
                event, (ToolCallArgsEvent, ToolCallEndEvent),
            ):
                if pending_text:
                    ordered_parts.append(
                        {"type": "text", "text": "".join(pending_text)},
                    )
                    pending_text.clear()
                for tc_id in open_tool_call_ids:
                    ordered_parts.append({"type": "tool_ref", "id": tc_id})
                    completed_tools.append({
                        "id": tc_id,
                        "name": tool_call_names.get(tc_id, "tool"),
                        "arguments": "".join(tool_call_args.pop(tc_id, [])),
                        "result": f"{tool_call_names.get(tc_id, 'tool')} completed",
                    })
                    yield ToolCallEndEvent(tool_call_id=tc_id)
                    yield ToolCallResultEvent(
                        message_id=str(uuid4()),
                        tool_call_id=tc_id,
                        content=f"{tool_call_names.get(tc_id, 'tool')} completed",
                        role="tool",
                    )
                open_tool_call_ids.clear()

            # ── Tool call lifecycle ──
            if isinstance(event, ToolCallStartEvent):
                name = event.tool_call_name or "tool"
                open_tool_call_ids.append(event.tool_call_id)
                tool_call_names[event.tool_call_id] = name
                tool_call_args[event.tool_call_id] = []
                yield event
                continue

            if isinstance(event, ToolCallEndEvent):
                tc_id = event.tool_call_id
                if tc_id in open_tool_call_ids:
                    open_tool_call_ids.remove(tc_id)
                if pending_text:
                    ordered_parts.append(
                        {"type": "text", "text": "".join(pending_text)},
                    )
                    pending_text.clear()
                ordered_parts.append({"type": "tool_ref", "id": tc_id})
                result_text = f"{tool_call_names.get(tc_id, 'tool')} completed"
                completed_tools.append({
                    "id": tc_id,
                    "name": tool_call_names.get(tc_id, "tool"),
                    "arguments": "".join(tool_call_args.pop(tc_id, [])),
                    "result": result_text,
                })
                yield event
                yield ToolCallResultEvent(
                    message_id=str(uuid4()),
                    tool_call_id=tc_id,
                    content=result_text,
                    role="tool",
                )
                continue

            if isinstance(event, ToolCallArgsEvent):
                if event.tool_call_id in tool_call_args:
                    tool_call_args[event.tool_call_id].append(event.delta)
                yield event
                continue

            if isinstance(event, ToolCallResultEvent):
                for tc in completed_tools:
                    if tc["id"] == event.tool_call_id:
                        tc["result"] = event.content or tc["result"]
                        break
                yield event
                continue

            # ── Step tracking (maps to agent names) ──
            if isinstance(event, StepStartedEvent):
                current_agent = event.step_name or ""
                logger.info("Agent started: %r", current_agent)
                yield event
                continue
            if isinstance(event, StepFinishedEvent):
                logger.info("Agent finished: %r", current_agent)
                current_agent = ""
                yield event
                continue

            # ── Text message end (close thinking if needed) ──
            if isinstance(event, TextMessageEndEvent):
                if event.message_id in thinking_msg_ids:
                    thinking_msg_ids.discard(event.message_id)
                    yield ThinkingTextMessageEndEvent()
                    if not thinking_msg_ids:
                        yield ThinkingEndEvent()
                        thinking_open = False
                    continue

            # ── Specialist text → thinking bubbles ──
            if current_agent in self._THINKING_AGENTS:
                if isinstance(event, TextMessageStartEvent):
                    thinking_msg_ids.add(event.message_id)
                    if not thinking_open:
                        yield ThinkingStartEvent()
                        thinking_open = True
                    yield ThinkingTextMessageStartEvent()
                    continue
                if isinstance(event, TextMessageContentEvent):
                    if event.message_id in thinking_msg_ids:
                        pending_text.append(event.delta)
                        yield ThinkingTextMessageContentEvent(
                            delta=event.delta,
                        )
                        continue

            # ── Default: pass through (user-visible text) ──
            if isinstance(event, TextMessageContentEvent):
                pending_text.append(event.delta)

            yield event

        # ── Flush remaining state ──
        if thinking_open:
            yield ThinkingEndEvent()
            thinking_open = False

        if pending_text:
            ordered_parts.append(
                {"type": "text", "text": "".join(pending_text)},
            )
            pending_text.clear()
        for tc_id in open_tool_call_ids:
            ordered_parts.append({"type": "tool_ref", "id": tc_id})
            result_text = f"{tool_call_names.get(tc_id, 'tool')} completed"
            completed_tools.append({
                "id": tc_id,
                "name": tool_call_names.get(tc_id, "tool"),
                "arguments": "".join(tool_call_args.pop(tc_id, [])),
                "result": result_text,
            })
            yield ToolCallEndEvent(tool_call_id=tc_id)
            yield ToolCallResultEvent(
                message_id=str(uuid4()),
                tool_call_id=tc_id,
                content=result_text,
                role="tool",
            )

        # ── Persist ──
        if self._store and thread_id:
            if user_text:
                self._save_user_message(thread_id, user_text)
            if ordered_parts:
                self._save_assistant_message(
                    thread_id, ordered_parts, completed_tools,
                )

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

    def _save_user_message(self, conv_id: str, text: str) -> None:
        """Persist the user message as an AF Message."""
        assert self._store is not None
        try:
            self._store.add_message(
                conv_id,
                AFMessage("user", [text]),
            )
        except Exception:
            logger.debug("Could not save user message", exc_info=True)

    def _save_assistant_message(
        self,
        conv_id: str,
        ordered_parts: list[dict[str, Any]],
        completed_tools: list[dict[str, str]],
    ) -> None:
        """Persist the assistant response as AF Message(s).

        Builds contents in the order events occurred — text segments
        interleaved with function_call entries — so the UI can replay
        the conversation with planning text before tool calls.

        :param conv_id: Conversation ID.
        :param ordered_parts: Ordered ``{"type": "text", "text": ...}``
            and ``{"type": "tool_ref", "id": ...}`` dicts.
        :param completed_tools: Tool call dicts with id/name/arguments/result.
        """
        assert self._store is not None
        try:
            tools_by_id = {tc["id"]: tc for tc in completed_tools}
            contents: list = []
            tool_results: list[dict[str, str]] = []
            for part in ordered_parts:
                if part["type"] == "text":
                    contents.append(Content.from_text(part["text"]))
                elif part["type"] == "tool_ref":
                    tc = tools_by_id.get(part["id"])
                    if tc:
                        contents.append(
                            Content.from_function_call(
                                call_id=tc["id"],
                                name=tc["name"],
                                arguments=tc.get("arguments", ""),
                            )
                        )
                        tool_results.append(tc)
            if not contents:
                return
            self._store.add_message(conv_id, AFMessage("assistant", contents))

            for tc in tool_results:
                self._store.add_message(
                    conv_id,
                    AFMessage(
                        "tool",
                        [Content.from_function_result(
                            call_id=tc["id"],
                            result=tc.get("result", ""),
                        )],
                    ),
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
