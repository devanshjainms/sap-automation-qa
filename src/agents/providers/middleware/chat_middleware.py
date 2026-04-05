# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Chat-level middleware: investigation depth awareness.
"""

from __future__ import annotations
import logging
from collections.abc import Awaitable, Callable, Sequence
from agent_framework import ChatContext, ChatMiddleware, Message

logger = logging.getLogger(__name__)


class InvestigationChatMiddleware(ChatMiddleware):
    """
    Injects investigation-depth awareness into each LLM round.
    """

    _STATUS_PREFIX = "[Investigation status]"
    _RESULT_TYPES = frozenset({"function_result", "mcp_server_tool_result"})
    _CALL_TYPES = frozenset({"function_call", "mcp_server_tool_call"})

    def __init__(self, *, min_evidence: int = 3) -> None:
        """Initialize the middleware.

        :param min_evidence: Minimum tool-result count before the
            middleware stops nudging the agent to gather more data.
        """
        self._min_evidence = min_evidence

    def _is_status(self, msg: Message) -> bool:
        """Return ``True`` if *msg* is a previously-injected status header."""
        return (
            msg.role == "system"
            and msg.text is not None
            and msg.text.startswith(self._STATUS_PREFIX)
        )

    def _scan(self, messages: Sequence[Message]) -> tuple[int, set[str]]:
        """Count tool results and collect unique tool names.

        :param messages: The full conversation so far.
        :returns: ``(evidence_count, tools_called)`` tuple.
        """
        evidence = 0
        tools: set[str] = set()
        for msg in messages:
            if not msg.contents:
                continue
            for c in msg.contents:
                if c.type in self._RESULT_TYPES:
                    evidence += 1
                elif c.type in self._CALL_TYPES and c.name:
                    tools.add(c.name)
        return evidence, tools

    def _build_header(
        self,
        evidence_count: int,
        tools_called: set[str],
    ) -> str:
        """Build a compact status string for injection.

        :param evidence_count: Total tool-result content items.
        :param tools_called: Set of unique tool names invoked so far.
        :returns: A short multi-line status block.
        """
        parts: list[str] = [f"{self._STATUS_PREFIX}"]
        if evidence_count < self._min_evidence:
            parts.append(
                f"You have only {evidence_count} of {self._min_evidence} "
                "required evidence items. DO NOT stop. Continue calling "
                "tools to gather more evidence right now."
            )
        else:
            parts.append(
                "You have gathered sufficient evidence. "
                "Answer the user's question now with the evidence you have."
            )
        return " ".join(parts)

    async def process(
        self,
        context: ChatContext,
        call_next: Callable[[], Awaitable[None]],
    ) -> None:
        """Inject an investigation status header then forward to the LLM.

        :param context: Framework-provided chat context with the full
            message history including accumulated tool results.
        :param call_next: Calls the next middleware or the LLM itself.
        """
        evidence_count, tools_called = self._scan(context.messages)

        if evidence_count > 0:
            header = self._build_header(evidence_count, tools_called)
            context.messages = [m for m in context.messages if not self._is_status(m)] + [
                Message("system", text=header)
            ]

            logger.info(
                "chat.status  evidence=%d  unique_tools=%d  nudge=%s",
                evidence_count,
                len(tools_called),
                evidence_count < self._min_evidence,
            )

        await call_next()
