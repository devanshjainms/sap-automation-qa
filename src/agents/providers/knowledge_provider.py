# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Knowledge context provider — proactive KB injection.
"""

from __future__ import annotations
import logging
from typing import Any, List
from agent_framework import BaseContextProvider
from src.core.knowledge.retrieval import HybridRetriever, ScoredResult

logger = logging.getLogger(__name__)

_MAX_RULES = 15
_MAX_PLAYBOOKS = 10
_MAX_PATTERNS = 10
_MIN_SCORE = 0.5


class KnowledgeContextProvider(BaseContextProvider):
    """Injects relevant KB entries into agent instructions.

    Follows the same pattern as :class:`WorkspaceContextProvider` —
    extends ``BaseContextProvider`` and overrides ``before_run``.

    When *user_query* is provided at init time it is used for every
    invocation.  When omitted (the AG-UI singleton case) the provider
    extracts the latest user message from ``context.input_messages``
    at runtime so it works correctly for every conversation.

    :param retriever: Hybrid retriever for knowledge search.
    :param user_query: Optional fixed query (omit for dynamic extraction).
    """

    def __init__(
        self,
        retriever: HybridRetriever,
        user_query: str | None = None,
    ) -> None:
        super().__init__("knowledge-context")
        self._retriever = retriever
        self._user_query = user_query

    @staticmethod
    def _format_rules(results: List[ScoredResult]) -> str:
        """Format matched rules into a compact summary."""
        lines = ["## Matching rules"]
        for r in results:
            rule = r.item
            lines.append(f"- **{rule.id}** {rule.name} " f"[{rule.severity}] — {rule.description}")
        return "\n".join(lines)

    @staticmethod
    def _format_playbooks(results: List[ScoredResult]) -> str:
        """Format matched playbooks into a compact summary."""
        lines = ["## Matching playbooks"]
        for r in results:
            pb = r.item
            lines.append(f"- **{pb.id}** {pb.name} — {pb.description}")
            if pb.symptoms:
                lines.append(f"  Symptoms: {', '.join(pb.symptoms[:5])}")
        return "\n".join(lines)

    @staticmethod
    def _format_patterns(results: List[ScoredResult]) -> str:
        """Format matched learned patterns into a compact summary."""
        lines = ["## Learned patterns from past sessions"]
        for r in results:
            pat = r.item
            confidence_note = " ⚠ low confidence" if r.low_confidence else ""
            lines.append(
                f"- **{pat.id}** {pat.name} " f"(confidence={pat.confidence:.2f}{confidence_note})"
            )
            if pat.symptoms:
                lines.append(f"  Symptoms: {', '.join(pat.symptoms[:5])}")
            if pat.fixes:
                lines.append(f"  Fixes: {', '.join(pat.fixes[:3])}")
        return "\n".join(lines)

    def _build_context(self, query: str) -> str:
        """Query the retriever and format results."""
        parts: list[str] = []

        rules = self._retriever.search_rules(query=query, limit=_MAX_RULES)
        rules = [r for r in rules if r.score >= _MIN_SCORE]
        if rules:
            parts.append(self._format_rules(rules))

        playbooks = self._retriever.search_playbooks(
            query=query,
            limit=_MAX_PLAYBOOKS,
        )
        playbooks = [p for p in playbooks if p.score >= _MIN_SCORE]
        if playbooks:
            parts.append(self._format_playbooks(playbooks))

        patterns = self._retriever.search_learned_patterns(
            query=query,
            limit=_MAX_PATTERNS,
        )
        patterns = [p for p in patterns if p.score >= _MIN_SCORE]
        if patterns:
            parts.append(self._format_patterns(patterns))

        if not parts:
            return ""

        header = (
            "# Relevant knowledge (from KB)\n"
            "The following rules, playbooks, and patterns are relevant "
            "to the user's request. Use them to guide your investigation "
            "but always verify with fresh evidence."
        )
        return header + "\n\n" + "\n\n".join(parts)

    async def before_run(
        self,
        *,
        agent: Any,
        session: Any,
        context: Any,
        state: dict[str, Any],
    ) -> None:
        """Search KB and inject matching items as instructions."""
        query = self._user_query
        if not query and hasattr(context, "input_messages"):
            for msg in reversed(context.input_messages):
                if msg.role == "user" and msg.text:
                    query = msg.text
                    break

        if not query:
            return

        self._user_query_resolved = query
        text = self._build_context(query)
        if text:
            context.extend_instructions(self.source_id, text)
            logger.info(
                "Injected KB context (%d chars) for query: %s",
                len(text),
                query[:60],
            )
