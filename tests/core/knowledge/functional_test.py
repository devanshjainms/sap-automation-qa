# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Functional tests: real seed data through the full knowledge pipeline.

These tests load actual JSONL files from ``src/core/knowledge/seed/``,
store them in real SQLite databases, and exercise the retrieval and
learning pipeline with realistic queries.  No mocks of core components.
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Generator

import pytest
from src.core.knowledge.loader import JsonlLoader
from src.core.knowledge.learning import LearningPipeline
from src.core.knowledge.retrieval import HybridRetriever
from src.core.models.knowledge import (
    ExperienceEntry,
    KnowledgeGap,
    LearnedPattern,
    Playbook,
    Reference,
    Rule,
)
from src.core.models.system import SystemProperties
from src.core.storage.knowledge_graph import KnowledgeGraph
from src.core.storage.knowledge_store import KnowledgeStore

SEED_DIR = Path(__file__).resolve().parents[3] / "src" / "core" / "knowledge" / "seed"


# ── Fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def store(tmp_path: Path) -> Generator[KnowledgeStore, None, None]:
    """KnowledgeStore backed by a temp database."""
    s = KnowledgeStore(db_path=tmp_path / "functional.db")
    yield s
    s.close()


@pytest.fixture
def graph() -> Generator[KnowledgeGraph, None, None]:
    """In-memory KnowledgeGraph."""
    g = KnowledgeGraph(db_path=":memory:")
    yield g
    g.close()


@pytest.fixture
def retriever(store: KnowledgeStore) -> HybridRetriever:
    """HybridRetriever wired to the real store."""
    return HybridRetriever(store)


@pytest.fixture
def pipeline(
    store: KnowledgeStore,
    graph: KnowledgeGraph,
    retriever: HybridRetriever,
) -> LearningPipeline:
    """Full LearningPipeline wired to real store + graph."""
    return LearningPipeline(store, graph, retriever)


def _load_all_seed(store: KnowledgeStore) -> tuple[int, int, int]:
    """Load all seed data into the store.

    :returns: ``(rules, playbooks, references)`` counts.
    """
    loader = JsonlLoader(SEED_DIR)

    rules = loader.load_directory("rules", Rule)
    store.save_rules(rules)

    playbooks = loader.load_directory("playbooks", Playbook)
    for pb in playbooks:
        store.save_playbook(pb)

    refs = loader.load_directory("references", Reference)
    for ref in refs:
        store.save_reference(ref)

    return len(rules), len(playbooks), len(refs)


# ── Seed loading ──────────────────────────────────────────────────


class TestSeedDataLoading:
    """Verify all seed JSONL files load through the full pipeline."""

    def test_all_seed_rules_load(self, store: KnowledgeStore) -> None:
        """Config rules + HA cluster constants all load."""
        n_rules, n_playbooks, n_refs = _load_all_seed(store)
        assert n_rules >= 700
        assert n_playbooks >= 5
        assert n_refs >= 7

    def test_seed_categories(self, store: KnowledgeStore) -> None:
        """Both config-check and ha_cluster categories present."""
        _load_all_seed(store)
        rules = store.load_rules()
        categories = {r.category for r in rules}
        assert "ha_cluster" in categories

    def test_seed_rules_have_validators(self, store: KnowledgeStore) -> None:
        """Most rules carry a validator spec."""
        _load_all_seed(store)
        rules = store.load_rules()
        with_val = [r for r in rules if r.validator is not None]
        assert len(with_val) >= 500

    def test_ha_db_rules_present(self, store: KnowledgeStore) -> None:
        """HA-DB-* rules from DB cluster constants are present."""
        _load_all_seed(store)
        rules = store.load_rules()
        ha_db = [r for r in rules if r.id.startswith("HA-DB-")]
        assert len(ha_db) >= 300

    def test_ha_scs_rules_present(self, store: KnowledgeStore) -> None:
        """HA-SCS-* rules from SCS cluster constants are present."""
        _load_all_seed(store)
        rules = store.load_rules()
        ha_scs = [r for r in rules if r.id.startswith("HA-SCS-")]
        assert len(ha_scs) >= 150

    def test_playbooks_have_symptoms(self, store: KnowledgeStore) -> None:
        """All seed playbooks have non-empty symptoms lists."""
        _load_all_seed(store)
        playbooks = store.load_playbooks()
        for pb in playbooks:
            assert len(pb.symptoms) > 0, f"Playbook {pb.id} has no symptoms"


