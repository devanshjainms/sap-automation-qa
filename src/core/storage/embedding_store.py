# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""SQLite + sqlite-vec backed store for vector embeddings.

Uses the ``vec0`` virtual table from the ``sqlite-vec`` C extension to
support cosine-similarity KNN queries directly inside SQLite — no
external vector database required.
"""

import sqlite_vec
import struct
from datetime import datetime, timezone
from typing import TYPE_CHECKING, List, Optional, Tuple

if TYPE_CHECKING:
    from src.core.storage.staf_store import StafStore

try:
    import pysqlite3 as sqlite3  # type: ignore[import-untyped]
except ImportError:
    import sqlite3


def _serialize_f32(vector: List[float]) -> bytes:
    """Pack a float list into a compact float32 byte buffer.

    :param vector: List of float values.
    :returns: Packed bytes (4 bytes per element).
    """
    return struct.pack(f"{len(vector)}f", *vector)


def _deserialize_f32(data: bytes) -> List[float]:
    """Unpack a float32 byte buffer into a float list.

    :param data: Packed bytes.
    :returns: List of float values.
    """
    count = len(data) // 4
    return list(struct.unpack(f"{count}f", data))


def _load_sqlite_vec(conn: sqlite3.Connection) -> None:
    """Load the sqlite-vec extension into a connection.

    :param conn: SQLite connection.
    :raises RuntimeError: If the extension cannot be loaded.
    """

    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)


_TYPE_FILTER_OVERFETCH = 3


class EmbeddingStore:
    """SQLite + sqlite-vec backed store for vector embeddings.

    Accepts a ``StafStore`` for the shared connection.  Loads the
    ``sqlite-vec`` C extension and manages its own virtual tables
    (which can't be schema-synced via ``ALTER TABLE``).

    :param db: Shared StafStore instance.
    :param dimensions: Embedding vector dimensions.
    """

    def __init__(
        self,
        db: Optional["StafStore"] = None,
        dimensions: int = 768,
        *,
        db_path: Optional[str] = None,
    ) -> None:
        if not isinstance(dimensions, int) or dimensions <= 0:
            raise ValueError(f"dimensions must be a positive integer, got {dimensions!r}")
        if db is None:
            if db_path is None:
                raise ValueError("Either db or db_path must be provided")
            from src.core.storage.staf_store import StafStore

            db = StafStore(db_path)
            self._owns_db = True
        else:
            self._owns_db = False
        self._dimensions = dimensions
        self._db = db
        self._conn = self._db.conn
        _load_sqlite_vec(self._conn)
        self._create_tables()
        self._validate_dimensions()

    def close(self) -> None:
        """Close the underlying database if this store owns it."""
        if self._owns_db:
            self._db.close()

    @property
    def dimensions(self) -> int:
        """Return the configured vector dimensions."""
        return self._dimensions

    def _create_tables(self) -> None:
        """Create metadata and vec0 virtual tables if missing."""
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS embedding_metadata (
                row_id    INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id   TEXT    NOT NULL,
                item_type TEXT    NOT NULL,
                text_hash TEXT    NOT NULL DEFAULT '',
                updated_at TEXT   NOT NULL,
                UNIQUE (item_id, item_type)
            )
            """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS embedding_dimensions (
                id         INTEGER PRIMARY KEY CHECK (id = 1),
                dimensions INTEGER NOT NULL
            )
            """)
        self._conn.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS vec_embeddings "
            f"USING vec0(embedding float[{self._dimensions}] "
            f"distance_metric=cosine)"
        )
        self._conn.execute(
            "INSERT OR IGNORE INTO embedding_dimensions " "(id, dimensions) VALUES (1, ?)",
            (self._dimensions,),
        )
        self._conn.commit()

    def _validate_dimensions(self) -> None:
        """Verify stored dimensions match configured dimensions.

        :raises RuntimeError: On mismatch.
        """
        row = self._conn.execute(
            "SELECT dimensions FROM embedding_dimensions " "WHERE id = 1"
        ).fetchone()
        if row and row[0] != self._dimensions:
            raise RuntimeError(
                f"Database was created with {row[0]} dimensions "
                f"but {self._dimensions} were requested. "
                f"Re-index or use the original dimension count."
            )

    def store(
        self,
        item_id: str,
        item_type: str,
        embedding: List[float],
        text_hash: str = "",
    ) -> None:
        """Store or update an embedding for an item.

        :param item_id: Unique identifier of the knowledge item.
        :param item_type: Type of item (``rule``, ``playbook``,
            ``learned_pattern``).
        :param embedding: Float vector of length ``dimensions``.
        :param text_hash: Optional hash of the source text for
            staleness detection.
        :raises ValueError: If ``embedding`` length != ``dimensions``.
        """
        if len(embedding) != self._dimensions:
            raise ValueError(f"Expected {self._dimensions} dimensions, " f"got {len(embedding)}")

        now = self._db.dt_to_iso(datetime.now(timezone.utc))
        blob = _serialize_f32(embedding)

        with self._conn:
            existing = self._conn.execute(
                "SELECT row_id FROM embedding_metadata " "WHERE item_id = ? AND item_type = ?",
                (item_id, item_type),
            ).fetchone()

            if existing is not None:
                rid = existing[0]
                self._conn.execute(
                    "UPDATE embedding_metadata "
                    "SET text_hash = ?, updated_at = ? "
                    "WHERE row_id = ?",
                    (text_hash, now, rid),
                )
                self._conn.execute(
                    "UPDATE vec_embeddings " "SET embedding = ? WHERE rowid = ?",
                    (blob, rid),
                )
            else:
                cursor = self._conn.execute(
                    "INSERT INTO embedding_metadata "
                    "(item_id, item_type, text_hash, updated_at) "
                    "VALUES (?, ?, ?, ?)",
                    (item_id, item_type, text_hash, now),
                )
                rid = cursor.lastrowid
                self._conn.execute(
                    "INSERT INTO vec_embeddings " "(rowid, embedding) VALUES (?, ?)",
                    (rid, blob),
                )

    def search(
        self,
        query_embedding: List[float],
        item_type: str = "",
        limit: int = 20,
    ) -> List[Tuple[str, str, float]]:
        """Find items closest to ``query_embedding`` by cosine distance.

        :param query_embedding: Query vector.
        :param item_type: Optional type filter (post-KNN filtering).
        :param limit: Maximum results after filtering.
        :returns: ``(item_id, item_type, distance)`` tuples sorted by
            ascending distance (0 = identical).
        :raises ValueError: If vector length != ``dimensions``.
        """
        if len(query_embedding) != self._dimensions:
            raise ValueError(
                f"Expected {self._dimensions} dimensions, " f"got {len(query_embedding)}"
            )

        blob = _serialize_f32(query_embedding)
        fetch_k = limit * _TYPE_FILTER_OVERFETCH if item_type else limit

        vec_rows = self._conn.execute(
            "SELECT rowid, distance FROM vec_embeddings " "WHERE embedding MATCH ? AND k = ?",
            (blob, fetch_k),
        ).fetchall()

        if not vec_rows:
            return []

        distance_map = {row[0]: row[1] for row in vec_rows}
        rowids = list(distance_map.keys())
        placeholders = ",".join("?" * len(rowids))

        meta_rows = self._conn.execute(
            "SELECT row_id, item_id, item_type "
            f"FROM embedding_metadata WHERE row_id IN ({placeholders})",
            rowids,
        ).fetchall()

        results: List[Tuple[str, str, float]] = []
        for row in meta_rows:
            rid, iid, itype = row
            if item_type and itype != item_type:
                continue
            results.append((iid, itype, distance_map[rid]))

        results.sort(key=lambda r: r[2])
        return results[:limit]

    def get(self, item_id: str, item_type: str) -> Optional[List[float]]:
        """Retrieve the stored embedding for an item.

        :param item_id: Item identifier.
        :param item_type: Item type.
        :returns: Embedding vector, or ``None`` if not found.
        """
        row = self._conn.execute(
            "SELECT m.row_id FROM embedding_metadata m " "WHERE m.item_id = ? AND m.item_type = ?",
            (item_id, item_type),
        ).fetchone()

        if row is None:
            return None

        rid = row[0]
        vec_row = self._conn.execute(
            "SELECT embedding FROM vec_embeddings WHERE rowid = ?",
            (rid,),
        ).fetchone()

        if vec_row is None:
            return None
        return _deserialize_f32(vec_row[0])

    def has(self, item_id: str, item_type: str) -> bool:
        """Check whether an embedding exists for the given item.

        :param item_id: Item identifier.
        :param item_type: Item type.
        :returns: ``True`` if an embedding is stored.
        """
        row = self._conn.execute(
            "SELECT 1 FROM embedding_metadata " "WHERE item_id = ? AND item_type = ?",
            (item_id, item_type),
        ).fetchone()
        return row is not None

    def delete(self, item_id: str, item_type: str) -> bool:
        """Delete the embedding for an item.

        :param item_id: Item identifier.
        :param item_type: Item type.
        :returns: ``True`` if a row was deleted.
        """
        row = self._conn.execute(
            "SELECT row_id FROM embedding_metadata " "WHERE item_id = ? AND item_type = ?",
            (item_id, item_type),
        ).fetchone()

        if row is None:
            return False

        rid = row[0]
        with self._conn:
            self._conn.execute(
                "DELETE FROM vec_embeddings WHERE rowid = ?",
                (rid,),
            )
            self._conn.execute(
                "DELETE FROM embedding_metadata WHERE row_id = ?",
                (rid,),
            )
        return True

    def count(self) -> int:
        """Return the total number of stored embeddings."""
        row = self._conn.execute("SELECT COUNT(*) FROM embedding_metadata").fetchone()
        return row[0] if row else 0
