# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
In-memory knowledge base loaded from JSONL seed files.
All data is loaded once at startup from JSONL files and held in memory.
"""

from __future__ import annotations
import logging
from pathlib import Path
from typing import List, Optional
from src.core.knowledge.loader import JsonlLoader
from src.core.models.knowledge import (
    EvidenceCollectorDef,
    LearnedPattern,
    Playbook,
    Reference,
    Rule,
)
from src.core.models.system import SystemProperties

logger = logging.getLogger(__name__)


class KnowledgeBase:
    """
    In-memory knowledge base backed by JSONL seed files.

    :param seed_dir: Path to the seed data directory containing
        ``rules/``, ``playbooks/``, ``references/``, ``evidence/``
        subdirectories with ``.jsonl`` files.
    """

    def __init__(self, seed_dir: Path | str) -> None:
        self._seed_dir = Path(seed_dir)
        self._rules: List[Rule] = []
        self._playbooks: List[Playbook] = []
        self._references: List[Reference] = []
        self._evidence_defs: List[EvidenceCollectorDef] = []
        self._learned_patterns: List[LearnedPattern] = []
        self._load()

    def _load(self) -> None:
        """Load all seed data from JSONL files."""
        loader = JsonlLoader(base_dir=self._seed_dir)

        self._rules = loader.load_directory("rules", Rule)
        logger.info("Loaded %d rules", len(self._rules))

        self._playbooks = loader.load_directory("playbooks", Playbook)
        logger.info("Loaded %d playbooks", len(self._playbooks))

        self._references = loader.load_directory("references", Reference)
        logger.info("Loaded %d references", len(self._references))

        self._evidence_defs = loader.load_directory("evidence", EvidenceCollectorDef)
        logger.info("Loaded %d evidence definitions", len(self._evidence_defs))

    def load_rules(
        self,
        system: Optional[SystemProperties] = None,
    ) -> List[Rule]:
        """Return rules, optionally filtered by system applicability.

        :param system: If provided, only return applicable rules.
        :returns: List of matching rules.
        """
        if system is None:
            return list(self._rules)
        return [r for r in self._rules if self._rule_matches(r, system)]

    def load_playbooks(self) -> List[Playbook]:
        """Return all playbooks."""
        return list(self._playbooks)

    def load_references(self) -> List[Reference]:
        """Return all references."""
        return list(self._references)

    def load_evidence_definitions(
        self,
        os_family: Optional[str] = None,
    ) -> List[EvidenceCollectorDef]:
        """Return evidence definitions, optionally filtered by OS family.

        :param os_family: If provided, filter by OS (e.g. ``SUSE``).
        :returns: List of matching definitions.
        """
        if os_family is None:
            return list(self._evidence_defs)
        upper = os_family.upper()
        return [
            d
            for d in self._evidence_defs
            if not d.os_family or upper in [f.upper() for f in d.os_family]
        ]

    def load_learned_patterns(
        self,
        min_confidence: float = 0.0,
    ) -> List[LearnedPattern]:
        """Return learned patterns above a confidence threshold.

        :param min_confidence: Minimum confidence score.
        :returns: List of matching patterns.
        """
        return [p for p in self._learned_patterns if p.confidence >= min_confidence]

    @staticmethod
    def _rule_matches(rule: Rule, system: SystemProperties) -> bool:
        """Check if a rule applies to the given system."""
        if rule.applicability is None:
            return True
        return rule.applicability.matches(system)

    def save_rule(self, rule: Rule) -> None:
        """Add or replace a rule in memory."""
        self._rules = [r for r in self._rules if r.id != rule.id]
        self._rules.append(rule)

    def save_rules(self, rules: List[Rule]) -> int:
        """Bulk-add rules."""
        for r in rules:
            self.save_rule(r)
        return len(rules)

    def save_playbook(self, playbook: Playbook) -> None:
        """Add or replace a playbook in memory."""
        self._playbooks = [p for p in self._playbooks if p.id != playbook.id]
        self._playbooks.append(playbook)

    def save_playbooks(self, playbooks: List[Playbook]) -> int:
        """Bulk-add playbooks."""
        for p in playbooks:
            self.save_playbook(p)
        return len(playbooks)

    def save_reference(self, reference: Reference) -> None:
        """Add or replace a reference in memory."""
        self._references = [r for r in self._references if r.id != reference.id]
        self._references.append(reference)

    def save_references(self, references: List[Reference]) -> int:
        """Bulk-add references."""
        for r in references:
            self.save_reference(r)
        return len(references)

    def save_evidence_definition(self, definition: EvidenceCollectorDef) -> None:
        """Add or replace an evidence definition in memory."""
        self._evidence_defs = [d for d in self._evidence_defs if d.id != definition.id]
        self._evidence_defs.append(definition)

    def save_evidence_definitions(self, definitions: List[EvidenceCollectorDef]) -> int:
        """Bulk-add evidence definitions."""
        for d in definitions:
            self.save_evidence_definition(d)
        return len(definitions)

    def save_learned_pattern(self, pattern: LearnedPattern) -> None:
        """Add or replace a learned pattern in memory."""
        self._learned_patterns = [p for p in self._learned_patterns if p.id != pattern.id]
        self._learned_patterns.append(pattern)
