# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for HybridRetriever."""

import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List

import pytest
from src.core.knowledge.retrieval import (
    CONFIDENCE_EXCLUDE_THRESHOLD,
    CONFIDENCE_WARNING_THRESHOLD,
    HybridRetriever,
    ScoredResult,
    _RECENCY_HALF_LIFE_DAYS,
)
from src.core.knowledge.base import KnowledgeBase
from src.core.models.knowledge import (
    EvidenceCollectorDef,
    LearnedPattern,
    Playbook,
    Reference,
    Rule,
)
from src.core.models.system import Applicability, SystemProperties


@pytest.fixture
def store(tmp_path: Path) -> KnowledgeBase:
    """Create an empty KnowledgeBase for testing."""
    seed_dir = tmp_path / "empty_seed"
    seed_dir.mkdir()
    return KnowledgeBase(seed_dir=seed_dir)


@pytest.fixture
def retriever(store: KnowledgeBase) -> HybridRetriever:
    """Create a HybridRetriever with the given store."""
    return HybridRetriever(store)


class TestSearchRules:
    """Tests for rule search and scoring."""

    def test_search_returns_applicable_rules(
        self, store: KnowledgeBase, retriever: HybridRetriever
    ) -> None:
        """Verify rules are filtered by system applicability."""
        store.save_rule(
            Rule(
                id="R-HANA",
                name="HANA rule",
                applicability=Applicability(database_type="HANA"),
            )
        )
        store.save_rule(
            Rule(
                id="R-DB2",
                name="DB2 rule",
                applicability=Applicability(database_type="DB2"),
            )
        )

        results = retriever.search_rules(system=SystemProperties(database_type="HANA"))
        ids = {r.item_id for r in results}
        assert "R-HANA" in ids
        assert "R-DB2" not in ids

    def test_search_with_keyword(self, store: KnowledgeBase, retriever: HybridRetriever) -> None:
        """Verify keyword matching affects relevance score."""
        store.save_rule(Rule(id="R-1", name="HANA takeover", tags=["hana"]))
        store.save_rule(Rule(id="R-2", name="SCS migration", tags=["scs"]))

        results = retriever.search_rules(query="HANA takeover")
        assert results[0].item_id == "R-1"
        assert results[0].relevance > results[1].relevance

    def test_empty_query_matches_all(
        self, store: KnowledgeBase, retriever: HybridRetriever
    ) -> None:
        """Verify empty query returns all (relevance=1.0)."""
        store.save_rule(Rule(id="R-1", name="a"))
        store.save_rule(Rule(id="R-2", name="b"))
        results = retriever.search_rules(query="")
        assert len(results) == 2
        assert all(r.relevance == 1.0 for r in results)

    def test_limit(self, store: KnowledgeBase, retriever: HybridRetriever) -> None:
        """Verify limit parameter caps results."""
        for i in range(10):
            store.save_rule(Rule(id=f"R-{i}", name=f"rule {i}"))
        results = retriever.search_rules(limit=3)
        assert len(results) == 3


class TestSearchPlaybooks:
    """Tests for playbook search."""

    def test_search_playbooks_keyword(
        self, store: KnowledgeBase, retriever: HybridRetriever
    ) -> None:
        """Verify playbook keyword matching on symptoms."""
        store.save_playbook(
            Playbook(
                id="PB-1",
                name="HSR failure",
                symptoms=["Secondary in SOK"],
                investigation=["Check sync_state"],
                root_cause="test",
                fixes=["fix"],
            )
        )
        store.save_playbook(
            Playbook(
                id="PB-2",
                name="SCS failover",
                symptoms=["ASCS process down"],
                investigation=["sapcontrol"],
                root_cause="test",
                fixes=["fix"],
            )
        )

        results = retriever.search_playbooks(query="Secondary SOK")
        assert results[0].item_id == "PB-1"


