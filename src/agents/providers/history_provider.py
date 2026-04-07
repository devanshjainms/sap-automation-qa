# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Conversation history provider backed by our ConversationStore.

Stores full agent framework Messages (including tool calls) serialized
as JSON in the message metadata field, so multi-turn conversations
preserve tool call context.
"""

from __future__ import annotations
import asyncio
import logging
from collections.abc import Callable
from typing import Any

from agent_framework import BaseHistoryProvider, AgentSession, SessionContext
from agent_framework._types import Message as AFMessage

from src.core.storage.conversation_store import ConversationStore

logger = logging.getLogger(__name__)

# Type alias for the async title generator function.
TitleGenerator = Callable[[str], Any]  # async (user_text) -> str


class ConversationHistoryProvider(BaseHistoryProvider):
    """Persists full agent conversation history to ConversationStore.

    Stores serialized AF Messages (including tool calls) in the
    metadata field so the agent sees full context on follow-up turns.

    :param store: The SQLite-backed conversation store.
    :param title_generator: Async callable that generates a title.
    :param conversation_id: Explicit conversation ID — bypasses
        session-based lookup.  Used by workflow-level callers that
        know the AG-UI ``thread_id`` up-front.
    :param save_enabled: When ``False`` the provider only loads
        history; ``after_run`` becomes a no-op.  Useful for agents
        inside a sequential workflow where persistence is handled
        at the workflow boundary.
    """

    def __init__(
        self,
        store: ConversationStore,
        title_generator: TitleGenerator | None = None,
        *,
        conversation_id: str | None = None,
        save_enabled: bool = True,
    ) -> None:
        super().__init__(
            "conversation-store",
            load_messages=True,
            store_inputs=True,
            store_outputs=True,
        )
        self._store = store
        self._title_generator = title_generator
        self._conversation_id = conversation_id
        self._save_enabled = save_enabled

    async def before_run(
        self,
        *,
        agent: Any,
        session: AgentSession,
        context: SessionContext,
        state: dict[str, Any],
    ) -> None:
        """Load conversation history from SQLite before agent runs."""
        conv_id = self._get_conv_id(session, context)
        if not conv_id:
            return

        try:
            messages = self._store.get_history(conv_id, limit=30)
        except Exception:
            logger.debug("Could not load history for %s", conv_id)
            return

        sanitized: list[AFMessage] = []
        for msg in messages:
            sanitized.append(self._sanitize_silent_tool_call(msg))

        if sanitized:
            context.extend_messages(self, sanitized)
            logger.info(
                "history: loaded %d AF messages for %s",
                len(sanitized),
                conv_id[:8],
            )

    async def after_run(
        self,
        *,
        agent: Any,
        session: AgentSession,
        context: SessionContext,
        state: dict[str, Any],
    ) -> None:
        """Save messages to SQLite after agent runs."""
        if not self._save_enabled:
            return

        conv_id = self._get_conv_id(session, context)
        if not conv_id:
            return

        saved = 0

        # Save the last user input as an AF message.
        user_msgs = [
            msg
            for msg in (context.input_messages or [])
            if getattr(msg, "role", "") == "user" and getattr(msg, "text", "")
        ]
        if user_msgs:
            try:
                self._store.add_message(conv_id, user_msgs[-1])
                saved += 1
            except Exception:
                logger.debug("Could not save user message", exc_info=True)

        # Save all response AF messages directly.
        response = context.response
        if response and hasattr(response, "messages") and response.messages:
            for msg in response.messages:
                try:
                    self._store.add_message(conv_id, msg)
                    saved += 1
                except Exception:
                    logger.debug("Could not save response message", exc_info=True)

        logger.info("history: saved %d messages to %s", saved, conv_id[:8])

        if self._title_generator and not context.context_messages.get(self.source_id):
            user_text = ""
            for msg in context.input_messages or []:
                if getattr(msg, "role", "") == "user" and getattr(msg, "text", ""):
                    user_text = msg.text
                    break
            if user_text:
                asyncio.create_task(self._set_title(conv_id, user_text))

    async def _set_title(self, conv_id: str, user_text: str) -> None:
        """Generate and persist a conversation title.

        Runs as a fire-and-forget task so it never blocks the
        response stream.  Errors are logged and swallowed.

        :param conv_id: Conversation to update.
        :param user_text: First user message text.
        """
        try:
            if self._title_generator is None:
                return
            title = await self._title_generator(user_text)
            title = str(title).strip().strip('"').strip("'")[:80]
            if title:
                self._store.update_title(conv_id, title)
                logger.info("history: set title for %s: %s", conv_id[:8], title)
        except Exception:
            logger.debug("Could not generate title for %s", conv_id[:8], exc_info=True)

    async def get_messages(self, session_id, *, state=None, **kwargs):
        return []

    async def save_messages(self, session_id, messages, *, state=None, **kwargs):
        pass

    @staticmethod
    def _sanitize_silent_tool_call(msg: AFMessage) -> AFMessage:
        """Inject synthetic text into assistant messages that only have tool calls.

        Assistant messages that contain only ``FunctionCallContent`` (no text)
        teach the model to make silent tool calls via in-context learning.
        This method injects a short synthetic ``TextContent`` before the
        function-call items so the model always sees a think-before-act
        pattern in its history.

        :param msg: AF Message to sanitize.
        :returns: Possibly-modified AF Message with text content prepended.
        """
        if msg.role != "assistant":
            return msg

        msg_dict = msg.to_dict()
        contents = msg_dict.get("contents", [])
        if not contents:
            return msg

        has_text = any(c.get("type") == "text" for c in contents)
        has_call = any(c.get("type") == "function_call" for c in contents)

        if has_call and not has_text:
            tool_names = [
                c.get("name", "tool") for c in contents if c.get("type") == "function_call"
            ]
            label = ", ".join(tool_names)
            synthetic = {"type": "text", "text": f"Let me call {label}."}
            msg_dict = {**msg_dict, "contents": [synthetic, *contents]}
            try:
                return AFMessage.from_dict(msg_dict)
            except Exception:
                return msg

        return msg

    def _get_conv_id(self, session: AgentSession, context: SessionContext) -> str:
        if self._conversation_id:
            return self._conversation_id
        if hasattr(context, "service_session_id") and context.service_session_id:
            return context.service_session_id
        if hasattr(session, "service_session_id") and session.service_session_id:
            return session.service_session_id
        return context.session_id or ""
