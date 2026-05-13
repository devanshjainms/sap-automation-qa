# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Hybrid retriever: structured filter + semantic similarity search.

Uses sentence-transformers for in-process embedding. Falls back to
keyword matching when no embedding provider is configured.
"""

import logging
import math
import numpy as np
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional
from src.core.services.embedding import EmbeddingProvider, cosine_similarity_matrix
from src.core.knowledge.base import KnowledgeBase
from src.core.models.system import SystemProperties

_logger = logging.getLogger(__name__)

_WEIGHT_RELEVANCE = 0.45
_WEIGHT_CONFIDENCE = 0.35
_WEIGHT_RECENCY = 0.20
_RECENCY_HALF_LIFE_DAYS = 90.0
CONFIDENCE_WARNING_THRESHOLD = 0.4
CONFIDENCE_EXCLUDE_THRESHOLD = 0.2


@dataclass
class ScoredResult:
    """A search result with its computed relevance score.

    :param item_id: Identifier of the matched item.
    :param item_type: Type of item (rule, playbook, learned_pattern).
    :param score: Composite score (0.0-1.0).
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


class _EmbeddingCache:
    """In-memory cache of item embeddings keyed by item ID."""

    def __init__(self) -> None:
        self._vectors: dict[str, np.ndarray] = {}

    def get_or_compute_batch(
        self,
        items: list[tuple[str, str]],
        provider: EmbeddingProvider,
    ) -> np.ndarray:
        """Compute embeddings for items not yet cached, return all as matrix."""
        missing_ids = []
        missing_texts = []
        for item_id, text in items:
            if item_id not in self._vectors:
                missing_ids.append(item_id)
                missing_texts.append(text)

        if missing_texts:
            vectors = provider.embed_batch(missing_texts)
            for iid, vec in zip(missing_ids, vectors):
                self._vectors[iid] = np.array(vec, dtype=np.float32)

        return np.array(
            [self._vectors[iid] for iid, _ in items],
            dtype=np.float32,
        )


