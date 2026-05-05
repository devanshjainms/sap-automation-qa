# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for LearningPipeline (CBR Revise + Retain)."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Generator, List
from pytest_mock import MockerFixture

import pytest
from src.core.storage.knowledge_graph import KnowledgeGraph
from src.core.knowledge.learning import (
    LearningPipeline,
    _BOOST_FULL,
    _BOOST_HALF,
    _CONFIDENCE_FLOOR,
    _DECAY_PER_MONTH,
    _INITIAL_CONFIDENCE,
    _NEAR_DUPLICATE_THRESHOLD,
    _PENALTY,
    _RELATED_THRESHOLD,
)
from src.core.knowledge.retrieval import HybridRetriever
from src.core.storage.knowledge_store import KnowledgeStore
from src.core.models.knowledge import (
    ExperienceEntry,
    KnowledgeGap,
    LearnedPattern,
)


@pytest.fixture
def store(tmp_path: Path) -> Generator[KnowledgeStore, None, None]:
    """Create a KnowledgeStore backed by a temp database."""
    s = KnowledgeStore(db_path=tmp_path / "test_learning.db")
    yield s
    s.close()


@pytest.fixture
def graph() -> Generator[KnowledgeGraph, None, None]:
    """Create an in-memory KnowledgeGraph."""
    g = KnowledgeGraph(db_path=":memory:")
    yield g
    g.close()


@pytest.fixture
def retriever(store: KnowledgeStore) -> HybridRetriever:
    """Create a HybridRetriever with the given store."""
    return HybridRetriever(store)


@pytest.fixture
def pipeline(
    store: KnowledgeStore,
    graph: KnowledgeGraph,
    retriever: HybridRetriever,
) -> LearningPipeline:
    """Create a LearningPipeline wired to all dependencies."""
    return LearningPipeline(store, graph, retriever)


def _make_candidate(
    id: str = "LP-NEW",
    name: str = "ANF throttling",
    description: str = "Storage throttling on ANF volumes",
    symptoms: list[str] | None = None,
    source_sessions: list[str] | None = None,
    confidence: float = 0.0,
) -> LearnedPattern:
    """Build a candidate pattern with sensible defaults."""
    return LearnedPattern(
        id=id,
        name=name,
        description=description,
        symptoms=symptoms if symptoms is not None else ["io errors", "latency spike"],
        source_sessions=(source_sessions if source_sessions is not None else ["sess-new"]),
        confidence=confidence,
    )


def _make_experience(
    session_id: str = "sess-new",
    system_id: str = "PRD-HANA-01",
    trigger: str = "ha_failover_test",
    operator_feedback: str | None = None,
    root_cause_found: bool = False,
    resolution_applied: bool = False,
) -> ExperienceEntry:
    """Build an ExperienceEntry with optional feedback fields."""
    return ExperienceEntry(
        session_id=session_id,
        system_id=system_id,
        trigger=trigger,
        operator_feedback=operator_feedback,
        root_cause_found=root_cause_found,
        resolution_applied=resolution_applied,
    )


class _FakeProvider:
    """Minimal EmbeddingProvider for testing."""

    def __init__(self, dims: int = 4) -> None:
        self._dims = dims

    @property
    def dimensions(self) -> int:
        return self._dims

    def embed(self, text: str) -> List[float]:
        return [0.1] * self._dims

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        return [[0.1] * self._dims for _ in texts]


class _FailingProvider(_FakeProvider):
    """Provider that always raises on embed()."""

    def embed(self, text: str) -> List[float]:
        raise RuntimeError("embedding service unavailable")


class TestProcessSessionNovel:
    """Tests for the full pipeline when candidate is novel."""

    def test_novel_pattern_stored(self, pipeline: LearningPipeline, store: KnowledgeStore) -> None:
        """Verify novel candidate gets initial confidence and is stored."""
        candidate = _make_candidate()
        experience = _make_experience()

        result = pipeline.process_session(candidate, experience)
        assert result.confidence == _INITIAL_CONFIDENCE

        loaded = store.get_learned_pattern("LP-NEW")
        assert loaded is not None
        assert loaded.confidence == _INITIAL_CONFIDENCE

    def test_experience_logged(self, pipeline: LearningPipeline, store: KnowledgeStore) -> None:
        """Verify experience entry is logged."""
        pipeline.process_session(_make_candidate(), _make_experience())
        assert store.get_experience("sess-new") is not None

    def test_gaps_logged(self, pipeline: LearningPipeline, store: KnowledgeStore) -> None:
        """Verify gaps are logged."""
        gaps = [
            KnowledgeGap(
                id="GAP-1",
                description="Missing DB2 rules",
                session_id="sess-new",
            ),
        ]
        pipeline.process_session(_make_candidate(), _make_experience(), gaps=gaps)
        assert len(store.get_unresolved_gaps()) == 1


