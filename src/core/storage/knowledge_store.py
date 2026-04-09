# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""SQLite-backed storage for knowledge: rules, playbooks, references,
learned patterns, experience entries, and knowledge gaps."""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from src.core.models.knowledge import (
    EvidenceCollectorDef,
    ExperienceEntry,
    KnowledgeGap,
    LearnedPattern,
    Playbook,
    Reference,
    Rule,
)
from src.core.models.system import Applicability, SystemProperties
from src.core.storage.staf_store import StafStore

KNOWLEDGE_SCHEMA = """
CREATE TABLE IF NOT EXISTS rules (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    description   TEXT NOT NULL DEFAULT '',
    category      TEXT NOT NULL DEFAULT '',
    severity      TEXT NOT NULL DEFAULT 'MEDIUM',
    applicability TEXT NOT NULL DEFAULT '{}',
    validator     TEXT,
    "references"  TEXT NOT NULL DEFAULT '[]',
    tags          TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS playbooks (
    id               TEXT PRIMARY KEY,
    name             TEXT NOT NULL,
    description      TEXT NOT NULL DEFAULT '',
    category         TEXT NOT NULL DEFAULT '',
    symptoms         TEXT NOT NULL DEFAULT '[]',
    investigation    TEXT NOT NULL DEFAULT '[]',
    root_cause       TEXT NOT NULL DEFAULT '',
    fixes            TEXT NOT NULL DEFAULT '[]',
    related_patterns TEXT NOT NULL DEFAULT '[]',
    tags             TEXT NOT NULL DEFAULT '[]',
    source           TEXT NOT NULL DEFAULT 'seed'
);

CREATE TABLE IF NOT EXISTS "references" (
    id              TEXT PRIMARY KEY,
    title           TEXT NOT NULL,
    url             TEXT NOT NULL DEFAULT '',
    category        TEXT NOT NULL DEFAULT '',
    failure_classes TEXT NOT NULL DEFAULT '[]',
    summary         TEXT NOT NULL DEFAULT '',
    tags            TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS learned_patterns (
    id                TEXT PRIMARY KEY,
    name              TEXT NOT NULL,
    description       TEXT NOT NULL DEFAULT '',
    category          TEXT NOT NULL DEFAULT '',
    symptoms          TEXT NOT NULL DEFAULT '[]',
    investigation     TEXT NOT NULL DEFAULT '[]',
    root_cause        TEXT NOT NULL DEFAULT '',
    fixes             TEXT NOT NULL DEFAULT '[]',
    related_patterns  TEXT NOT NULL DEFAULT '[]',
    tags              TEXT NOT NULL DEFAULT '[]',
    source            TEXT NOT NULL DEFAULT 'learned',
    confidence        REAL NOT NULL DEFAULT 0.0,
    occurrence_count  INTEGER NOT NULL DEFAULT 1,
    first_seen        TEXT NOT NULL,
    last_seen         TEXT NOT NULL,
    source_sessions   TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS experience_entries (
    session_id          TEXT PRIMARY KEY,
    timestamp           TEXT NOT NULL,
    system_id           TEXT NOT NULL DEFAULT '',
    trigger             TEXT NOT NULL DEFAULT '',
    duration_seconds    REAL NOT NULL DEFAULT 0.0,
    patterns_matched    TEXT NOT NULL DEFAULT '[]',
    rules_fired         INTEGER NOT NULL DEFAULT 0,
    rules_failed        INTEGER NOT NULL DEFAULT 0,
    root_cause_found    INTEGER NOT NULL DEFAULT 0,
    resolution_applied  INTEGER NOT NULL DEFAULT 0,
    operator_feedback   TEXT,
    knowledge_gaps      TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS knowledge_gaps (
    id          TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    session_id  TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    resolved    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS evidence_definitions (
    id                  TEXT PRIMARY KEY,
    type                TEXT NOT NULL DEFAULT 'command',
    name                TEXT NOT NULL DEFAULT '',
    command             TEXT NOT NULL DEFAULT '',
    description         TEXT NOT NULL DEFAULT '',
    os_family           TEXT NOT NULL DEFAULT '["SUSE", "REDHAT"]',
    parser              TEXT NOT NULL DEFAULT '',
    source              TEXT NOT NULL DEFAULT 'command',
    evidence_type       TEXT NOT NULL DEFAULT 'command_output',
    requires_ha         INTEGER NOT NULL DEFAULT 0,
    cache_ttl_seconds   INTEGER NOT NULL DEFAULT 300,
    max_timeout_seconds INTEGER NOT NULL DEFAULT 30,
    tags                TEXT NOT NULL DEFAULT '[]',
    metadata            TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_rules_category
    ON rules(category);
CREATE INDEX IF NOT EXISTS idx_rules_severity
    ON rules(severity);
CREATE INDEX IF NOT EXISTS idx_playbooks_category
    ON playbooks(category);
CREATE INDEX IF NOT EXISTS idx_learned_confidence
    ON learned_patterns(confidence);
CREATE INDEX IF NOT EXISTS idx_experience_system
    ON experience_entries(system_id);
CREATE INDEX IF NOT EXISTS idx_gaps_session
    ON knowledge_gaps(session_id);
CREATE INDEX IF NOT EXISTS idx_gaps_resolved
    ON knowledge_gaps(resolved);
"""


def _dt_to_iso(dt: Optional[datetime]) -> Optional[str]:
    """Convert datetime to ISO-8601 string for SQLite storage."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


class KnowledgeStore:
    """Knowledge artifacts backed by ``StafStore``."""

    SCHEMA = KNOWLEDGE_SCHEMA

    def __init__(
        self,
        db: Optional[StafStore] = None,
        *,
        db_path: Optional[Path] = None,
    ) -> None:
        if db is None:
            if db_path is None:
                raise ValueError("Either db or db_path must be provided")
            db = StafStore(db_path)
            self._owns_db = True
        else:
            self._owns_db = False
        self._db = db
        self._conn = db.conn
        db.register_schema(self.SCHEMA)
        if self._owns_db:
            db.sync()

    def close(self) -> None:
        """Close the underlying database if this store owns it."""
        if self._owns_db:
            self._db.close()

    def save_rule(self, rule: Rule) -> Rule:
        """Insert or replace a rule.

        :param rule: Rule to persist.
        :returns: The persisted rule.
        """
        with self._conn:
            self._conn.execute(
                """INSERT OR REPLACE INTO rules
                   (id, name, description, category, severity,
                    applicability, validator, "references", tags)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    rule.id,
                    rule.name,
                    rule.description,
                    rule.category,
                    rule.severity,
                    json.dumps(
                        rule.applicability.__dict__ if rule.applicability else {},
                        default=str,
                    ),
                    json.dumps(
                        rule.validator.model_dump(mode="json") if rule.validator else None,
                        default=str,
                    ),
                    json.dumps(rule.references),
                    json.dumps(rule.tags),
                ),
            )
        return rule

    def save_rules(self, rules: list[Rule]) -> int:
        """Bulk-insert rules.

        :param rules: Rules to persist.
        :returns: Number of rules saved.
        """
        for rule in rules:
            self.save_rule(rule)
        return len(rules)

    def load_rules(
        self,
        system: Optional[SystemProperties] = None,
    ) -> List[Rule]:
        """Load rules, optionally filtered by system applicability.

        :param system: If provided, only return rules applicable to this system.
        :returns: List of matching rules.
        """
        self._conn.row_factory = sqlite3.Row
        cur = self._conn.execute("SELECT * FROM rules")
        rules: list[Rule] = []
        for row in cur.fetchall():
            rule = self._row_to_rule(dict(row))
            if system is None or self._rule_matches(rule, system):
                rules.append(rule)
        return rules

    def get_rule(self, rule_id: str) -> Optional[Rule]:
        """Get a single rule by ID.

        :param rule_id: Rule identifier.
        :returns: Rule if found, None otherwise.
        """
        self._conn.row_factory = sqlite3.Row
        row = self._conn.execute("SELECT * FROM rules WHERE id = ?", (rule_id,)).fetchone()
        return self._row_to_rule(dict(row)) if row else None

    @staticmethod
    def _row_to_rule(data: dict) -> Rule:
        """Reconstruct a Rule from a database row."""
        app_data = json.loads(data["applicability"])
        validator_data = json.loads(data["validator"]) if data["validator"] else None
        return Rule(
            id=data["id"],
            name=data["name"],
            description=data["description"],
            category=data["category"],
            severity=data["severity"],
            applicability=Applicability(**app_data) if app_data else None,
            validator=validator_data,
            references=json.loads(data["references"]),
            tags=json.loads(data["tags"]),
        )

    @staticmethod
    def _rule_matches(rule: Rule, system: SystemProperties) -> bool:
        """Check if a rule applies to the given system."""
        if rule.applicability is None:
            return True
        return rule.applicability.matches(system)

    def save_playbook(self, playbook: Playbook) -> Playbook:
        """Insert or replace a playbook.

        :param playbook: Playbook to persist.
        :returns: The persisted playbook.
        """
        with self._conn:
            self._conn.execute(
                """INSERT OR REPLACE INTO playbooks
                   (id, name, description, category, symptoms,
                    investigation, root_cause, fixes,
                    related_patterns, tags, source)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    playbook.id,
                    playbook.name,
                    playbook.description,
                    playbook.category,
                    json.dumps(playbook.symptoms),
                    json.dumps(playbook.investigation),
                    playbook.root_cause,
                    json.dumps(playbook.fixes),
                    json.dumps(playbook.related_patterns),
                    json.dumps(playbook.tags),
                    playbook.source,
                ),
            )
        return playbook

    def save_playbooks(self, playbooks: list[Playbook]) -> int:
        """Bulk-insert playbooks.

        :param playbooks: Playbooks to persist.
        :returns: Number of playbooks saved.
        """
        for playbook in playbooks:
            self.save_playbook(playbook)
        return len(playbooks)

    def load_playbooks(self) -> List[Playbook]:
        """Load all playbooks.

        :returns: List of all playbooks.
        """
        self._conn.row_factory = sqlite3.Row
        cur = self._conn.execute("SELECT * FROM playbooks")
        return [self._row_to_playbook(dict(row)) for row in cur.fetchall()]

    @staticmethod
    def _row_to_playbook(data: dict) -> Playbook:
        """Reconstruct a Playbook from a database row."""
        return Playbook(
            id=data["id"],
            name=data["name"],
            description=data["description"],
            category=data["category"],
            symptoms=json.loads(data["symptoms"]),
            investigation=json.loads(data["investigation"]),
            root_cause=data["root_cause"],
            fixes=json.loads(data["fixes"]),
            related_patterns=json.loads(data["related_patterns"]),
            tags=json.loads(data["tags"]),
            source=data["source"],
        )

    def save_reference(self, ref: Reference) -> Reference:
        """Insert or replace a reference.

        :param ref: Reference to persist.
        :returns: The persisted reference.
        """
        with self._conn:
            self._conn.execute(
                """INSERT OR REPLACE INTO "references"
                   (id, title, url, category, failure_classes,
                    summary, tags)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    ref.id,
                    ref.title,
                    ref.url,
                    ref.category,
                    json.dumps(ref.failure_classes),
                    ref.summary,
                    json.dumps(ref.tags),
                ),
            )
        return ref

    def save_references(self, refs: list[Reference]) -> int:
        """Bulk-insert references.

        :param refs: References to persist.
        :returns: Number of references saved.
        """
        for ref in refs:
            self.save_reference(ref)
        return len(refs)

    def load_references(self) -> List[Reference]:
        """Load all references.

        :returns: List of all references.
        """
        self._conn.row_factory = sqlite3.Row
        cur = self._conn.execute('SELECT * FROM "references"')
        return [self._row_to_reference(dict(row)) for row in cur.fetchall()]

    @staticmethod
    def _row_to_reference(data: dict) -> Reference:
        """Reconstruct a Reference from a database row."""
        return Reference(
            id=data["id"],
            title=data["title"],
            url=data["url"],
            category=data["category"],
            failure_classes=json.loads(data["failure_classes"]),
            summary=data["summary"],
            tags=json.loads(data["tags"]),
        )

    def save_learned_pattern(self, pattern: LearnedPattern) -> LearnedPattern:
        """Insert or replace a learned pattern.

        :param pattern: Learned pattern to persist.
        :returns: The persisted pattern.
        """
        with self._conn:
            self._conn.execute(
                """INSERT OR REPLACE INTO learned_patterns
                   (id, name, description, category, symptoms,
                    investigation, root_cause, fixes,
                    related_patterns, tags, source, confidence,
                    occurrence_count, first_seen, last_seen,
                    source_sessions)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    pattern.id,
                    pattern.name,
                    pattern.description,
                    pattern.category,
                    json.dumps(pattern.symptoms),
                    json.dumps(pattern.investigation),
                    pattern.root_cause,
                    json.dumps(pattern.fixes),
                    json.dumps(pattern.related_patterns),
                    json.dumps(pattern.tags),
                    pattern.source,
                    pattern.confidence,
                    pattern.occurrence_count,
                    _dt_to_iso(pattern.first_seen),
                    _dt_to_iso(pattern.last_seen),
                    json.dumps(pattern.source_sessions),
                ),
            )
        return pattern

    def load_learned_patterns(self, min_confidence: float = 0.0) -> List[LearnedPattern]:
        """Load learned patterns above a confidence threshold.

        :param min_confidence: Minimum confidence score (default 0.0).
        :returns: List of matching learned patterns.
        """
        self._conn.row_factory = sqlite3.Row
        cur = self._conn.execute(
            "SELECT * FROM learned_patterns WHERE confidence >= ?",
            (min_confidence,),
        )
        return [self._row_to_learned_pattern(dict(row)) for row in cur.fetchall()]

    def get_learned_pattern(self, pattern_id: str) -> Optional[LearnedPattern]:
        """Get a single learned pattern by ID.

        :param pattern_id: Pattern identifier.
        :returns: Pattern if found, None otherwise.
        """
        self._conn.row_factory = sqlite3.Row
        row = self._conn.execute(
            "SELECT * FROM learned_patterns WHERE id = ?",
            (pattern_id,),
        ).fetchone()
        return self._row_to_learned_pattern(dict(row)) if row else None

    @staticmethod
    def _row_to_learned_pattern(data: dict) -> LearnedPattern:
        """Reconstruct a LearnedPattern from a database row."""
        return LearnedPattern(
            id=data["id"],
            name=data["name"],
            description=data["description"],
            category=data["category"],
            symptoms=json.loads(data["symptoms"]),
            investigation=json.loads(data["investigation"]),
            root_cause=data["root_cause"],
            fixes=json.loads(data["fixes"]),
            related_patterns=json.loads(data["related_patterns"]),
            tags=json.loads(data["tags"]),
            source=data["source"],
            confidence=data["confidence"],
            occurrence_count=data["occurrence_count"],
            first_seen=datetime.fromisoformat(data["first_seen"]),
            last_seen=datetime.fromisoformat(data["last_seen"]),
            source_sessions=json.loads(data["source_sessions"]),
        )

    def log_experience(self, entry: ExperienceEntry) -> ExperienceEntry:
        """Insert or replace an experience entry.

        :param entry: Experience entry to persist.
        :returns: The persisted entry.
        """
        with self._conn:
            self._conn.execute(
                """INSERT OR REPLACE INTO experience_entries
                   (session_id, timestamp, system_id, trigger,
                    duration_seconds, patterns_matched, rules_fired,
                    rules_failed, root_cause_found, resolution_applied,
                    operator_feedback, knowledge_gaps)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    entry.session_id,
                    _dt_to_iso(entry.timestamp),
                    entry.system_id,
                    entry.trigger,
                    entry.duration_seconds,
                    json.dumps(entry.patterns_matched),
                    entry.rules_fired,
                    entry.rules_failed,
                    int(entry.root_cause_found),
                    int(entry.resolution_applied),
                    entry.operator_feedback,
                    json.dumps(entry.knowledge_gaps),
                ),
            )
        return entry

    def get_experience(self, session_id: str) -> Optional[ExperienceEntry]:
        """Get an experience entry by session ID.

        :param session_id: Session identifier.
        :returns: Experience entry if found, None otherwise.
        """
        self._conn.row_factory = sqlite3.Row
        row = self._conn.execute(
            "SELECT * FROM experience_entries WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        return self._row_to_experience(dict(row)) if row else None

    @staticmethod
    def _row_to_experience(data: dict) -> ExperienceEntry:
        """Reconstruct an ExperienceEntry from a database row."""
        return ExperienceEntry(
            session_id=data["session_id"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            system_id=data["system_id"],
            trigger=data["trigger"],
            duration_seconds=data["duration_seconds"],
            patterns_matched=json.loads(data["patterns_matched"]),
            rules_fired=data["rules_fired"],
            rules_failed=data["rules_failed"],
            root_cause_found=bool(data["root_cause_found"]),
            resolution_applied=bool(data["resolution_applied"]),
            operator_feedback=data["operator_feedback"],
            knowledge_gaps=json.loads(data["knowledge_gaps"]),
        )

    def log_gap(self, gap: KnowledgeGap) -> KnowledgeGap:
        """Insert or replace a knowledge gap.

        :param gap: Knowledge gap to persist.
        :returns: The persisted gap.
        """
        with self._conn:
            self._conn.execute(
                """INSERT OR REPLACE INTO knowledge_gaps
                   (id, description, session_id, created_at, resolved)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    gap.id,
                    gap.description,
                    gap.session_id,
                    _dt_to_iso(gap.created_at),
                    int(gap.resolved),
                ),
            )
        return gap

    def get_unresolved_gaps(self) -> List[KnowledgeGap]:
        """Get all unresolved knowledge gaps.

        :returns: List of unresolved gaps.
        """
        self._conn.row_factory = sqlite3.Row
        cur = self._conn.execute("SELECT * FROM knowledge_gaps WHERE resolved = 0")
        return [self._row_to_gap(dict(row)) for row in cur.fetchall()]

    def resolve_gap(self, gap_id: str) -> bool:
        """Mark a knowledge gap as resolved.

        :param gap_id: Gap identifier.
        :returns: True if the gap was found and updated.
        """
        with self._conn:
            cur = self._conn.execute(
                "UPDATE knowledge_gaps SET resolved = 1 WHERE id = ?",
                (gap_id,),
            )
        return cur.rowcount > 0

    @staticmethod
    def _row_to_gap(data: dict) -> KnowledgeGap:
        """Reconstruct a KnowledgeGap from a database row."""
        return KnowledgeGap(
            id=data["id"],
            description=data["description"],
            session_id=data["session_id"],
            created_at=datetime.fromisoformat(data["created_at"]),
            resolved=bool(data["resolved"]),
        )

    def save_evidence_definition(self, definition: EvidenceCollectorDef) -> EvidenceCollectorDef:
        """Insert or replace an evidence collection definition.

        :param definition: Evidence definition to persist.
        :returns: The persisted definition.
        """
        with self._conn:
            self._conn.execute(
                """INSERT OR REPLACE INTO evidence_definitions
                   (id, type, name, command, description,
                    os_family, parser, source, evidence_type,
                    requires_ha, cache_ttl_seconds,
                    max_timeout_seconds, tags, metadata)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    definition.id,
                    definition.type,
                    definition.name,
                    definition.command,
                    definition.description,
                    json.dumps(definition.os_family),
                    definition.parser,
                    definition.source,
                    definition.evidence_type,
                    int(definition.requires_ha),
                    definition.cache_ttl_seconds,
                    definition.max_timeout_seconds,
                    json.dumps(definition.tags),
                    json.dumps(definition.metadata),
                ),
            )
        return definition

    def save_evidence_definitions(self, definitions: list[EvidenceCollectorDef]) -> int:
        """Bulk-insert evidence definitions.

        :param definitions: Definitions to persist.
        :returns: Number saved.
        """
        for d in definitions:
            self.save_evidence_definition(d)
        return len(definitions)

    def load_evidence_definitions(
        self, os_family: Optional[str] = None, collector_type: str = "command"
    ) -> List[EvidenceCollectorDef]:
        """Load evidence definitions, optionally filtered by OS family.

        :param os_family: If provided, only return defs applicable to
            this OS (``SUSE`` or ``REDHAT``). None returns all.
        :param collector_type: Filter by collector type (default ``command``).
        :returns: List of matching evidence definitions.
        """
        self._conn.row_factory = sqlite3.Row
        cur = self._conn.execute(
            "SELECT * FROM evidence_definitions WHERE type = ?",
            (collector_type,),
        )
        defs: list[EvidenceCollectorDef] = []
        for row in cur.fetchall():
            d = self._row_to_evidence_def(dict(row))
            if os_family is None or os_family.upper() in (f.upper() for f in d.os_family):
                defs.append(d)
        return defs

    @staticmethod
    def _row_to_evidence_def(data: dict) -> EvidenceCollectorDef:
        """Reconstruct an EvidenceCollectorDef from a database row."""
        return EvidenceCollectorDef(
            id=data["id"],
            type=data["type"],
            name=data["name"],
            command=data["command"],
            description=data["description"],
            os_family=json.loads(data["os_family"]),
            parser=data["parser"],
            source=data.get("source", "command"),
            evidence_type=data.get("evidence_type", "command_output"),
            requires_ha=bool(data.get("requires_ha", 0)),
            cache_ttl_seconds=data["cache_ttl_seconds"],
            max_timeout_seconds=data["max_timeout_seconds"],
            tags=json.loads(data["tags"]),
            metadata=json.loads(data.get("metadata", "{}")),
        )