class HybridRetriever:
    """Knowledge retriever: structured filter + semantic similarity.

    When an ``EmbeddingProvider`` is supplied, relevance is computed
    via cosine similarity on in-process embeddings. Falls back to
    keyword matching when embeddings are unavailable.

    Scoring formula::

        score = 0.45 * relevance + 0.35 * confidence + 0.20 * recency

    :param store: Knowledge store for loading rules and patterns.
    :param embedding_provider: Optional in-process embedding provider.
    """

    def __init__(
        self,
        store: KnowledgeBase,
        embedding_provider: Optional[EmbeddingProvider] = None,
    ) -> None:
        """Initialize the retriever.

        :param store: Knowledge store to query.
        :param embedding_provider: Optional embedding provider.
        """
        self._store = store
        self._provider = embedding_provider
        self._cache = _EmbeddingCache() if embedding_provider else None

    @property
    def semantic_enabled(self) -> bool:
        """Return True when semantic search is available."""
        return self._provider is not None

    def _relevance_scores(
        self,
        query: str,
        items: list[tuple[str, str]],
    ) -> dict[str, float]:
        """Compute semantic relevance scores for items.

        :param query: Search query.
        :param items: List of (item_id, text_for_embedding) tuples.
        :returns: Mapping of item_id to relevance score (0.0-1.0).
        """
        if not query.strip() or not items:
            return {iid: 1.0 for iid, _ in items}

        if self._provider is not None and self._cache is not None:
            try:
                query_vec = np.array(
                    self._provider.embed(query),
                    dtype=np.float32,
                )
                corpus = self._cache.get_or_compute_batch(items, self._provider)
                sims = cosine_similarity_matrix(query_vec, corpus)
                scores = np.clip(sims, 0.0, 1.0)
                return {iid: float(scores[i]) for i, (iid, _) in enumerate(items)}
            except Exception:
                _logger.warning(
                    "Semantic search failed; falling back to keywords",
                    exc_info=True,
                )

        return {}

    def search_rules(
        self,
        system: Optional[SystemProperties] = None,
        query: str = "",
        limit: int = 50,
    ) -> List[ScoredResult]:
        """Search rules by applicability + relevance scoring."""
        rules = self._store.load_rules(system)
        items = [(r.id, f"{r.name} {r.description} {' '.join(r.tags)}") for r in rules]
        semantic = self._relevance_scores(query, items)

        results: list[ScoredResult] = []
        for rule in rules:
            relevance = semantic.get(
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
        """Search playbooks by relevance scoring."""
        playbooks = self._store.load_playbooks()
        items = [
            (pb.id, f"{pb.name} {pb.description} {' '.join(pb.symptoms)} {' '.join(pb.tags)}")
            for pb in playbooks
        ]
        semantic = self._relevance_scores(query, items)

        results: list[ScoredResult] = []
        for pb in playbooks:
            relevance = semantic.get(
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
        """Search learned patterns with full scoring formula."""
        patterns = self._store.load_learned_patterns(
            min_confidence=CONFIDENCE_EXCLUDE_THRESHOLD,
        )
        items = [
            (p.id, f"{p.name} {p.description} {' '.join(p.symptoms)} {' '.join(p.tags)}")
            for p in patterns
        ]
        semantic = self._relevance_scores(query, items)
        now = datetime.now(timezone.utc)

        results: list[ScoredResult] = []
        for pattern in patterns:
            relevance = semantic.get(
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

    def search_evidence_definitions(
        self,
        query: str = "",
        limit: int = 15,
    ) -> List[ScoredResult]:
        """Rank evidence definitions by relevance."""
        defs = self._store.load_evidence_definitions()
        items = [(d.id, f"{d.name} {d.description} {d.command} {' '.join(d.tags)}") for d in defs]
        semantic = self._relevance_scores(query, items)

        results: list[ScoredResult] = []
        for d in defs:
            relevance = semantic.get(
                d.id,
                self._keyword_relevance(
                    query,
                    [d.name, d.description, d.command] + d.tags,
                ),
            )
            score = _WEIGHT_RELEVANCE * relevance + _WEIGHT_CONFIDENCE * 1.0
            results.append(
                ScoredResult(
                    item_id=d.id,
                    item_type="evidence",
                    score=score,
                    relevance=relevance,
                    confidence=1.0,
                    recency=1.0,
                    item=d,
                )
            )
        results.sort(key=lambda r: r.score, reverse=True)
        return results[:limit]

    def search_references(
        self,
        query: str = "",
        category: str = "",
        limit: int = 10,
    ) -> List[ScoredResult]:
        """Rank references by relevance, optionally filtered by category."""
        refs = self._store.load_references()
        if category:
            cat_lower = category.lower()
            refs = [r for r in refs if r.category.lower() == cat_lower]

        items = [
            (
                ref.id,
                f"{ref.title} {ref.summary} "
                f"{' '.join(ref.failure_classes)} {' '.join(ref.tags)}",
            )
            for ref in refs
        ]
        semantic = self._relevance_scores(query, items)

        results: list[ScoredResult] = []
        for ref in refs:
            relevance = semantic.get(
                ref.id,
                self._keyword_relevance(
                    query,
                    [ref.title, ref.summary] + ref.failure_classes + ref.tags,
                ),
            )
            score = _WEIGHT_RELEVANCE * relevance + _WEIGHT_CONFIDENCE * 1.0
            results.append(
                ScoredResult(
                    item_id=ref.id,
                    item_type="reference",
                    score=score,
                    relevance=relevance,
                    confidence=1.0,
                    recency=1.0,
                    item=ref,
                )
            )
        results.sort(key=lambda r: r.score, reverse=True)
        return results[:limit]

    @staticmethod
    def _keyword_relevance(query: str, fields: list[str]) -> float:
        """Compute keyword relevance score (fallback).

        :param query: Search query string.
        :param fields: Text fields to search in.
        :returns: Relevance score (0.0-1.0).
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

    @staticmethod
    def _recency_score(last_seen: datetime, now: datetime) -> float:
        """Compute exponential recency decay (half-life 90 days)."""
        if last_seen.tzinfo is None:
            last_seen = last_seen.replace(tzinfo=timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        age_days = max(0.0, (now - last_seen).total_seconds() / 86400.0)
        return math.exp(-0.693 * age_days / _RECENCY_HALF_LIFE_DAYS)