class TestConsolidateNearDuplicate:
    """Tests for near-duplicate consolidation."""

    def test_reinforce_existing_pattern(
        self,
        pipeline: LearningPipeline,
        store: KnowledgeStore,
    ) -> None:
        """Verify near-duplicate reinforces existing pattern."""
        existing = LearnedPattern(
            id="LP-EXIST",
            name="ANF throttling",
            description="Storage throttling on ANF volumes",
            symptoms=["io errors", "latency spike"],
            confidence=0.5,
            occurrence_count=3,
            source_sessions=["sess-1", "sess-2", "sess-3"],
        )
        store.save_learned_pattern(existing)

        candidate = _make_candidate(
            id="LP-EXIST",
            name="ANF throttling",
            description="Storage throttling on ANF volumes",
            symptoms=["io errors", "latency spike"],
            source_sessions=["sess-new"],
        )
        experience = _make_experience()

        result = pipeline.process_session(candidate, experience)
        loaded = store.get_learned_pattern("LP-EXIST")
        assert loaded is not None
        assert loaded.confidence >= existing.confidence


class TestConsolidateRelated:
    """Tests for related pattern cross-referencing."""

    def test_related_adds_cross_reference(
        self,
        pipeline: LearningPipeline,
        store: KnowledgeStore,
    ) -> None:
        """Verify related pattern gets cross-reference in related_patterns."""
        store.save_learned_pattern(
            LearnedPattern(
                id="LP-RELATED",
                name="ANF performance degradation",
                description="ANF performance issues",
                symptoms=["slow io"],
                confidence=0.6,
            )
        )

        candidate = _make_candidate(
            name="ANF throttling new variant",
            description="Different variant of ANF issues",
            symptoms=["io errors"],
        )

        result = pipeline.process_session(candidate, _make_experience())
        assert store.get_learned_pattern(result.id) is not None


class TestReinforce:
    """Tests for the _reinforce method directly."""

    def test_occurrence_increment(self, pipeline: LearningPipeline) -> None:
        """Verify occurrence_count is incremented."""
        existing = LearnedPattern(
            id="LP-1",
            name="test",
            occurrence_count=5,
            source_sessions=["s1"],
        )
        candidate = LearnedPattern(
            id="LP-1",
            name="test",
            source_sessions=["s2"],
        )
        result = pipeline._reinforce(existing, candidate)
        assert result.occurrence_count == 6

    def test_sessions_merged(self, pipeline: LearningPipeline) -> None:
        """Verify source sessions are merged (deduplicated)."""
        existing = LearnedPattern(
            id="LP-1",
            name="test",
            source_sessions=["s1", "s2"],
        )
        candidate = LearnedPattern(
            id="LP-1",
            name="test",
            source_sessions=["s2", "s3"],
        )
        result = pipeline._reinforce(existing, candidate)
        assert set(result.source_sessions) == {"s1", "s2", "s3"}

    def test_confidence_not_changed_by_reinforce(self, pipeline: LearningPipeline) -> None:
        """Verify _reinforce does not alter confidence (Revise handles it)."""
        existing = LearnedPattern(
            id="LP-1",
            name="test",
            confidence=0.5,
            source_sessions=["s1"],
        )
        candidate = LearnedPattern(
            id="LP-1",
            name="test",
            source_sessions=["s2"],
        )
        result = pipeline._reinforce(existing, candidate)
        assert result.confidence == 0.5


