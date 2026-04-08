# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
AG-UI integration — Single-agent intents use ``AgentFrameworkAgent`` directly.
Handoff intents use ``workflow.as_agent()`` → ``AgentFrameworkAgent``.
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
    BaseEvent,
    ReasoningMessageStartEvent,
    TextMessageContentEvent,
    ToolCallArgsEvent,
    ToolCallEndEvent,
    ToolCallResultEvent,
    ToolCallStartEvent,
)
from agent_framework import Message as AFMessage
from agent_framework._types import Content
from agent_framework_ag_ui import (
    AgentFrameworkAgent,
    AgentFrameworkWorkflow,
    add_agent_framework_fastapi_endpoint,
)

from src.agents.agent import SapAgentFactory
from src.agents.agent_config import InvestigationIntent, config_for_intent
from src.core.models.conversation import Conversation
from src.core.storage.conversation_store import ConversationStore

logger = logging.getLogger(__name__)


class SapWorkflow(AgentFrameworkWorkflow):
    """AG-UI endpoint: classify → delegate → persist.

    :param factory: Agent factory with MCP connections.
    :param conversation_store: SQLite conversation store.
    """

    def __init__(
        self,
        factory: SapAgentFactory,
        conversation_store: ConversationStore | None,
        *,
        name: str | None = None,
        description: str | None = None,
    ) -> None:
        super().__init__(name=name, description=description)
        self._factory = factory
        self._store = conversation_store

    async def run(
        self,
        input_data: dict[str, Any],
    ) -> AsyncGenerator[BaseEvent]:
        thread_id = input_data.get("thread_id", "")
        run_id = input_data.get("run_id", str(uuid4()))
        user_text = self._extract_user_text(input_data)
        stream_start = time.perf_counter()

        # Classify intent.
        intent = await self._factory.classify_intent(user_text)
        config = config_for_intent(intent)

        logger.info(
            "AG-UI run: thread=%r run=%s intent=%s msgs=%d",
            thread_id[:8] if thread_id else "",
            run_id[:12] if run_id else "",
            intent.value,
            len(input_data.get("messages", [])),
        )

        if self._store and thread_id:
            self._ensure_conversation(thread_id)

        input_data = self._sanitize_messages(input_data)

        # Create agent (plain or workflow-as-agent).
        if intent in (InvestigationIntent.TRIAGE, InvestigationIntent.TEST):
            workflow = self._factory.create_workflow(
                config=config,
                user_query=user_text,
                thread_id=thread_id,
            )
            agent = workflow.as_agent(name="SAP-Pipeline")
        else:
            agent = self._factory.create_agent(
                config=config,
                user_query=user_text,
                thread_id=thread_id,
            )

        delegate = AgentFrameworkAgent(
            agent=agent,
            name="SAP-Agent",
            description="SAP infrastructure specialist for Azure.",
            require_confirmation=False,
        )

        # Stream — only intercept for role fix + persistence tracking.
        completed_tools: list[dict[str, str]] = []
        ordered_parts: list[dict[str, Any]] = []
        pending_text: list[str] = []
        tool_call_names: dict[str, str] = {}
        tool_call_args: dict[str, list[str]] = {}

        async for event in delegate.run(input_data):
            # Fix framework bug: role="assistant" → role="reasoning".
            if isinstance(event, ReasoningMessageStartEvent):
                yield ReasoningMessageStartEvent.model_construct(
                    type="REASONING_MESSAGE_START",
                    message_id=event.message_id,
                    role="reasoning",
                )
                continue

            # Track tool calls for persistence.
            if isinstance(event, ToolCallStartEvent):
                tool_call_names[event.tool_call_id] = event.tool_call_name or "tool"
                tool_call_args[event.tool_call_id] = []

            if isinstance(event, ToolCallArgsEvent):
                if event.tool_call_id in tool_call_args:
                    tool_call_args[event.tool_call_id].append(event.delta)

            if isinstance(event, ToolCallEndEvent):
                tc_id = event.tool_call_id
                name = tool_call_names.get(tc_id, "tool")
                args = "".join(tool_call_args.pop(tc_id, []))
                if pending_text:
                    ordered_parts.append({"type": "text", "text": "".join(pending_text)})
                    pending_text.clear()
                ordered_parts.append({"type": "tool_ref", "id": tc_id})
                completed_tools.append(
                    {"id": tc_id, "name": name, "arguments": args, "result": ""},
                )

            if isinstance(event, ToolCallResultEvent):
                for tc in completed_tools:
                    if tc["id"] == event.tool_call_id:
                        tc["result"] = event.content or ""
                        break

            if isinstance(event, TextMessageContentEvent):
                pending_text.append(event.delta)

            yield event

        # Flush remaining text.
        if pending_text:
            ordered_parts.append({"type": "text", "text": "".join(pending_text)})

        # Persist.
        duration = int((time.perf_counter() - stream_start) * 1000)
        logger.info(
            "AG-UI done: thread=%s intent=%s duration=%dms tools=%s",
            thread_id[:8] if thread_id else "",
            intent.value,
            duration,
            [tc["name"] for tc in completed_tools] or "none",
        )
        if self._store and thread_id:
            if user_text:
                self._save_user_message(thread_id, user_text)
            if ordered_parts:
                self._save_assistant_message(thread_id, ordered_parts, completed_tools)
            if user_text:
                asyncio.create_task(
                    self._factory._generate_title(user_text),
                ).add_done_callback(lambda fut: self._apply_title(thread_id, fut))

    # ── Helpers ──────────────────────────────────────────

    @staticmethod
    def _sanitize_messages(input_data: dict[str, Any]) -> dict[str, Any]:
        """Strip orphan tool_calls from message history."""
        messages = input_data.get("messages")
        if not messages:
            return input_data
        tool_ids: set[str] = set()
        for msg in messages:
            if msg.get("role") == "tool":
                tc_id = msg.get("toolCallId") or msg.get("tool_call_id") or ""
                if tc_id:
                    tool_ids.add(tc_id)
        clean: list[dict[str, Any]] = []
        for msg in messages:
            if msg.get("role") == "assistant" and msg.get("toolCalls"):
                matched = [tc for tc in msg["toolCalls"] if tc.get("id") in tool_ids]
                if matched:
                    clean.append({**msg, "toolCalls": matched})
                else:
                    clean.append({k: v for k, v in msg.items() if k != "toolCalls"})
            else:
                clean.append(msg)
        return {**input_data, "messages": clean}

    def _ensure_conversation(self, thread_id: str) -> None:
        assert self._store is not None
        try:
            if self._store.get(thread_id):
                return
            self._store.create(Conversation(id=UUID(thread_id), workspace_id=""))
            logger.info("Created conversation %s", thread_id[:8])
        except Exception:
            logger.debug("Could not ensure conversation %s", thread_id[:8], exc_info=True)

    def _save_user_message(self, conv_id: str, text: str) -> None:
        assert self._store is not None
        try:
            self._store.add_message(conv_id, AFMessage("user", [text]))
        except Exception:
            logger.warning("Could not save user message", exc_info=True)

    def _save_assistant_message(
        self,
        conv_id: str,
        ordered_parts: list[dict[str, Any]],
        completed_tools: list[dict[str, str]],
    ) -> None:
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
                                call_id=tc["id"], result=tc.get("result", "")
                            )
                        ],
                    ),
                )
        except Exception:
            logger.debug("Could not save assistant message", exc_info=True)

    def _apply_title(self, conv_id: str, fut: asyncio.Future) -> None:
        try:
            title = str(fut.result()).strip().strip('"').strip("'")[:80]
            if title and self._store:
                self._store.update_title(conv_id, title)
                logger.info("Set title for %s: %s", conv_id[:8], title)
        except Exception:
            logger.debug("Title generation failed", exc_info=True)

    @staticmethod
    def _extract_user_text(input_data: dict[str, Any]) -> str:
        for msg in reversed(input_data.get("messages", [])):
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, str):
                    return content
                if isinstance(content, list):
                    return " ".join(
                        p.get("text", "")
                        for p in content
                        if isinstance(p, dict) and p.get("type") == "text"
                    )
        return ""


def register_ag_ui(
    app: FastAPI,
    factory: SapAgentFactory,
    path: str = "/ag-ui",
    allow_origins: list[str] | None = None,
    conversation_store: ConversationStore | None = None,
) -> None:
    ag_ui_workflow = SapWorkflow(
        factory=factory,
        conversation_store=conversation_store,
        name="SAP-Agent",
        description="SAP infrastructure specialist for Azure.",
    )
    add_agent_framework_fastapi_endpoint(app, ag_ui_workflow, path, allow_origins=allow_origins)
    logger.info("AG-UI endpoint registered at %s", path)