class TestSearchLearnedPatterns:
    """Tests for learned pattern search with full scoring."""

    def test_excludes_low_confidence(
        self, store: KnowledgeBase, retriever: HybridRetriever
    ) -> None:
        """Verify patterns below CONFIDENCE_EXCLUDE_THRESHOLD are excluded."""
        store.save_learned_pattern(
            LearnedPattern(
                id="LP-LOW",
                name="low conf",
                confidence=0.1,
            )
        )
        store.save_learned_pattern(
            LearnedPattern(
                id="LP-OK",
                name="ok conf",
                confidence=0.5,
            )
        )
        results = retriever.search_learned_patterns()
        ids = {r.item_id for r in results}
        assert "LP-LOW" not in ids
        assert "LP-OK" in ids

    def test_flags_warning_confidence(
        self, store: KnowledgeBase, retriever: HybridRetriever
    ) -> None:
        """Verify low_confidence=True when < WARNING threshold."""
        store.save_learned_pattern(
            LearnedPattern(
                id="LP-WARN",
                name="warning",
                confidence=0.25,
            )
        )
        results = retriever.search_learned_patterns()
        assert len(results) == 1
        assert results[0].low_confidence is True

    def test_scoring_formula(self, store: KnowledgeBase, retriever: HybridRetriever) -> None:
        """Verify composite score formula."""
        store.save_learned_pattern(
            LearnedPattern(
                id="LP-1",
                name="throttling anf storage",
                confidence=0.8,
                symptoms=["io errors"],
                tags=["anf"],
            )
        )
        results = retriever.search_learned_patterns(query="throttling anf")
        assert len(results) == 1
        r = results[0]
        # score = 0.45 * relevance + 0.35 * 0.8 + 0.20 * recency
        # With near-zero age, recency ~ 1.0
        expected = 0.45 * r.relevance + 0.35 * 0.8 + 0.20 * r.recency
        assert abs(r.score - expected) < 1e-9


class TestKeywordRelevance:
    """Tests for the static _keyword_relevance method."""

    def test_full_match(self) -> None:
        """All query tokens found → 1.0."""
        score = HybridRetriever._keyword_relevance("hana takeover", ["hana", "takeover", "test"])
        assert score == 1.0

    def test_partial_match(self) -> None:
        """Only some tokens found → fraction."""
        score = HybridRetriever._keyword_relevance("hana cluster fencing", ["hana", "cluster"])
        assert abs(score - 2.0 / 3.0) < 1e-9

    def test_no_match(self) -> None:
        """No tokens found → 0.0."""
        score = HybridRetriever._keyword_relevance("xyz", ["abc", "def"])
        assert score == 0.0

    def test_empty_query(self) -> None:
        """Empty query → 1.0 (match all)."""
        assert HybridRetriever._keyword_relevance("", ["a"]) == 1.0

    def test_whitespace_query(self) -> None:
        """Whitespace-only query → 1.0."""
        assert HybridRetriever._keyword_relevance("   ", ["a"]) == 1.0


class TestRecencyScore:
    """Tests for the static _recency_score method."""

    def test_same_day(self) -> None:
        """Pattern seen just now → ~1.0."""
        now = datetime.now(timezone.utc)
        score = HybridRetriever._recency_score(now, now)
        assert abs(score - 1.0) < 1e-9

    def test_half_life(self) -> None:
        """Pattern seen 90 days ago → ~0.5."""
        now = datetime.now(timezone.utc)
        then = now - timedelta(days=90)
        score = HybridRetriever._recency_score(then, now)
        assert abs(score - 0.5) < 0.01

    def test_very_old(self) -> None:
        """Pattern seen 360 days ago → quite low."""
        now = datetime.now(timezone.utc)
        then = now - timedelta(days=360)
        score = HybridRetriever._recency_score(then, now)
        assert score < 0.1

    def test_naive_datetime(self) -> None:
        """Naive datetimes treated as UTC."""
        now = datetime(2024, 6, 1, 12, 0, 0)
        then = datetime(2024, 3, 3, 12, 0, 0)  # ~90 days
        score = HybridRetriever._recency_score(then, now)
        assert abs(score - 0.5) < 0.02