class TestRevise:
    """Tests for outcome-weighted confidence update (CBR Revise)."""

    def test_full_boost_on_correct_and_resolved(self, pipeline: LearningPipeline) -> None:
        """correct feedback + resolution_applied = full boost."""
        pattern = _make_candidate(confidence=0.3)
        experience = _make_experience(operator_feedback="correct", resolution_applied=True)
        result = pipeline._revise(pattern, experience)
        assert abs(result.confidence - (0.3 + _BOOST_FULL)) < 1e-9

    def test_half_boost_on_root_cause_only(self, pipeline: LearningPipeline) -> None:
        """root_cause_found without resolution = half boost."""
        pattern = _make_candidate(confidence=0.3)
        experience = _make_experience(root_cause_found=True)
        result = pipeline._revise(pattern, experience)
        assert abs(result.confidence - (0.3 + _BOOST_HALF)) < 1e-9

    def test_penalty_on_incorrect(self, pipeline: LearningPipeline) -> None:
        """incorrect feedback = negative penalty."""
        pattern = _make_candidate(confidence=0.3)
        experience = _make_experience(operator_feedback="incorrect")
        result = pipeline._revise(pattern, experience)
        assert abs(result.confidence - (0.3 + _PENALTY)) < 1e-9

    def test_no_change_on_no_feedback(self, pipeline: LearningPipeline) -> None:
        """No feedback = no confidence change."""
        pattern = _make_candidate(confidence=0.5)
        experience = _make_experience()
        result = pipeline._revise(pattern, experience)
        assert result.confidence == 0.5

    def test_confidence_capped_at_one(self, pipeline: LearningPipeline) -> None:
        """Verify confidence never exceeds 1.0."""
        pattern = _make_candidate(confidence=0.95)
        experience = _make_experience(operator_feedback="correct", resolution_applied=True)
        result = pipeline._revise(pattern, experience)
        assert result.confidence <= 1.0

    def test_confidence_floored_at_zero(self, pipeline: LearningPipeline) -> None:
        """Verify confidence never goes below 0.0."""
        pattern = _make_candidate(confidence=0.02)
        experience = _make_experience(operator_feedback="incorrect")
        result = pipeline._revise(pattern, experience)
        assert result.confidence >= 0.0

    def test_full_pipeline_applies_revise(
        self,
        pipeline: LearningPipeline,
        store: KnowledgeStore,
    ) -> None:
        """Verify process_session applies Revise step end-to-end."""
        candidate = _make_candidate()
        experience = _make_experience(operator_feedback="correct", resolution_applied=True)
        result = pipeline.process_session(candidate, experience)
        expected = _INITIAL_CONFIDENCE + _BOOST_FULL
        assert abs(result.confidence - expected) < 1e-9

        loaded = store.get_learned_pattern("LP-NEW")
        assert loaded is not None
        assert abs(loaded.confidence - expected) < 1e-9


class TestApplyDecay:
    """Tests for age-based confidence decay."""

    def test_no_decay_for_recent_pattern(self, pipeline: LearningPipeline) -> None:
        """Pattern seen within 30 days should not decay."""
        pattern = LearnedPattern(
            id="LP-1",
            name="recent",
            confidence=0.5,
            last_seen=datetime.now(timezone.utc) - timedelta(days=15),
        )
        decayed = pipeline.apply_decay([pattern])
        assert decayed == []

    def test_decay_after_one_period(self, pipeline: LearningPipeline) -> None:
        """Pattern 45 days old should lose ~1.5 periods * DECAY_PER_MONTH."""
        pattern = LearnedPattern(
            id="LP-1",
            name="stale",
            confidence=0.5,
            last_seen=datetime.now(timezone.utc) - timedelta(days=45),
        )
        decayed = pipeline.apply_decay([pattern])
        assert len(decayed) == 1
        assert decayed[0].confidence < 0.5

    def test_decay_respects_floor(self, pipeline: LearningPipeline) -> None:
        """Confidence should never drop below CONFIDENCE_FLOOR."""
        pattern = LearnedPattern(
            id="LP-1",
            name="ancient",
            confidence=0.1,
            last_seen=datetime.now(timezone.utc) - timedelta(days=365),
        )
        decayed = pipeline.apply_decay([pattern])
        assert len(decayed) == 1
        assert decayed[0].confidence >= _CONFIDENCE_FLOOR

    def test_decay_only_returns_changed(self, pipeline: LearningPipeline) -> None:
        """Only patterns that actually decayed are returned."""
        recent = LearnedPattern(
            id="LP-1",
            name="recent",
            confidence=0.5,
            last_seen=datetime.now(timezone.utc) - timedelta(days=10),
        )
        old = LearnedPattern(
            id="LP-2",
            name="old",
            confidence=0.5,
            last_seen=datetime.now(timezone.utc) - timedelta(days=90),
        )
        decayed = pipeline.apply_decay([recent, old])
        assert len(decayed) == 1
        assert decayed[0].id == "LP-2"


