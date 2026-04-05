# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Retrieval tools — knowledge base search (rules, playbooks, patterns)."""

from __future__ import annotations

import logging
from typing import Any

from mcp.server.fastmcp import Context
from mcp.server.session import ServerSession
from mcp.types import ToolAnnotations

from src.mcp_server.server import SapContext, mcp
from src.mcp_server.tools._helpers import ICON_BOOK

logger = logging.getLogger(__name__)


class RetrievalTools:
    """Knowledge base search — rules, playbooks, and learned patterns."""

    @staticmethod
    @mcp.tool(
        name="query_knowledge",
        title="Query Knowledge Base",
        description=(
            "Search the SAP knowledge base for rules, playbooks, and learned "
            "patterns from previous investigations. Returns matching rules, "
            "remediation playbooks, and experience-based patterns with "
            "confidence scores. Learned patterns include root causes, symptoms, "
            "and fixes from past triage sessions."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
        icons=[ICON_BOOK],
        structured_output=False,
    )
    async def query_knowledge(
        query: str,
        category: str = "",
        limit: int = 20,
        ctx: Context[ServerSession, SapContext] | None = None,
    ) -> dict[str, Any]:
        """Search the SAP knowledge base for rules, playbooks, and learned patterns."""
        logger.info("Tool called: query_knowledge(query=%s)", query[:100])
        assert ctx is not None
        sap: SapContext = ctx.request_context.lifespan_context

        query = sap.validator.query(query)
        limit = max(1, min(limit, 100))

        rule_results = sap.retriever.search_rules(query=query, limit=1000)
        playbook_results = sap.retriever.search_playbooks(query=query, limit=1000)
        pattern_results = sap.retriever.search_learned_patterns(query=query, limit=limit)

        if category:
            rule_results = [
                r
                for r in rule_results
                if category.lower() in getattr(r.item, "category", "").lower()
            ]

        total_rules = len(rule_results)
        total_playbooks = len(playbook_results)

        return {
            "rules": [
                {
                    "id": r.item_id,
                    "name": getattr(r.item, "name", ""),
                    "severity": getattr(r.item, "severity", ""),
                    "category": getattr(r.item, "category", ""),
                    "score": round(r.score, 3),
                }
                for r in rule_results[:limit]
            ],
            "playbooks": [
                {
                    "id": r.item_id,
                    "name": getattr(r.item, "name", ""),
                    "category": getattr(r.item, "category", ""),
                    "score": round(r.score, 3),
                }
                for r in playbook_results[:limit]
            ],
            "learned_patterns": [
                {
                    "id": r.item_id,
                    "name": getattr(r.item, "name", ""),
                    "category": getattr(r.item, "category", ""),
                    "root_cause": getattr(r.item, "root_cause", ""),
                    "symptoms": getattr(r.item, "symptoms", []),
                    "fixes": getattr(r.item, "fixes", []),
                    "confidence": round(r.confidence, 3),
                    "score": round(r.score, 3),
                    "low_confidence": r.low_confidence,
                    "occurrence_count": getattr(r.item, "occurrence_count", 1),
                }
                for r in pattern_results[:limit]
            ],
            "total_rules": total_rules,
            "total_playbooks": total_playbooks,
            "total_learned_patterns": len(pattern_results),
        }
