# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""CBR Revise + Retain pipeline: consolidate, revise confidence, store,
link, and log patterns using a Case-Based Reasoning approach.
"""

import hashlib
import logging
from datetime import datetime, timezone
from typing import List, Optional

from src.core.models.embedding import EmbeddingProvider
from src.core.knowledge.retrieval import HybridRetriever
from src.core.storage.embedding_store import EmbeddingStore
from src.core.storage.knowledge_graph import KnowledgeGraph
from src.core.storage.knowledge_store import KnowledgeStore
from src.core.models.knowledge import (
    ExperienceEntry,
    KnowledgeGap,
    LearnedPattern,
)

_log = logging.getLogger(__name__)

# Similarity thresholds for consolidation (Section 7.2.1)
_NEAR_DUPLICATE_THRESHOLD = 0.95
_RELATED_THRESHOLD = 0.85

# Default confidence for newly extracted patterns
_INITIAL_CONFIDENCE = 0.3

# Outcome-weighted confidence adjustments (Section 7.2.1 CBR Revise)
_BOOST_FULL = 0.10
_BOOST_HALF = 0.05
_PENALTY = -0.08

# Age-based confidence decay: 0.02 per 30-day period (Section 7.2.1)
_DECAY_PER_MONTH = 0.02
_DECAY_PERIOD_DAYS = 30.0

# Minimum confidence floor after decay
_CONFIDENCE_FLOOR = 0.05


class LearningPipeline:
    """CBR Revise + Retain pipeline (Section 7.2.1).

    After each completed triage session, the pipeline:

    1. **Consolidate** — de-duplicate candidate against existing patterns.
    2. **Revise** — update confidence using outcome-weighted feedback
       from :class:`ExperienceEntry`.
    3. **Store** — persist new or reinforced pattern + compute embedding.
    4. **Link** — connect to related patterns in the knowledge graph.
    5. **Log** — append session outcome to experience log.

    :param store: Knowledge store for pattern persistence.
    :param graph: Knowledge graph for relationship linking.
    :param retriever: Hybrid retriever for similarity search.
    :param embedding_store: Optional embedding store for vector persistence.
    :param embedding_provider: Optional provider for text-to-vector conversion.
    """

    def __init__(
        self,
        store: KnowledgeStore,
        graph: KnowledgeGraph,
        retriever: HybridRetriever,
        embedding_store: Optional[EmbeddingStore] = None,
        embedding_provider: Optional[EmbeddingProvider] = None,
    ) -> None:
        """Initialize the learning pipeline.

        :param store: Knowledge store.
        :param graph: Knowledge graph.
        :param retriever: Hybrid retriever for consolidation.
        :param embedding_store: Optional embedding store.
        :param embedding_provider: Optional embedding provider.
        """
        self._store = store
        self._graph = graph
        self._retriever = retriever
        self._embedding_store = embedding_store
        self._embedding_provider = embedding_provider

    def process_session(
        self,
        candidate: LearnedPattern,
        experience: ExperienceEntry,
        gaps: Optional[List[KnowledgeGap]] = None,
    ) -> LearnedPattern:
        """Run the full CBR Revise + Retain pipeline for a session.

        :param candidate: Extracted candidate pattern from triage results.
        :param experience: Session outcome record (used for Revise step).
        :param gaps: Optional knowledge gaps identified during triage.
        :returns: The stored (new or reinforced) learned pattern.
        """
        # Step 1: Consolidate (de-duplicate)
        pattern = self._consolidate(candidate)

        # Step 2: Revise (outcome-weighted confidence update)
        pattern = self._revise(pattern, experience)

        # Step 3: Store (SQLite + embedding)
        self._store.save_learned_pattern(pattern)
        self._embed(pattern)

        # Step 4: Link
        self._link(pattern)

        # Step 5: Log
        self._store.log_experience(experience)
        for gap in gaps or []:
            self._store.log_gap(gap)

        return pattern

    def _consolidate(self, candidate: LearnedPattern) -> LearnedPattern:
        """De-duplicate candidate against existing patterns.

        Uses keyword-based similarity from the retriever:
        - >= 0.95: near-duplicate → reinforce existing pattern.
        - 0.85–0.95: related → store as new with cross-reference.
        - < 0.85: novel → store as new pattern.

        :param candidate: Candidate pattern to consolidate.
        :returns: The pattern to store (reinforced existing or new).
        """
        search_text = " ".join([candidate.name, candidate.description] + candidate.symptoms)
        existing = self._retriever.search_learned_patterns(query=search_text, limit=5)

        if not existing:
            candidate_dict = candidate.model_dump()
            candidate_dict["confidence"] = _INITIAL_CONFIDENCE
            return LearnedPattern.model_validate(candidate_dict)

        best = existing[0]

        if best.relevance >= _NEAR_DUPLICATE_THRESHOLD:
            # Near-duplicate: reinforce existing pattern
            assert isinstance(best.item, LearnedPattern)
            return self._reinforce(best.item, candidate)

        if best.relevance >= _RELATED_THRESHOLD:
            # Related: store as new, cross-reference
            if best.item_id not in candidate.related_patterns:
                updated = candidate.model_dump()
                updated["related_patterns"] = candidate.related_patterns + [best.item_id]
                updated["confidence"] = _INITIAL_CONFIDENCE
                return LearnedPattern.model_validate(updated)

        # Novel: store with initial confidence
        candidate_dict = candidate.model_dump()
        candidate_dict["confidence"] = _INITIAL_CONFIDENCE
        return LearnedPattern.model_validate(candidate_dict)

    def _reinforce(
        self,
        existing: LearnedPattern,
        candidate: LearnedPattern,
    ) -> LearnedPattern:
        """Reinforce an existing pattern with new evidence.

        Bumps occurrence count, updates last_seen, and merges sessions.
        Confidence update is handled separately by :meth:`_revise`.

        :param existing: The existing pattern to reinforce.
        :param candidate: The new candidate with fresh session data.
        :returns: Updated learned pattern (confidence unchanged here).
        """
        now = datetime.now(timezone.utc)
        merged_sessions = list(set(existing.source_sessions + candidate.source_sessions))

        return LearnedPattern(
            id=existing.id,
            name=existing.name,
            description=existing.description,
            category=existing.category,
            symptoms=existing.symptoms,
            investigation=existing.investigation,
            root_cause=existing.root_cause,
            fixes=existing.fixes,
            related_patterns=list(set(existing.related_patterns + candidate.related_patterns)),
            tags=list(set(existing.tags + candidate.tags)),
            source="learned",
            confidence=existing.confidence,
            occurrence_count=existing.occurrence_count + 1,
            first_seen=existing.first_seen,
            last_seen=now,
            source_sessions=merged_sessions,
        )

    @staticmethod
    def _compute_boost(experience: ExperienceEntry) -> float:
        """Compute confidence adjustment from session outcome.

        Rules (Section 7.2.1 CBR Revise):
        - ``operator_feedback == "correct"`` + ``resolution_applied``: full boost.
        - ``root_cause_found`` but no resolution: half boost.
        - ``operator_feedback == "incorrect"``: penalty.
        - Otherwise: no change.

        :param experience: Session outcome record.
        :returns: Signed confidence delta.
        """
        if experience.operator_feedback == "correct" and experience.resolution_applied:
            return _BOOST_FULL
        if experience.root_cause_found:
            return _BOOST_HALF
        if experience.operator_feedback == "incorrect":
            return _PENALTY
        return 0.0

    def _revise(
        self,
        pattern: LearnedPattern,
        experience: ExperienceEntry,
    ) -> LearnedPattern:
        """CBR Revise: update confidence based on session outcome.

        :param pattern: Pattern after consolidation.
        :param experience: Session outcome with feedback fields.
        :returns: Pattern with revised confidence.
        """
        boost = self._compute_boost(experience)
        if boost == 0.0:
            return pattern

        new_confidence = max(0.0, min(1.0, pattern.confidence + boost))
        updated = pattern.model_dump()
        updated["confidence"] = new_confidence
        return LearnedPattern.model_validate(updated)

    def _embed(self, pattern: LearnedPattern) -> None:
        """Compute and persist an embedding for a learned pattern.

        No-op when ``embedding_store`` or ``embedding_provider`` is not
        configured. Failures are logged but do not break the pipeline.

        :param pattern: Pattern to embed.
        """
        if self._embedding_store is None or self._embedding_provider is None:
            return

        text = " ".join([pattern.name, pattern.description] + pattern.symptoms)
        text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()

        try:
            vector = self._embedding_provider.embed(text)
            self._embedding_store.store(
                item_id=pattern.id,
                item_type="learned_pattern",
                embedding=vector,
                text_hash=text_hash,
            )
        except Exception:
            _log.warning(
                "Failed to compute/store embedding for pattern %s",
                pattern.id,
                exc_info=True,
            )

    def apply_decay(self, patterns: List[LearnedPattern]) -> List[LearnedPattern]:
        """Apply age-based confidence decay to a batch of patterns.

        Confidence erodes at :data:`_DECAY_PER_MONTH` per 30-day period
        since ``last_seen``. Patterns that are actively reinforced reset
        their ``last_seen`` and therefore do not decay.

        Patterns that drop below :data:`_CONFIDENCE_FLOOR` are clamped
        to the floor rather than reaching zero.

        :param patterns: Patterns to potentially decay.
        :returns: Patterns with decayed confidence (only changed ones).
        """
        now = datetime.now(timezone.utc)
        decayed: List[LearnedPattern] = []

        for pattern in patterns:
            age_days = (now - pattern.last_seen).total_seconds() / 86400.0
            periods = age_days / _DECAY_PERIOD_DAYS
            if periods < 1.0:
                continue

            decay_amount = periods * _DECAY_PER_MONTH
            new_confidence = max(
                _CONFIDENCE_FLOOR,
                pattern.confidence - decay_amount,
            )
            if new_confidence < pattern.confidence:
                updated = pattern.model_dump()
                updated["confidence"] = round(new_confidence, 4)
                decayed.append(LearnedPattern.model_validate(updated))

        return decayed

    def _link(self, pattern: LearnedPattern) -> None:
        """Connect pattern to related patterns in the knowledge graph.

        :param pattern: Pattern to link.
        """
        for related_id in pattern.related_patterns:
            self._graph.add_edge(
                pattern.id,
                related_id,
                "related_to",
                strength=pattern.confidence,
            )
