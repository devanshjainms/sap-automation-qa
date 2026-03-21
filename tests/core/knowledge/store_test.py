# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for KnowledgeStore."""

from pathlib import Path
from typing import Generator

import pytest
from src.core.storage.knowledge_store import KnowledgeStore
from src.core.models.knowledge import (
    ExperienceEntry,
    KnowledgeGap,
    LearnedPattern,
    Playbook,
    Reference,
    Rule,
    ValidatorSpec,
)
from src.core.models.system import Applicability, SystemProperties
from src.core.models.validators import ValidatorType


@pytest.fixture
def store(tmp_path: Path) -> Generator[KnowledgeStore, None, None]:
    """Create a KnowledgeStore backed by a temp database."""
    s = KnowledgeStore(db_path=tmp_path / "test_knowledge.db")
    yield s
    s.close()


class TestKnowledgeStoreRules:
    """Tests for rule CRUD and filtering."""

    def test_save_and_load_rule(self, store: KnowledgeStore) -> None:
        """Verify rule round-trip through SQLite."""
        rule = Rule(
            id="DB-HANA-0001",
            name="PREFER_SITE_TAKEOVER",
            description="Should be true",
            category="ha_check",
            severity="HIGH",
            tags=["hana", "hsr"],
        )
        store.save_rule(rule)
        rules = store.load_rules()
        assert len(rules) == 1
        assert rules[0].id == "DB-HANA-0001"
        assert rules[0].tags == ["hana", "hsr"]

    def test_save_rule_with_applicability(self, store: KnowledgeStore) -> None:
        """Verify applicability survives serialization."""
        rule = Rule(
            id="R-001",
            name="test",
            applicability=Applicability(
                database_type="HANA",
                ha_enabled=True,
                os_family=["SUSE", "REDHAT"],
            ),
        )
        store.save_rule(rule)
        loaded = store.get_rule("R-001")
        assert loaded is not None
        assert loaded.applicability is not None
        assert loaded.applicability.database_type == "HANA"

    def test_save_rule_with_validator(self, store: KnowledgeStore) -> None:
        """Verify validator spec survives serialization."""
        rule = Rule(
            id="R-002",
            name="test",
            validator=ValidatorSpec(
                type=ValidatorType.EXACT_MATCH,
                source="global_ini",
                parameter="PREFER_SITE_TAKEOVER",
                expected="true",
            ),
        )
        store.save_rule(rule)
        loaded = store.get_rule("R-002")
        assert loaded is not None
        assert loaded.validator is not None

    def test_load_rules_filters_by_system(self, store: KnowledgeStore) -> None:
        """Verify load_rules returns only applicable rules."""
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
        store.save_rule(Rule(id="R-ANY", name="Universal rule"))

        hana_system = SystemProperties(database_type="HANA")
        rules = store.load_rules(system=hana_system)
        rule_ids = {r.id for r in rules}
        assert "R-HANA" in rule_ids
        assert "R-ANY" in rule_ids
        assert "R-DB2" not in rule_ids

    def test_load_rules_no_filter(self, store: KnowledgeStore) -> None:
        """Verify load_rules without system returns all."""
        store.save_rule(Rule(id="R-1", name="a"))
        store.save_rule(Rule(id="R-2", name="b"))
        assert len(store.load_rules()) == 2

    def test_get_rule_not_found(self, store: KnowledgeStore) -> None:
        """Verify get_rule returns None for missing ID."""
        assert store.get_rule("MISSING") is None

    def test_save_rules_bulk(self, store: KnowledgeStore) -> None:
        """Verify bulk save of rules."""
        rules = [Rule(id=f"R-{i}", name=f"rule-{i}") for i in range(10)]
        count = store.save_rules(rules)
        assert count == 10
        assert len(store.load_rules()) == 10

    def test_upsert_rule(self, store: KnowledgeStore) -> None:
        """Verify save_rule replaces existing rule."""
        store.save_rule(Rule(id="R-1", name="original"))
        store.save_rule(Rule(id="R-1", name="updated"))
        rule = store.get_rule("R-1")
        assert rule is not None
        assert rule.name == "updated"


class TestKnowledgeStorePlaybooks:
    """Tests for playbook CRUD."""

    def test_save_and_load_playbook(self, store: KnowledgeStore) -> None:
        """Verify playbook round-trip."""
        pb = Playbook(
            id="PB-001",
            name="HSR takeover",
            symptoms=["Secondary in SOK"],
            investigation=["Check sync_state"],
            root_cause="PREFER_SITE_TAKEOVER disabled",
            fixes=["Set to true"],
            related_patterns=["DB-HANA-0001"],
            tags=["hana"],
        )
        store.save_playbook(pb)
        playbooks = store.load_playbooks()
        assert len(playbooks) == 1
        assert playbooks[0].symptoms == ["Secondary in SOK"]
        assert playbooks[0].related_patterns == ["DB-HANA-0001"]


