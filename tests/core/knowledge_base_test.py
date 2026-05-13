# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for KnowledgeBase in-memory store."""

from __future__ import annotations
from pathlib import Path

import pytest
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
def kb(tmp_path: Path) -> KnowledgeBase:
    """Empty KnowledgeBase for testing."""
    seed = tmp_path / "seed"
    seed.mkdir()
    return KnowledgeBase(seed_dir=seed)


class TestLoadRules:
    """Tests for rule loading and filtering."""

    def test_load_rules_returns_all(self, kb: KnowledgeBase) -> None:
        kb.save_rule(Rule(id="R-1", name="rule one"))
        kb.save_rule(Rule(id="R-2", name="rule two"))
        assert len(kb.load_rules()) == 2

    def test_load_rules_filters_by_system(self, kb: KnowledgeBase) -> None:
        kb.save_rule(
            Rule(
                id="R-HANA",
                name="HANA rule",
                applicability=Applicability(database_type="HANA"),
            )
        )
        kb.save_rule(
            Rule(
                id="R-DB2",
                name="DB2 rule",
                applicability=Applicability(database_type="DB2"),
            )
        )
        system = SystemProperties(database_type="HANA")
        result = kb.load_rules(system=system)
        assert len(result) == 1
        assert result[0].id == "R-HANA"

    def test_load_rules_no_applicability_matches_all(self, kb: KnowledgeBase) -> None:
        kb.save_rule(Rule(id="R-ALL", name="universal"))
        system = SystemProperties(database_type="HANA")
        assert len(kb.load_rules(system=system)) == 1

    def test_save_rule_replaces_by_id(self, kb: KnowledgeBase) -> None:
        kb.save_rule(Rule(id="R-1", name="old"))
        kb.save_rule(Rule(id="R-1", name="new"))
        rules = kb.load_rules()
        assert len(rules) == 1
        assert rules[0].name == "new"


class TestLoadPlaybooks:
    def test_load_playbooks(self, kb: KnowledgeBase) -> None:
        kb.save_playbook(
            Playbook(
                id="PB-1",
                name="pb one",
                investigation=["step1"],
                root_cause="rc",
                fixes=["fix1"],
            )
        )
        assert len(kb.load_playbooks()) == 1

    def test_save_playbooks_bulk(self, kb: KnowledgeBase) -> None:
        pbs = [
            Playbook(id=f"PB-{i}", name=f"pb {i}", investigation=["s"], root_cause="r", fixes=["f"])
            for i in range(5)
        ]
        count = kb.save_playbooks(pbs)
        assert count == 5
        assert len(kb.load_playbooks()) == 5


class TestLoadReferences:
    def test_load_references(self, kb: KnowledgeBase) -> None:
        kb.save_reference(Reference(id="REF-1", title="ref one"))
        assert len(kb.load_references()) == 1

    def test_save_references_bulk(self, kb: KnowledgeBase) -> None:
        count = kb.save_references(
            [
                Reference(id="REF-1", title="a"),
                Reference(id="REF-2", title="b"),
            ]
        )
        assert count == 2


class TestEvidenceDefinitions:
    def test_load_evidence_definitions(self, kb: KnowledgeBase) -> None:
        kb.save_evidence_definition(
            EvidenceCollectorDef(
                id="EC-1",
                name="test",
            )
        )
        assert len(kb.load_evidence_definitions()) == 1

    def test_filter_by_os_family(self, kb: KnowledgeBase) -> None:
        kb.save_evidence_definition(
            EvidenceCollectorDef(
                id="EC-SUSE",
                name="suse only",
                os_family=["SUSE"],
            )
        )
        kb.save_evidence_definition(
            EvidenceCollectorDef(
                id="EC-ALL",
                name="all os",
            )
        )
        result = kb.load_evidence_definitions(os_family="SUSE")
        assert len(result) == 2

    def test_filter_excludes_wrong_os(self, kb: KnowledgeBase) -> None:
        kb.save_evidence_definition(
            EvidenceCollectorDef(
                id="EC-RHEL",
                name="rhel only",
                os_family=["REDHAT"],
            )
        )
        result = kb.load_evidence_definitions(os_family="SUSE")
        assert len(result) == 0


class TestLearnedPatterns:
    def test_load_learned_patterns(self, kb: KnowledgeBase) -> None:
        kb.save_learned_pattern(
            LearnedPattern(
                id="LP-1",
                name="pattern",
                confidence=0.8,
            )
        )
        assert len(kb.load_learned_patterns()) == 1

    def test_confidence_filter(self, kb: KnowledgeBase) -> None:
        kb.save_learned_pattern(
            LearnedPattern(
                id="LP-LOW",
                name="low",
                confidence=0.1,
            )
        )
        kb.save_learned_pattern(
            LearnedPattern(
                id="LP-HIGH",
                name="high",
                confidence=0.9,
            )
        )
        result = kb.load_learned_patterns(min_confidence=0.5)
        assert len(result) == 1
        assert result[0].id == "LP-HIGH"


class TestLoadFromJsonl:
    """Test loading from actual JSONL files."""

    def test_loads_rules_from_seed(self, tmp_path: Path) -> None:
        seed = tmp_path / "seed"
        rules_dir = seed / "rules"
        rules_dir.mkdir(parents=True)
        (rules_dir / "test.jsonl").write_text(
            '{"id": "R-1", "name": "test rule", "tags": ["hana"]}\n'
            '{"id": "R-2", "name": "another rule"}\n'
        )
        kb = KnowledgeBase(seed_dir=seed)
        assert len(kb.load_rules()) == 2

    def test_empty_seed_dir(self, tmp_path: Path) -> None:
        seed = tmp_path / "empty"
        seed.mkdir()
        kb = KnowledgeBase(seed_dir=seed)
        assert len(kb.load_rules()) == 0
        assert len(kb.load_playbooks()) == 0