class TestEmbed:
    """Tests for embedding computation during Retain step."""

    def test_embed_called_when_provider_configured(
        self,
        store: KnowledgeStore,
        graph: KnowledgeGraph,
        retriever: HybridRetriever,
        mocker: MockerFixture,
    ) -> None:
        """Verify embedding is stored when provider + store are present."""
        mock_emb_store = mocker.MagicMock()
        provider = _FakeProvider(dims=4)
        pl = LearningPipeline(
            store,
            graph,
            retriever,
            embedding_store=mock_emb_store,
            embedding_provider=provider,
        )
        pattern = _make_candidate()
        pl._embed(pattern)
        mock_emb_store.store.assert_called_once()
        call_kwargs = mock_emb_store.store.call_args
        assert call_kwargs[1]["item_id"] == "LP-NEW"
        assert call_kwargs[1]["item_type"] == "learned_pattern"

    def test_embed_noop_without_provider(
        self, pipeline: LearningPipeline, mocker: MockerFixture
    ) -> None:
        """Verify _embed is a no-op when no provider is configured."""
        pattern = _make_candidate()
        # Should not raise
        pipeline._embed(pattern)

    def test_embed_failure_does_not_break_pipeline(
        self,
        store: KnowledgeStore,
        graph: KnowledgeGraph,
        retriever: HybridRetriever,
        mocker: MockerFixture,
    ) -> None:
        """Verify provider failure is logged but pipeline continues."""
        mock_emb_store = mocker.MagicMock()
        provider = _FailingProvider(dims=4)
        pl = LearningPipeline(
            store,
            graph,
            retriever,
            embedding_store=mock_emb_store,
            embedding_provider=provider,
        )
        candidate = _make_candidate()
        experience = _make_experience()
        # Should not raise
        result = pl.process_session(candidate, experience)
        assert result is not None
        # store.store should NOT have been called (provider failed)
        mock_emb_store.store.assert_not_called()

    def test_embed_computes_text_hash(
        self,
        store: KnowledgeStore,
        graph: KnowledgeGraph,
        retriever: HybridRetriever,
        mocker: MockerFixture,
    ) -> None:
        """Verify text_hash is a SHA-256 of the pattern text."""
        import hashlib

        mock_emb_store = mocker.MagicMock()
        provider = _FakeProvider(dims=4)
        pl = LearningPipeline(
            store,
            graph,
            retriever,
            embedding_store=mock_emb_store,
            embedding_provider=provider,
        )
        pattern = _make_candidate(
            name="foo",
            description="bar",
            symptoms=["baz"],
        )
        pl._embed(pattern)
        expected_hash = hashlib.sha256("foo bar baz".encode("utf-8")).hexdigest()
        call_kwargs = mock_emb_store.store.call_args[1]
        assert call_kwargs["text_hash"] == expected_hash


# ─── Graph linking tests ──────────────────────────────────────


class TestLink:
    """Tests for graph linking."""

    def test_link_creates_graph_edges(
        self,
        pipeline: LearningPipeline,
        graph: KnowledgeGraph,
    ) -> None:
        """Verify _link creates related_to edges in graph."""
        pattern = LearnedPattern(
            id="LP-1",
            name="test",
            related_patterns=["LP-A", "LP-B"],
            confidence=0.7,
        )
        pipeline._link(pattern)

        edges = graph.get_related("LP-1")
        target_ids = {e["target_id"] if e["source_id"] == "LP-1" else e["source_id"] for e in edges}
        assert "LP-A" in target_ids
        assert "LP-B" in target_ids

    def test_link_no_related(
        self,
        pipeline: LearningPipeline,
        graph: KnowledgeGraph,
    ) -> None:
        """Verify _link with empty related_patterns creates no edges."""
        pattern = LearnedPattern(id="LP-1", name="test")
        pipeline._link(pattern)
        assert graph.get_all_edges("LP-1") == []