# ── Applicability filtering ───────────────────────────────────────


class TestApplicabilityFiltering:
    """Verify rule filtering works with real seed data."""

    def test_hana_scale_up_suse_system(
        self,
        store: KnowledgeStore,
    ) -> None:
        """HANA Scale-Up SUSE system gets DB rules, not SCS rules."""
        _load_all_seed(store)
        system = SystemProperties(
            database_type="HANA",
            ha_enabled=True,
            hana_topology="scale_up",
            os_family="SUSE",
            hsr_provider="SAPHanaSR",
            instance_type="db",
        )
        rules = store.load_rules(system)
        ids = [r.id for r in rules]
        assert any(i.startswith("HA-DB-") for i in ids), "HANA system should get HA-DB rules"
        assert not any(
            i.startswith("HA-SCS-") for i in ids
        ), "HANA system should NOT get HA-SCS rules"

    def test_scs_system(self, store: KnowledgeStore) -> None:
        """SCS system gets SCS rules, not HANA-specific rules."""
        _load_all_seed(store)
        system = SystemProperties(
            ha_enabled=True,
            os_family="SUSE",
            instance_type="ascs",
            scs_type="ENSA2",
        )
        rules = store.load_rules(system)
        ids = [r.id for r in rules]
        assert any(i.startswith("HA-SCS-") for i in ids), "SCS system should get HA-SCS rules"
        assert not any(i.startswith("HA-DB-") for i in ids), "SCS system should NOT get HA-DB rules"
        assert not any(
            i.startswith("DB-HANA-") for i in ids
        ), "SCS system should NOT get DB-HANA rules"

    def test_redhat_system_excludes_suse_only(
        self,
        store: KnowledgeStore,
    ) -> None:
        """REDHAT system must not get SUSE-only resource rules."""
        _load_all_seed(store)
        system = SystemProperties(
            database_type="HANA",
            ha_enabled=True,
            hana_topology="scale_up",
            os_family="REDHAT",
            instance_type="db",
        )
        rules = store.load_rules(system)
        for r in rules:
            if r.applicability and r.applicability.os_family:
                assert "REDHAT" in r.applicability.os_family, (
                    f"Rule {r.id} has os_family {r.applicability.os_family} "
                    "but should be REDHAT-compatible"
                )

    def test_unfiltered_returns_all(self, store: KnowledgeStore) -> None:
        """No system filter returns the full rule set."""
        _load_all_seed(store)
        all_rules = store.load_rules()
        assert len(all_rules) >= 700


# ── End-to-end retrieval ──────────────────────────────────────────


class TestEndToEndRetrieval:
    """Test HybridRetriever against real seed data."""

    def test_search_rules_stonith(
        self,
        store: KnowledgeStore,
        retriever: HybridRetriever,
    ) -> None:
        """Keyword 'stonith' finds cluster stonith rules."""
        _load_all_seed(store)
        results = retriever.search_rules(query="stonith fencing enabled")
        names = [r.item.name for r in results]
        assert any("stonith" in n.lower() for n in names)

    def test_search_rules_hana_system_scoped(
        self,
        store: KnowledgeStore,
        retriever: HybridRetriever,
    ) -> None:
        """Search rules scoped to a HANA system."""
        _load_all_seed(store)
        system = SystemProperties(
            database_type="HANA",
            instance_type="db",
            os_family="SUSE",
        )
        results = retriever.search_rules(
            system=system,
            query="PREFER_SITE_TAKEOVER",
        )
        assert len(results) > 0
        ids = [r.item_id for r in results]
        assert not any(i.startswith("HA-SCS-") for i in ids)

    def test_search_playbooks_hsr(
        self,
        store: KnowledgeStore,
        retriever: HybridRetriever,
    ) -> None:
        """Searching 'HSR sync failure' finds HANA playbooks."""
        _load_all_seed(store)
        results = retriever.search_playbooks(
            query="HSR sync failure takeover",
        )
        assert len(results) > 0

    def test_search_playbooks_enqueue(
        self,
        store: KnowledgeStore,
        retriever: HybridRetriever,
    ) -> None:
        """Searching 'enqueue replication' finds SCS playbooks."""
        _load_all_seed(store)
        results = retriever.search_playbooks(
            query="enqueue replication server failure",
        )
        assert len(results) > 0

    def test_search_rules_crm_config(
        self,
        store: KnowledgeStore,
        retriever: HybridRetriever,
    ) -> None:
        """Searching 'cluster infrastructure corosync' finds CRM rules."""
        _load_all_seed(store)
        results = retriever.search_rules(
            query="cluster infrastructure corosync crm_config",
        )
        assert len(results) > 0


