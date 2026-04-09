# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Knowledge graph: causal and relational edges between patterns."""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Union

from src.core.storage.staf_store import StafStore

GRAPH_SCHEMA = """
CREATE TABLE IF NOT EXISTS knowledge_edges (
    source_id   TEXT NOT NULL,
    target_id   TEXT NOT NULL,
    edge_type   TEXT NOT NULL,
    strength    REAL NOT NULL DEFAULT 0.5,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (source_id, target_id, edge_type)
);

CREATE INDEX IF NOT EXISTS idx_edges_source
    ON knowledge_edges(source_id);
CREATE INDEX IF NOT EXISTS idx_edges_target
    ON knowledge_edges(target_id);
CREATE INDEX IF NOT EXISTS idx_edges_type
    ON knowledge_edges(edge_type);
"""

VALID_EDGE_TYPES = frozenset({"causes", "caused_by", "related_to", "supersedes", "prerequisite"})
_EMA_ALPHA = 0.3


class KnowledgeGraph:
    """Pattern relationship graph backed by ``StafStore``."""

    SCHEMA = GRAPH_SCHEMA

    def __init__(
        self,
        db: Optional[StafStore] = None,
        *,
        db_path: Optional[Union[Path, str]] = None,
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

    def add_edge(
        self,
        source_id: str,
        target_id: str,
        edge_type: str,
        strength: float = 0.5,
    ) -> None:
        """Add an edge between two patterns.

        If the edge already exists, its strength is updated via EMA.

        :param source_id: Source pattern identifier.
        :param target_id: Target pattern identifier.
        :param edge_type: Relationship type (causes, caused_by, etc.).
        :param strength: Initial or observed strength (0.0–1.0).
        :raises ValueError: If edge_type is not a valid relationship type.
        """
        if edge_type not in VALID_EDGE_TYPES:
            raise ValueError(
                f"Invalid edge type '{edge_type}'. " f"Valid types: {sorted(VALID_EDGE_TYPES)}"
            )

        existing = self._get_edge(source_id, target_id, edge_type)
        now = self._db.dt_to_iso(datetime.now(timezone.utc))

        if existing is not None:
            self.update_strength(source_id, target_id, edge_type, strength)
        else:
            with self._conn:
                self._conn.execute(
                    """INSERT INTO knowledge_edges
                       (source_id, target_id, edge_type, strength,
                        created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (source_id, target_id, edge_type, strength, now, now),
                )

    def update_strength(
        self,
        source_id: str,
        target_id: str,
        edge_type: str,
        observed: float,
    ) -> Optional[float]:
        """Update edge strength using EMA.

        Formula: ``new = 0.3 * observed + 0.7 * old``

        :param source_id: Source pattern identifier.
        :param target_id: Target pattern identifier.
        :param edge_type: Relationship type.
        :param observed: Newly observed strength value.
        :returns: New strength after EMA update, or None if edge not found.
        """
        existing = self._get_edge(source_id, target_id, edge_type)
        if existing is None:
            return None

        old_strength = existing["strength"]
        new_strength = _EMA_ALPHA * observed + (1 - _EMA_ALPHA) * old_strength

        with self._conn:
            self._conn.execute(
                """UPDATE knowledge_edges
                   SET strength = ?, updated_at = ?
                   WHERE source_id = ? AND target_id = ?
                   AND edge_type = ?""",
                (
                    new_strength,
                    self._db.dt_to_iso(datetime.now(timezone.utc)),
                    source_id,
                    target_id,
                    edge_type,
                ),
            )
        return new_strength

    def get_causes(self, pattern_id: str) -> List[dict]:
        """Get patterns that cause the given pattern.

        Walks ``caused_by`` edges from the perspective of the target.

        :param pattern_id: Pattern to find causes for.
        :returns: List of edge dicts with source_id, strength.
        """
        return self._query_edges(
            "SELECT * FROM knowledge_edges " "WHERE target_id = ? AND edge_type = 'causes'",
            (pattern_id,),
        )

    def get_effects(self, pattern_id: str) -> List[dict]:
        """Get patterns caused by the given pattern.

        :param pattern_id: Source pattern.
        :returns: List of edge dicts.
        """
        return self._query_edges(
            "SELECT * FROM knowledge_edges " "WHERE source_id = ? AND edge_type = 'causes'",
            (pattern_id,),
        )

    def get_related(self, pattern_id: str) -> List[dict]:
        """Get patterns related to the given pattern.

        Includes both directions of ``related_to`` edges.

        :param pattern_id: Pattern to find relations for.
        :returns: List of edge dicts.
        """
        return self._query_edges(
            "SELECT * FROM knowledge_edges "
            "WHERE (source_id = ? OR target_id = ?) "
            "AND edge_type = 'related_to'",
            (pattern_id, pattern_id),
        )

    def get_all_edges(self, pattern_id: str) -> List[dict]:
        """Get all edges involving a pattern (either direction).

        :param pattern_id: Pattern identifier.
        :returns: List of all edge dicts.
        """
        return self._query_edges(
            "SELECT * FROM knowledge_edges " "WHERE source_id = ? OR target_id = ?",
            (pattern_id, pattern_id),
        )

    def _get_edge(
        self,
        source_id: str,
        target_id: str,
        edge_type: str,
    ) -> Optional[dict]:
        """Get a specific edge if it exists."""
        self._conn.row_factory = sqlite3.Row
        row = self._conn.execute(
            "SELECT * FROM knowledge_edges "
            "WHERE source_id = ? AND target_id = ? AND edge_type = ?",
            (source_id, target_id, edge_type),
        ).fetchone()
        return dict(row) if row else None

    def _query_edges(self, sql: str, params: tuple) -> List[dict]:
        """Execute an edge query and return list of dicts."""
        self._conn.row_factory = sqlite3.Row
        rows = self._conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]
