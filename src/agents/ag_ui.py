# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
AG-UI integration — exposes the SAP workflow via the official
``add_agent_framework_fastapi_endpoint`` from the Agent Framework.
"""

from __future__ import annotations
import asyncio
import logging
import time
from collections.abc import AsyncGenerator
from typing import Any
from uuid import UUID, uuid4
from fastapi import FastAPI
from ag_ui.core.events import (
    RunStartedEvent,
    RunFinishedEvent,
    CustomEvent,
    StateSnapshotEvent,
    StepStartedEvent,
    StepFinishedEvent,
    TextMessageStartEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    ToolCallStartEvent,
    ToolCallArgsEvent,
    ToolCallEndEvent,
    ToolCallResultEvent,
    ReasoningStartEvent,
    ReasoningMessageStartEvent,
    ReasoningMessageContentEvent,
    ReasoningMessageEndEvent,
    ReasoningEndEvent,
)
from ag_ui.core.events import BaseEvent
from agent_framework_ag_ui import (
    AgentFrameworkAgent,
    AgentFrameworkWorkflow,
    add_agent_framework_fastapi_endpoint,
)

from agent_framework import Message as AFMessage
from agent_framework._types import Content
from src.agents.agent import SapAgentFactory
from src.agents.agent_config import InvestigationIntent, config_for_intent
from src.core.models.conversation import Conversation
from src.core.storage.conversation_store import ConversationStore

logger = logging.getLogger(__name__)


class SapWorkflow(AgentFrameworkWorkflow):
    """
    AG-UI endpoint that classifies intent per request and routes
    to the optimal execution strategy.

    :param factory: Agent factory with MCP connections.
    :param conversation_store: SQLite conversation store.
    """

    _THINKING_AGENTS = frozenset({"Investigator", "TestRunner"})

    _STATE_SCHEMA = {
        "tool_activity": {
            "type": "object",
            "description": "Microsoft docs search arguments",
        },
        "evidence_activity": {
            "type": "object",
            "description": "Evidence collection arguments",
        },
        "knowledge_activity": {
            "type": "object",
            "description": "Knowledge query arguments",
        },
    }

    _PREDICT_STATE_CONFIG = {
        "tool_activity": {
            "tool": "microsoft_docs_search",
            "tool_argument": "*",
        },
        "evidence_activity": {
            "tool": "collect_evidence",
            "tool_argument": "*",
        },
        "knowledge_activity": {
            "tool": "query_knowledge",
            "tool_argument": "*",
        },
    }

    def __init__(
        self,
        factory: SapAgentFactory,
        conversation_store: ConversationStore | None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._factory = factory
        self._store = conversation_store

    @staticmethod
    def _build_state(
        *,
        status: str,
        intent: str | None = None,
        active_agent: str | None = None,
        tools: list[dict[str, str]] | None = None,
    ) -> StateSnapshotEvent:
        """Build a ``StateSnapshotEvent``."""
        return StateSnapshotEvent(
            snapshot={
                "status": status,
                "intent": intent,
                "active_agent": active_agent,
                "tools": tools or [],
            },
        )

    # ── Main entry point ──────────────────────────────────

    async def run(
        self,
        input_data: dict[str, Any],
    ) -> AsyncGenerator[BaseEvent]:
        """Classify intent, then delegate to the optimal execution
        strategy.

        :param input_data: AG-UI input dict.
        :yields: AG-UI events.
        """
        thread_id = input_data.get("thread_id", "")
        run_id = input_data.get("run_id", str(uuid4()))
        user_text = self._extract_user_text(input_data)
        stream_start = time.perf_counter()

        yield RunStartedEvent(run_id=run_id, thread_id=thread_id)
        yield StepStartedEvent(step_name="classifying")

        intent = await self._factory.classify_intent(user_text)
        config = config_for_intent(intent)

        yield CustomEvent(
            name="intent_classified",
            value={"intent": intent.value},
        )
        yield StepFinishedEvent(step_name="classifying")
        yield self._build_state(status="thinking", intent=intent.value)

        logger.info(
            "AG-UI run: thread_id=%r, run_id=%s, intent=%s, " "user_text=%s, msg_count=%d",
            thread_id,
            run_id[:12] if run_id else "(none)",
            intent.value,
            bool(user_text),
            len(input_data.get("messages", [])),
        )

        if self._store and thread_id:
            self._ensure_conversation(thread_id)

        completed_tools: list[dict[str, str]] = []
        ordered_parts: list[dict[str, Any]] = []

        input_data = self._sanitize_messages(input_data)

        if intent in (InvestigationIntent.TRIAGE, InvestigationIntent.TEST):
            async for event in self._run_handoff_workflow(
                input_data=input_data,
                config=config,
                intent=intent,
                user_text=user_text,
                thread_id=thread_id,
                completed_tools=completed_tools,
                ordered_parts=ordered_parts,
            ):
                yield event
        else:
            async for event in self._run_single_agent(
                input_data=input_data,
                config=config,
                intent=intent,
                user_text=user_text,
                thread_id=thread_id,
                completed_tools=completed_tools,
                ordered_parts=ordered_parts,
            ):
                yield event

        yield self._build_state(
            status="complete",
            intent=intent.value,
            tools=[{"name": tc["name"], "status": "completed"} for tc in completed_tools],
        )

        stream_duration_ms = int(
            (time.perf_counter() - stream_start) * 1000,
        )
        tool_names = [tc["name"] for tc in completed_tools]
        logger.info(
            "AG-UI stream completed: thread_id=%s, intent=%s, "
            "duration_ms=%d, tools=%s, tool_count=%d",
            thread_id[:8] if thread_id else "(none)",
            intent.value,
            stream_duration_ms,
            tool_names or "none",
            len(completed_tools),
        )

        if self._store and thread_id:
            if user_text:
                self._save_user_message(thread_id, user_text)
            if ordered_parts:
                self._save_assistant_message(
                    thread_id,
                    ordered_parts,
                    completed_tools,
                )
            if user_text:
                asyncio.create_task(
                    self._factory._generate_title(user_text),
                ).add_done_callback(
                    lambda fut: self._apply_title(thread_id, fut),
                )

        yield RunFinishedEvent(
            run_id=run_id,
            thread_id=thread_id,
        )

    async def _run_single_agent(
        self,
        *,
        input_data: dict[str, Any],
        config: Any,
        intent: Any,
        user_text: str,
        thread_id: str,
        completed_tools: list[dict[str, str]],
        ordered_parts: list[dict[str, Any]],
    ) -> AsyncGenerator[BaseEvent]:
        """
        Run a plain Agent via ``AgentFrameworkAgent`` for native real-time streaming.

        :yields: AG-UI events in real time.
        """
        agent = self._factory.create_agent(
            config=config,
            user_query=user_text,
            thread_id=thread_id,
        )
        delegate = AgentFrameworkAgent(
            agent=agent,
            name="SAP-Agent",
            description="SAP infrastructure specialist for Azure.",
            state_schema=self._STATE_SCHEMA,
            predict_state_config=self._PREDICT_STATE_CONFIG,
            require_confirmation=False,
        )

        pending_text: list[str] = []
        tool_call_names: dict[str, str] = {}
        tool_call_args: dict[str, list[str]] = {}
        run_started_skipped = False

        async for event in delegate.run(input_data):
            if isinstance(event, (RunStartedEvent, RunFinishedEvent)):
                if isinstance(event, RunStartedEvent) and not run_started_skipped:
                    run_started_skipped = True
                continue

            if isinstance(event, ReasoningMessageStartEvent):
                yield ReasoningMessageStartEvent.model_construct(
                    type="REASONING_MESSAGE_START",
                    message_id=event.message_id,
                    role="reasoning",
                )
                continue

            if isinstance(event, ToolCallStartEvent):
                name = event.tool_call_name or "tool"
                tool_call_names[event.tool_call_id] = name
                tool_call_args[event.tool_call_id] = []
                yield self._build_state(
                    status="calling_tool",
                    intent=intent.value,
                    active_agent="SAP-Agent",
                    tools=[
                        *[{"name": tc["name"], "status": "completed"} for tc in completed_tools],
                        {"name": name, "status": "in_progress"},
                    ],
                )
                yield event
                continue

            if isinstance(event, ToolCallArgsEvent):
                if event.tool_call_id in tool_call_args:
                    tool_call_args[event.tool_call_id].append(event.delta)
                yield event
                continue

            if isinstance(event, ToolCallEndEvent):
                tc_id = event.tool_call_id
                name = tool_call_names.get(tc_id, "tool")
                args = "".join(tool_call_args.pop(tc_id, []))
                if pending_text:
                    ordered_parts.append(
                        {"type": "text", "text": "".join(pending_text)},
                    )
                    pending_text.clear()
                ordered_parts.append({"type": "tool_ref", "id": tc_id})
                completed_tools.append(
                    {
                        "id": tc_id,
                        "name": name,
                        "arguments": args,
                        "result": "",
                        "status": "completed",
                    },
                )
                yield event
                yield self._build_state(
                    status="thinking",
                    intent=intent.value,
                    active_agent="SAP-Agent",
                    tools=[{"name": tc["name"], "status": "completed"} for tc in completed_tools],
                )

                continue

            if isinstance(event, ToolCallResultEvent):
                for tc in completed_tools:
                    if tc["id"] == event.tool_call_id:
                        tc["result"] = event.content or ""
                        break
                yield event
                continue

            if isinstance(event, TextMessageContentEvent):
                pending_text.append(event.delta)

            yield event

        if pending_text:
            ordered_parts.append(
                {"type": "text", "text": "".join(pending_text)},
            )

    async def _run_handoff_workflow(
        self,
        *,
        input_data: dict[str, Any],
        config: Any,
        intent: Any,
        user_text: str,
        thread_id: str,
        completed_tools: list[dict[str, str]],
        ordered_parts: list[dict[str, Any]],
    ) -> AsyncGenerator[BaseEvent]:
        """
        Run a multi-agent handoff workflow.

        :yields: AG-UI events with real-time streaming.
        """
        workflow = self._factory.create_workflow(
            config=config,
            user_query=user_text,
            thread_id=thread_id,
        )

        workflow_agent = workflow.as_agent(name="SAP-Pipeline")
        delegate = AgentFrameworkAgent(
            agent=workflow_agent,
            name="SAP-Pipeline",
            description="SAP multi-agent investigation pipeline.",
            state_schema=self._STATE_SCHEMA,
            predict_state_config=self._PREDICT_STATE_CONFIG,
            require_confirmation=False,
        )

        pending_text: list[str] = []
        current_agent: str = ""
        thinking_msg_ids: set[str] = set()
        thinking_open: bool = False
        thinking_reasoning_id: str = ""
        tool_call_names: dict[str, str] = {}
        run_started_skipped = False

        async for event in delegate.run(input_data):
            if isinstance(event, (RunStartedEvent, RunFinishedEvent)):
                if isinstance(event, RunStartedEvent) and not run_started_skipped:
                    run_started_skipped = True
                continue
            if isinstance(event, ReasoningMessageStartEvent):
                yield ReasoningMessageStartEvent.model_construct(
                    type="REASONING_MESSAGE_START",
                    message_id=event.message_id,
                    role="reasoning",
                )
                continue

            if isinstance(event, ToolCallStartEvent):
                name = event.tool_call_name or ""
                if name.startswith("handoff_to_") or name == "request_info":
                    tool_call_names[event.tool_call_id] = name
                    continue
            if isinstance(
                event,
                (ToolCallArgsEvent, ToolCallEndEvent, ToolCallResultEvent),
            ):
                tc_id = event.tool_call_id
                skipped = tool_call_names.get(tc_id, "")
                if skipped.startswith("handoff_to_") or skipped == "request_info":
                    continue
            if isinstance(event, ToolCallStartEvent):
                name = event.tool_call_name or "tool"
                tool_call_names[event.tool_call_id] = name
                yield self._build_state(
                    status="calling_tool",
                    intent=intent.value,
                    active_agent=current_agent or None,
                    tools=[
                        *[{"name": tc["name"], "status": "completed"} for tc in completed_tools],
                        {"name": name, "status": "in_progress"},
                    ],
                )
                yield event
                continue

            if isinstance(event, ToolCallEndEvent):
                tc_id = event.tool_call_id
                name = tool_call_names.get(tc_id, "tool")
                if pending_text:
                    ordered_parts.append(
                        {"type": "text", "text": "".join(pending_text)},
                    )
                    pending_text.clear()
                ordered_parts.append({"type": "tool_ref", "id": tc_id})
                completed_tools.append(
                    {"id": tc_id, "name": name, "status": "completed"},
                )
                yield event
                yield self._build_state(
                    status="thinking",
                    intent=intent.value,
                    active_agent=current_agent or None,
                    tools=[{"name": tc["name"], "status": "completed"} for tc in completed_tools],
                )
                continue

            if isinstance(event, ToolCallArgsEvent):
                yield event
                continue

            if isinstance(event, ToolCallResultEvent):
                for tc in completed_tools:
                    if tc["id"] == event.tool_call_id:
                        tc["result"] = event.content or ""
                        break
                yield event
                continue

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

            if isinstance(event, TextMessageEndEvent):
                if event.message_id in thinking_msg_ids:
                    thinking_msg_ids.discard(event.message_id)
                    yield ReasoningMessageEndEvent(
                        message_id=event.message_id,
                    )
                    if not thinking_msg_ids:
                        yield ReasoningEndEvent(
                            message_id=thinking_reasoning_id,
                        )
                        thinking_open = False
                    continue

            if current_agent in self._THINKING_AGENTS:
                if isinstance(event, TextMessageStartEvent):
                    thinking_msg_ids.add(event.message_id)
                    if not thinking_open:
                        thinking_reasoning_id = str(uuid4())
                        yield ReasoningStartEvent(
                            message_id=thinking_reasoning_id,
                        )
                        thinking_open = True
                    yield ReasoningMessageStartEvent.model_construct(
                        type="REASONING_MESSAGE_START",
                        message_id=event.message_id,
                        role="reasoning",
                    )
                    continue
                if isinstance(event, TextMessageContentEvent):
                    if event.message_id in thinking_msg_ids:
                        pending_text.append(event.delta)
                        yield ReasoningMessageContentEvent(
                            message_id=event.message_id,
                            delta=event.delta,
                        )
                        continue

            if isinstance(event, TextMessageContentEvent):
                pending_text.append(event.delta)

            yield event

        if thinking_open:
            yield ReasoningEndEvent(
                message_id=thinking_reasoning_id,
            )
        if pending_text:
            ordered_parts.append(
                {"type": "text", "text": "".join(pending_text)},
            )

    @staticmethod
    def _sanitize_messages(
        input_data: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Strip tool_calls from assistant messages that lack
        matching tool results.

        :param input_data: Original AG-UI input.
        :returns: Sanitized copy of input_data.
        """
        messages = input_data.get("messages")
        if not messages:
            return input_data

        tool_result_ids: set[str] = set()
        for msg in messages:
            if msg.get("role") == "tool":
                tc_id = msg.get("toolCallId") or msg.get("tool_call_id") or ""
                if tc_id:
                    tool_result_ids.add(tc_id)

        clean: list[dict[str, Any]] = []
        for msg in messages:
            if msg.get("role") == "assistant" and msg.get("toolCalls"):
                matched = [tc for tc in msg["toolCalls"] if tc.get("id") in tool_result_ids]
                if matched:
                    clean.append({**msg, "toolCalls": matched})
                else:
                    clean.append(
                        {k: v for k, v in msg.items() if k != "toolCalls"},
                    )
            else:
                clean.append(msg)

        return {**input_data, "messages": clean}

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
            logger.warning("Could not save user message", exc_info=True)

    def _save_assistant_message(
        self,
        conv_id: str,
        ordered_parts: list[dict[str, Any]],
        completed_tools: list[dict[str, str]],
    ) -> None:
        """
        Persist the assistant response as AF Message(s).

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
                        [
                            Content.from_function_result(
                                call_id=tc["id"],
                                result=tc.get("result", ""),
                            )
                        ],
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
