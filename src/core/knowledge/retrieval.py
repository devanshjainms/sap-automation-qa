# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Hybrid retriever: structured filter + vector similarity search,
with keyword fallback when embeddings are unavailable."""

import logging
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional

_logger = logging.getLogger(__name__)

from src.core.models.embedding import EmbeddingProvider
from src.core.storage.embedding_store import EmbeddingStore
from src.core.storage.knowledge_store import KnowledgeStore
from src.core.models.knowledge import LearnedPattern, Playbook, Rule
from src.core.models.system import SystemProperties

# Scoring weights from Section 7.3.1
_WEIGHT_RELEVANCE = 0.45
_WEIGHT_CONFIDENCE = 0.35
_WEIGHT_RECENCY = 0.20

# Recency decay half-life in days
_RECENCY_HALF_LIFE_DAYS = 90.0

# Confidence thresholds for learned patterns
CONFIDENCE_WARNING_THRESHOLD = 0.4
CONFIDENCE_EXCLUDE_THRESHOLD = 0.2


@dataclass
class ScoredResult:
    """A search result with its computed relevance score.

    :param item_id: Identifier of the matched item.
    :param item_type: Type of item (rule, playbook, learned_pattern).
    :param score: Composite score (0.0–1.0).
    :param relevance: Relevance sub-score.
    :param confidence: Confidence sub-score.
    :param recency: Recency sub-score.
    :param item: The matched object.
    :param low_confidence: True if confidence < WARNING threshold.
    """

    item_id: str
    item_type: str
    score: float
    relevance: float = 0.0
    confidence: float = 1.0
    recency: float = 1.0
    item: object = None
    low_confidence: bool = False


class HybridRetriever:
    """Strategy pattern retriever: structured filter + vector similarity.

    Scoring formula::

        score = 0.45 * relevance + 0.35 * confidence + 0.20 * recency

    When an ``EmbeddingStore`` and ``EmbeddingProvider`` are supplied,
    relevance is computed via cosine similarity from ``sqlite-vec``.
    Falls back to keyword matching on tags, symptoms, and description
    when embeddings are not available for a given item.

    :param store: Knowledge store for loading rules and patterns.
    :param embedding_store: Optional vector store for embeddings.
    :param embedding_provider: Optional provider for query embedding.
    """

    def __init__(
        self,
        store: KnowledgeStore,
        embedding_store: Optional[EmbeddingStore] = None,
        embedding_provider: Optional[EmbeddingProvider] = None,
    ) -> None:
        """Initialize the retriever.

        :param store: Knowledge store to query.
        :param embedding_store: Optional embedding store.
        :param embedding_provider: Optional embedding provider.
        """
        self._store = store
        self._embedding_store = embedding_store
        self._embedding_provider = embedding_provider

    @property
    def vector_enabled(self) -> bool:
        """Return True when vector search is available."""
        return self._embedding_store is not None and self._embedding_provider is not None

    def search_rules(
        self,
        system: Optional[SystemProperties] = None,
        query: str = "",
        limit: int = 50,
    ) -> List[ScoredResult]:
        """Search rules by applicability + relevance scoring.

        :param system: System properties for structured filtering.
        :param query: Optional query for relevance scoring.
        :param limit: Maximum results to return.
        :returns: Scored results sorted by score descending.
        """
        rules = self._store.load_rules(system)
        vector_scores = self._vector_scores(query, [r.id for r in rules], "rule")

        results: list[ScoredResult] = []
        for rule in rules:
            relevance = vector_scores.get(
                rule.id,
                self._keyword_relevance(
                    query,
                    [rule.name, rule.description] + rule.tags,
                ),
            )
            score = _WEIGHT_RELEVANCE * relevance + _WEIGHT_CONFIDENCE * 1.0
            results.append(
                ScoredResult(
                    item_id=rule.id,
                    item_type="rule",
                    score=score,
                    relevance=relevance,
                    confidence=1.0,
                    recency=1.0,
                    item=rule,
                )
            )
        results.sort(key=lambda r: r.score, reverse=True)
        return results[:limit]

    def search_playbooks(
        self,
        query: str = "",
        limit: int = 20,
    ) -> List[ScoredResult]:
        """Search playbooks by relevance scoring.

        :param query: Keyword or semantic query.
        :param limit: Maximum results.
        :returns: Scored results sorted by score descending.
        """
        playbooks = self._store.load_playbooks()
        vector_scores = self._vector_scores(query, [pb.id for pb in playbooks], "playbook")

        results: list[ScoredResult] = []
        for pb in playbooks:
            relevance = vector_scores.get(
                pb.id,
                self._keyword_relevance(
                    query,
                    [pb.name, pb.description] + pb.symptoms + pb.tags,
                ),
            )
            score = _WEIGHT_RELEVANCE * relevance + _WEIGHT_CONFIDENCE * 1.0
            results.append(
                ScoredResult(
                    item_id=pb.id,
                    item_type="playbook",
                    score=score,
                    relevance=relevance,
                    confidence=1.0,
                    recency=1.0,
                    item=pb,
                )
            )
        results.sort(key=lambda r: r.score, reverse=True)
        return results[:limit]

    def search_learned_patterns(
        self,
        query: str = "",
        limit: int = 20,
    ) -> List[ScoredResult]:
        """Search learned patterns with full scoring formula.

        Patterns below ``CONFIDENCE_EXCLUDE_THRESHOLD`` (0.2) are
        excluded. Patterns below ``CONFIDENCE_WARNING_THRESHOLD``
        (0.4) are flagged.

        :param query: Keyword or semantic query.
        :param limit: Maximum results.
        :returns: Scored results sorted by score descending.
        """
        patterns = self._store.load_learned_patterns(min_confidence=CONFIDENCE_EXCLUDE_THRESHOLD)
        vector_scores = self._vector_scores(query, [p.id for p in patterns], "learned_pattern")
        now = datetime.now(timezone.utc)

        results: list[ScoredResult] = []
        for pattern in patterns:
            relevance = vector_scores.get(
                pattern.id,
                self._keyword_relevance(
                    query,
                    [pattern.name, pattern.description] + pattern.symptoms + pattern.tags,
                ),
            )
            recency = self._recency_score(pattern.last_seen, now)
            score = (
                _WEIGHT_RELEVANCE * relevance
                + _WEIGHT_CONFIDENCE * pattern.confidence
                + _WEIGHT_RECENCY * recency
            )
            results.append(
                ScoredResult(
                    item_id=pattern.id,
                    item_type="learned_pattern",
                    score=score,
                    relevance=relevance,
                    confidence=pattern.confidence,
                    recency=recency,
                    item=pattern,
                    low_confidence=(pattern.confidence < CONFIDENCE_WARNING_THRESHOLD),
                )
            )
        results.sort(key=lambda r: r.score, reverse=True)
        return results[:limit]

    # ------------------------------------------------------------------
    # Vector similarity
    # ------------------------------------------------------------------

    def _vector_scores(
        self,
        query: str,
        item_ids: List[str],
        item_type: str,
    ) -> Dict[str, float]:
        """Compute vector relevance for a batch of items.

        Returns a dict mapping ``item_id → similarity`` for items that
        have stored embeddings. Items not in the dict should fall back
        to keyword relevance.

        :param query: Search query text.
        :param item_ids: Candidate item IDs to score.
        :param item_type: Item type (``rule``, ``playbook``, etc.).
        :returns: Mapping of item_id to cosine similarity (0.0–1.0).
        """
        if not self.vector_enabled or not query.strip():
            return {}

        assert self._embedding_store is not None
        assert self._embedding_provider is not None

        try:
            query_vec = self._embedding_provider.embed(query)
        except Exception:  # noqa: BLE001
            _logger.warning(
                "Embedding provider failed for query; " "falling back to keyword search",
                exc_info=True,
            )
            return {}

        try:
            hits = self._embedding_store.search(
                query_embedding=query_vec,
                item_type=item_type,
                limit=len(item_ids),
            )
        except Exception:  # noqa: BLE001
            _logger.warning(
                "Vector search failed; " "falling back to keyword search",
                exc_info=True,
            )
            return {}

        id_set = set(item_ids)
        scores: Dict[str, float] = {}
        for iid, _itype, distance in hits:
            if iid in id_set:
                scores[iid] = max(0.0, 1.0 - distance)
        return scores

    # ------------------------------------------------------------------
    # Keyword fallback
    # ------------------------------------------------------------------

    @staticmethod
    def _keyword_relevance(query: str, fields: list[str]) -> float:
        """Compute keyword relevance score.

        Simple token overlap: fraction of query tokens found in the
        concatenated field text. Returns 1.0 when query is empty
        (match-all behavior for applicability-only searches).

        :param query: Search query string.
        :param fields: Text fields to search in.
        :returns: Relevance score (0.0–1.0).
        """
        if not query.strip():
            return 1.0

        query_tokens = set(query.lower().split())
        field_text = " ".join(f.lower() for f in fields if f)
        field_tokens = set(field_text.split())

        if not query_tokens:
            return 1.0

        matched = query_tokens & field_tokens
        return len(matched) / len(query_tokens)

    # ------------------------------------------------------------------
    # Recency decay
    # ------------------------------------------------------------------

    @staticmethod
    def _recency_score(
        last_seen: datetime,
        now: datetime,
    ) -> float:
        """Compute exponential recency decay score.

        Half-life of 90 days — a pattern last seen 90 days ago
        scores 0.5.

        :param last_seen: When the pattern was last observed.
        :param now: Current timestamp.
        :returns: Recency score (0.0–1.0).
        """
        if last_seen.tzinfo is None:
            last_seen = last_seen.replace(tzinfo=timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        age_days = max(0.0, (now - last_seen).total_seconds() / 86400.0)
        return math.exp(-0.693 * age_days / _RECENCY_HALF_LIFE_DAYS)