# ── Full CBR cycle ────────────────────────────────────────────────


class TestFullCBRCycle:
    """Test the complete CBR cycle: Retrieve → Revise → Retain."""

    def test_learn_and_retrieve_pattern(
        self,
        store: KnowledgeStore,
        graph: KnowledgeGraph,
        retriever: HybridRetriever,
        pipeline: LearningPipeline,
    ) -> None:
        """Learn a pattern through the pipeline and retrieve it."""
        _load_all_seed(store)

        candidate = LearnedPattern(
            id="LP-FUNC-001",
            name="Corosync token timeout too low",
            description=("Corosync token timeout was 5000ms causing " "false positive fencing"),
            category="ha_cluster",
            symptoms=["unexpected fencing", "corosync timeout"],
            root_cause="Corosync token below recommended 30000ms",
            fixes=["Set runtime.config.totem.token to 30000"],
            confidence=0.5,
        )
        experience = ExperienceEntry(
            session_id="sess-func-001",
            system_id="PRD-HANA-01",
            patterns_matched=["LP-FUNC-001"],
            root_cause_found=True,
            resolution_applied=True,
        )

        result = pipeline.process_session(candidate, experience)

        # Pattern was stored
        stored = store.get_learned_pattern("LP-FUNC-001")
        assert stored is not None
        assert stored.confidence > 0.0

        # Experience was logged
        exp = store.get_experience("sess-func-001")
        assert exp is not None

        # Pattern is retrievable
        hits = retriever.search_learned_patterns(
            query="corosync token timeout fencing",
        )
        found_ids = [h.item_id for h in hits]
        assert "LP-FUNC-001" in found_ids

    def test_positive_experience_boosts_confidence(
        self,
        store: KnowledgeStore,
        graph: KnowledgeGraph,
        retriever: HybridRetriever,
        pipeline: LearningPipeline,
    ) -> None:
        """Positive experience feedback boosts pattern confidence."""
        _load_all_seed(store)

        candidate = LearnedPattern(
            id="LP-FUNC-002",
            name="ANF throttling during backup",
            description="ANF volume throttled during HANA backup window",
            category="ha_cluster",
            symptoms=["ANF throttling", "IO latency spike"],
            confidence=0.3,
        )
        experience = ExperienceEntry(
            session_id="sess-func-002",
            system_id="PRD-HANA-01",
            patterns_matched=["LP-FUNC-002"],
            root_cause_found=True,
            resolution_applied=True,
        )

        result = pipeline.process_session(candidate, experience)
        assert result.confidence > 0.3

    def test_negative_experience_penalizes(
        self,
        store: KnowledgeStore,
        graph: KnowledgeGraph,
        retriever: HybridRetriever,
        pipeline: LearningPipeline,
    ) -> None:
        """Negative experience feedback lowers confidence."""
        _load_all_seed(store)

        candidate = LearnedPattern(
            id="LP-FUNC-003",
            name="Spurious fencing correlation",
            description="Incorrectly linked fencing to network issue",
            category="ha_cluster",
            symptoms=["fencing triggered"],
            confidence=0.6,
        )
        experience = ExperienceEntry(
            session_id="sess-func-003",
            system_id="PRD-HANA-01",
            patterns_matched=["LP-FUNC-003"],
            root_cause_found=False,
            resolution_applied=False,
        )

        result = pipeline.process_session(candidate, experience)
        assert result.confidence < 0.6

    def test_knowledge_gap_logged(
        self,
        store: KnowledgeStore,
        graph: KnowledgeGraph,
        retriever: HybridRetriever,
        pipeline: LearningPipeline,
    ) -> None:
        """Knowledge gaps are logged through the pipeline."""
        _load_all_seed(store)

        candidate = LearnedPattern(
            id="LP-FUNC-004",
            name="Unknown ANF behavior",
            description="No matching knowledge for ANF timeout pattern",
            category="ha_cluster",
        )
        experience = ExperienceEntry(
            session_id="sess-func-004",
            system_id="PRD-HANA-02",
            knowledge_gaps=["GAP-001"],
            root_cause_found=False,
        )
        gap = KnowledgeGap(
            id="GAP-001",
            description="No rule for ANF timeout > 120s",
            session_id="sess-func-004",
        )

        pipeline.process_session(candidate, experience, gaps=[gap])

        gaps = store.get_unresolved_gaps()
        assert any(g.id == "GAP-001" for g in gaps)