class TestSearchEvidenceDefinitions:
    """Tests for evidence definition search and scoring."""

    def test_keyword_ranking(self, store: KnowledgeBase, retriever: HybridRetriever) -> None:
        """Evidence definitions matching query keywords rank higher."""
        store.save_evidence_definition(
            EvidenceCollectorDef(
                id="EC-HANA-SR",
                name="hana_sr_attributes",
                description="SAP HANA system replication",
                command="SAPHanaSR-showAttr",
                tags=["hana", "hsr", "replication"],
            )
        )
        store.save_evidence_definition(
            EvidenceCollectorDef(
                id="EC-DF",
                name="filesystem_usage",
                description="Filesystem disk usage",
                command="df -hT",
                tags=["filesystem", "storage"],
            )
        )
        results = retriever.search_evidence_definitions(query="hana replication")
        assert results[0].item_id == "EC-HANA-SR"
        assert results[0].relevance > results[1].relevance

    def test_empty_query_returns_all(
        self, store: KnowledgeBase, retriever: HybridRetriever
    ) -> None:
        """Empty query returns all definitions with relevance=1.0."""
        store.save_evidence_definition(EvidenceCollectorDef(id="EC-1", name="a"))
        store.save_evidence_definition(EvidenceCollectorDef(id="EC-2", name="b"))
        results = retriever.search_evidence_definitions(query="")
        assert len(results) == 2
        assert all(r.relevance == 1.0 for r in results)

    def test_limit(self, store: KnowledgeBase, retriever: HybridRetriever) -> None:
        """Limit parameter caps results."""
        for i in range(10):
            store.save_evidence_definition(EvidenceCollectorDef(id=f"EC-{i}", name=f"def {i}"))
        results = retriever.search_evidence_definitions(limit=3)
        assert len(results) == 3

    def test_command_text_included_in_scoring(
        self, store: KnowledgeBase, retriever: HybridRetriever
    ) -> None:
        """The command field contributes to keyword matching."""
        store.save_evidence_definition(
            EvidenceCollectorDef(
                id="EC-CRM",
                name="cluster_status",
                command="crm_mon -1rR",
                tags=["pacemaker"],
            )
        )
        store.save_evidence_definition(
            EvidenceCollectorDef(
                id="EC-IP",
                name="network",
                command="ip addr show",
                tags=["network"],
            )
        )
        results = retriever.search_evidence_definitions(query="crm_mon pacemaker")
        assert results[0].item_id == "EC-CRM"


class TestSearchReferences:
    """Tests for reference search and category filtering."""

    def test_keyword_ranking(self, store: KnowledgeBase, retriever: HybridRetriever) -> None:
        """References matching query rank higher."""
        store.save_reference(
            Reference(
                id="REF-SBD",
                title="SBD Log",
                category="log_file",
                failure_classes=["FENCING_NOT_TRIGGERED"],
                summary="SBD fencing watchdog",
                tags=["sbd", "fencing"],
            )
        )
        store.save_reference(
            Reference(
                id="REF-NFS",
                title="NFS Config",
                category="azure_doc",
                summary="ANF NFS mount options",
                tags=["nfs", "anf"],
            )
        )
        results = retriever.search_references(query="fencing sbd watchdog")
        assert results[0].item_id == "REF-SBD"
        assert results[0].relevance > results[1].relevance

    def test_category_filter(self, store: KnowledgeBase, retriever: HybridRetriever) -> None:
        """Category filter restricts to matching references."""
        store.save_reference(Reference(id="LOG-1", title="Pacemaker Log", category="log_file"))
        store.save_reference(Reference(id="DOC-1", title="Azure Doc", category="azure_doc"))
        results = retriever.search_references(category="log_file")
        assert len(results) == 1
        assert results[0].item_id == "LOG-1"

    def test_empty_query_returns_all(
        self, store: KnowledgeBase, retriever: HybridRetriever
    ) -> None:
        """Empty query with no category returns all references."""
        store.save_reference(Reference(id="R-1", title="a"))
        store.save_reference(Reference(id="R-2", title="b"))
        results = retriever.search_references(query="")
        assert len(results) == 2

    def test_failure_classes_in_scoring(
        self, store: KnowledgeBase, retriever: HybridRetriever
    ) -> None:
        """failure_classes text contributes to keyword matching."""
        store.save_reference(
            Reference(
                id="REF-FENCE",
                title="Fence Agent Log",
                failure_classes=["FENCING_NOT_TRIGGERED", "AZURE_API_FAILURE"],
                summary="Azure fence agent log",
                tags=["azure", "fencing"],
            )
        )
        store.save_reference(
            Reference(
                id="REF-KERNEL",
                title="Kernel Messages",
                failure_classes=["NODE_CRASH", "NFS_TIMEOUT"],
                summary="Kernel ring buffer",
                tags=["kernel", "dmesg"],
            )
        )
        results = retriever.search_references(query="FENCING_NOT_TRIGGERED azure")
        assert results[0].item_id == "REF-FENCE"

    def test_limit(self, store: KnowledgeBase, retriever: HybridRetriever) -> None:
        """Limit parameter caps results."""
        for i in range(10):
            store.save_reference(Reference(id=f"R-{i}", title=f"ref {i}", category="log_file"))
        results = retriever.search_references(limit=5)
        assert len(results) == 5
