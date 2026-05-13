# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Unified SQLite store for all STAF application data.

One connection, one ``sync()``, one ``close()``.  Domain stores
are attributes: ``db.jobs``, ``db.schedules``, ``db.knowledge``.
"""

from __future__ import annotations
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


class StafStore:
    """Single SQLite connection owning all domain tables.

    Sub-stores are created lazily on first access after ``sync()``.
    """

    def __init__(self, db_path: Path | str = "data/staf.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._conn = sqlite3.connect(
            str(self.db_path),
            isolation_level="DEFERRED",
            check_same_thread=False,
        )
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.row_factory = sqlite3.Row

        self._schemas: list[str] = []
        self._jobs: Any = None
        self._schedules: Any = None

    def register_schema(self, schema_sql: str) -> None:
        """Register a CREATE TABLE block (called by sub-store __init__)."""
        self._schemas.append(schema_sql)

    def sync(self) -> None:
        """Create all registered tables.

        Call once after all sub-stores are instantiated.
        """
        for sql in self._schemas:
            self._conn.executescript(sql)
        logger.info(
            "StafStore synced %d schema blocks at %s",
            len(self._schemas),
            self.db_path,
        )

    @property
    def jobs(self) -> Any:
        """JobStore instance."""
        return self._jobs

    @property
    def schedules(self) -> Any:
        """ScheduleStore instance."""
        return self._schedules

    @property
    def conn(self) -> sqlite3.Connection:
        return self._conn

    def close(self) -> None:
        """Close the single shared connection."""
        self._conn.close()

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        return self._conn.execute(sql, params)

    def executemany(self, sql: str, seq: list[tuple]) -> sqlite3.Cursor:
        return self._conn.executemany(sql, seq)

    def commit(self) -> None:
        self._conn.commit()

    def fetchone(self, sql: str, params: tuple = ()) -> dict | None:
        row = self._conn.execute(sql, params).fetchone()
        return dict(row) if row else None

    def fetchall(self, sql: str, params: tuple = ()) -> list[dict]:
        return [dict(r) for r in self._conn.execute(sql, params).fetchall()]

    @staticmethod
    def dt_to_iso(dt: Optional[datetime]) -> Optional[str]:
        """Convert datetime to ISO-8601 string for SQLite."""
        if dt is None:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