# ── Cross-component wiring ────────────────────────────────────────


class TestCrossComponentWiring:
    """Verify components work together end-to-end."""

    def test_graph_edges_from_learning(
        self,
        store: KnowledgeStore,
        graph: KnowledgeGraph,
        retriever: HybridRetriever,
        pipeline: LearningPipeline,
    ) -> None:
        """Learning pipeline creates graph edges between patterns."""
        _load_all_seed(store)

        # Create two related patterns.
        p1 = LearnedPattern(
            id="LP-GRAPH-001",
            name="Fencing timeout misconfiguration",
            description="stonith-timeout too low for Azure Fence Agent",
            category="ha_cluster",
            symptoms=["fencing timeout"],
        )
        e1 = ExperienceEntry(
            session_id="sess-graph-001",
            patterns_matched=["LP-GRAPH-001"],
            root_cause_found=True,
        )
        pipeline.process_session(p1, e1)

        p2 = LearnedPattern(
            id="LP-GRAPH-002",
            name="Fencing delay not configured",
            description="priority-fencing-delay missing in CRM config",
            category="ha_cluster",
            symptoms=["fencing race condition"],
            related_patterns=["LP-GRAPH-001"],
        )
        e2 = ExperienceEntry(
            session_id="sess-graph-002",
            patterns_matched=["LP-GRAPH-002"],
            root_cause_found=True,
        )
        pipeline.process_session(p2, e2)

        # Graph should have edges.
        related = graph.get_related("LP-GRAPH-002")
        targets = [
            r["target_id"] if r["source_id"] == "LP-GRAPH-002" else r["source_id"] for r in related
        ]
        assert "LP-GRAPH-001" in targets

    def test_seed_plus_learned_retrieval(
        self,
        store: KnowledgeStore,
        retriever: HybridRetriever,
        pipeline: LearningPipeline,
        graph: KnowledgeGraph,
    ) -> None:
        """Seed rules and learned patterns coexist in retrieval."""
        _load_all_seed(store)

        # Add a learned pattern.
        candidate = LearnedPattern(
            id="LP-MIX-001",
            name="SBD device health check failure",
            description="SBD device not responding on standby node",
            category="ha_cluster",
            symptoms=["SBD timeout", "node not fenced"],
        )
        experience = ExperienceEntry(
            session_id="sess-mix-001",
            patterns_matched=["LP-MIX-001"],
            root_cause_found=True,
        )
        pipeline.process_session(candidate, experience)

        # Search should return both seed rules and learned patterns.
        rule_results = retriever.search_rules(query="SBD stonith")
        pattern_results = retriever.search_learned_patterns(
            query="SBD device failure",
        )
        assert len(rule_results) > 0, "Should find SBD seed rules"
        assert len(pattern_results) > 0, "Should find learned SBD pattern"
