# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for KnowledgeGraph."""

from typing import Generator

import pytest
from src.core.storage.knowledge_graph import KnowledgeGraph


@pytest.fixture
def graph() -> Generator[KnowledgeGraph, None, None]:
    """Create an in-memory KnowledgeGraph."""
    g = KnowledgeGraph(db_path=":memory:")
    yield g
    g.close()


class TestKnowledgeGraphEdges:
    """Tests for edge creation and validation."""

    def test_add_edge(self, graph: KnowledgeGraph) -> None:
        """Verify basic edge creation."""
        graph.add_edge("A", "B", "causes", strength=0.9)
        edges = graph.get_all_edges("A")
        assert len(edges) == 1
        assert edges[0]["source_id"] == "A"
        assert edges[0]["target_id"] == "B"
        assert edges[0]["edge_type"] == "causes"
        assert abs(edges[0]["strength"] - 0.9) < 1e-9

    def test_add_edge_invalid_type(self, graph: KnowledgeGraph) -> None:
        """Verify rejection of unknown edge types."""
        with pytest.raises(ValueError, match="Invalid edge type"):
            graph.add_edge("A", "B", "unknown_type")

    def test_upsert_applies_ema(self, graph: KnowledgeGraph) -> None:
        """Verify EMA on duplicate edge insertion."""
        graph.add_edge("A", "B", "causes", strength=1.0)
        graph.add_edge("A", "B", "causes", strength=0.0)
        edges = graph.get_all_edges("A")
        # EMA: 0.3 * 0.0 + 0.7 * 1.0 = 0.7
        assert len(edges) == 1
        assert abs(edges[0]["strength"] - 0.7) < 1e-9

    def test_update_strength(self, graph: KnowledgeGraph) -> None:
        """Verify explicit strength update via EMA."""
        graph.add_edge("X", "Y", "related_to", strength=0.5)
        graph.update_strength("X", "Y", "related_to", 1.0)
        # EMA: 0.3 * 1.0 + 0.7 * 0.5 = 0.65
        edges = graph.get_all_edges("X")
        assert abs(edges[0]["strength"] - 0.65) < 1e-9

    def test_update_strength_nonexistent(self, graph: KnowledgeGraph) -> None:
        """Verify update on missing edge returns None."""
        result = graph.update_strength("A", "B", "causes", 0.5)
        assert result is None


class TestKnowledgeGraphQueries:
    """Tests for causal chain and relationship queries."""

    @pytest.fixture(autouse=True)
    def _seed_graph(self, graph: KnowledgeGraph) -> None:
        """Seed a small graph:

        A --causes--> B --causes--> C
        A --related_to--> D
        E --prerequisite--> A

        get_causes(X) returns edges where target_id=X (what causes X).
        get_effects(X) returns edges where source_id=X (what X causes).
        """
        graph.add_edge("A", "B", "causes", strength=0.9)
        graph.add_edge("B", "C", "causes", strength=0.8)
        graph.add_edge("A", "D", "related_to", strength=0.6)
        graph.add_edge("E", "A", "prerequisite", strength=0.7)

    def test_get_causes(self, graph: KnowledgeGraph) -> None:
        """Verify get_causes returns edges causing a pattern."""
        # B is caused by A (A --causes--> B)
        causes = graph.get_causes("B")
        source_ids = {e["source_id"] for e in causes}
        assert "A" in source_ids

    def test_get_effects(self, graph: KnowledgeGraph) -> None:
        """Verify get_effects returns what a pattern causes."""
        # A causes B (A --causes--> B)
        effects = graph.get_effects("A")
        target_ids = {e["target_id"] for e in effects}
        assert "B" in target_ids

    def test_get_related(self, graph: KnowledgeGraph) -> None:
        """Verify related query returns both directions."""
        related = graph.get_related("D")
        partner_ids = {e["source_id"] if e["target_id"] == "D" else e["target_id"] for e in related}
        assert "A" in partner_ids

    def test_get_prerequisites(self, graph: KnowledgeGraph) -> None:
        """Verify prerequisite query."""
        prereqs = graph.get_prerequisites("A")
        source_ids = {e["source_id"] for e in prereqs}
        assert "E" in source_ids

    def test_get_all_edges(self, graph: KnowledgeGraph) -> None:
        """Verify all_edges returns all edges for a pattern."""
        # A has: causes->B, related_to->D, and E->prerequisite->A
        edges = graph.get_all_edges("A")
        assert len(edges) == 3

    def test_get_causes_empty(self, graph: KnowledgeGraph) -> None:
        """Verify empty result for pattern with no incoming causes."""
        # A has no incoming "causes" edges
        assert graph.get_causes("A") == []

    def test_get_effects_empty(self, graph: KnowledgeGraph) -> None:
        """Verify empty result for pattern with no outgoing causes."""
        # C has no outgoing "causes" edges
        assert graph.get_effects("C") == []

    def test_edge_types_isolated(self, graph: KnowledgeGraph) -> None:
        """Verify causes query doesn't return related_to edges."""
        effects = graph.get_effects("A")
        types = {e["edge_type"] for e in effects}
        assert types == {"causes"}