class TestKnowledgeStoreReferences:
    """Tests for reference CRUD."""

    def test_save_and_load_reference(self, store: KnowledgeStore) -> None:
        """Verify reference round-trip."""
        ref = Reference(
            id="REF-001",
            title="SAP Note 2407186",
            url="https://launchpad.support.sap.com/#/notes/2407186",
            failure_classes=["hsr_takeover_failure"],
            tags=["hana"],
        )
        store.save_reference(ref)
        refs = store.load_references()
        assert len(refs) == 1
        assert refs[0].failure_classes == ["hsr_takeover_failure"]


class TestKnowledgeStoreLearnedPatterns:
    """Tests for learned pattern CRUD."""

    def test_save_and_load_pattern(self, store: KnowledgeStore) -> None:
        """Verify learned pattern round-trip."""
        pattern = LearnedPattern(
            id="LP-001",
            name="ANF throttling",
            confidence=0.72,
            occurrence_count=3,
            source_sessions=["s1", "s2", "s3"],
        )
        store.save_learned_pattern(pattern)
        patterns = store.load_learned_patterns()
        assert len(patterns) == 1
        assert patterns[0].confidence == 0.72
        assert len(patterns[0].source_sessions) == 3

    def test_load_with_min_confidence(self, store: KnowledgeStore) -> None:
        """Verify confidence threshold filtering."""
        store.save_learned_pattern(LearnedPattern(id="LP-HIGH", name="high", confidence=0.8))
        store.save_learned_pattern(LearnedPattern(id="LP-LOW", name="low", confidence=0.1))
        assert len(store.load_learned_patterns(min_confidence=0.5)) == 1
        assert len(store.load_learned_patterns(min_confidence=0.0)) == 2

    def test_get_learned_pattern(self, store: KnowledgeStore) -> None:
        """Verify get by ID."""
        store.save_learned_pattern(LearnedPattern(id="LP-001", name="test"))
        p = store.get_learned_pattern("LP-001")
        assert p is not None
        assert p.name == "test"

    def test_get_learned_pattern_not_found(self, store: KnowledgeStore) -> None:
        """Verify get returns None for missing ID."""
        assert store.get_learned_pattern("MISSING") is None


class TestKnowledgeStoreExperience:
    """Tests for experience entry logging."""

    def test_log_and_get_experience(self, store: KnowledgeStore) -> None:
        """Verify experience entry round-trip."""
        entry = ExperienceEntry(
            session_id="sess-001",
            system_id="PRD-HANA-01",
            trigger="ha_failover_test",
            duration_seconds=342,
            patterns_matched=["PB-001"],
            rules_fired=47,
            rules_failed=3,
            root_cause_found=True,
            resolution_applied=True,
            operator_feedback="correct",
        )
        store.log_experience(entry)
        loaded = store.get_experience("sess-001")
        assert loaded is not None
        assert loaded.system_id == "PRD-HANA-01"
        assert loaded.root_cause_found is True
        assert loaded.rules_fired == 47

    def test_get_experience_not_found(self, store: KnowledgeStore) -> None:
        """Verify None for missing session."""
        assert store.get_experience("MISSING") is None


class TestKnowledgeStoreGaps:
    """Tests for knowledge gap logging."""

    def test_log_and_get_gaps(self, store: KnowledgeStore) -> None:
        """Verify gap round-trip and unresolved query."""
        store.log_gap(
            KnowledgeGap(
                id="GAP-001",
                description="Missing DB2 rule",
                session_id="sess-1",
            )
        )
        store.log_gap(
            KnowledgeGap(
                id="GAP-002",
                description="Missing ASE rule",
                session_id="sess-2",
            )
        )
        gaps = store.get_unresolved_gaps()
        assert len(gaps) == 2

    def test_resolve_gap(self, store: KnowledgeStore) -> None:
        """Verify gap resolution."""
        store.log_gap(
            KnowledgeGap(
                id="GAP-001",
                description="test",
                session_id="sess-1",
            )
        )
        assert store.resolve_gap("GAP-001") is True
        assert len(store.get_unresolved_gaps()) == 0

    def test_resolve_nonexistent_gap(self, store: KnowledgeStore) -> None:
        """Verify resolve returns False for missing gap."""
        assert store.resolve_gap("MISSING") is False
