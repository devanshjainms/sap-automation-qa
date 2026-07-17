# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Read-only search API over the generated SQLite FTS5 knowledge index.

Provides full-text search with optional structured filters and exact
get-by-ID retrieval. Never returns executable content. Enforces a hard
maximum of 10 results regardless of caller input.
"""

import json
import re
import sqlite3
from pathlib import Path
from typing import Optional
from pydantic import ValidationError
from src.core.exceptions import (
    IndexCorruptError,
    IndexIncompatibleError,
    IndexMissingError,
    InvalidFilterError,
    InvalidLimitError,
    InvalidQueryError,
)
from src.core.models.knowledge import (
    AppliesTo,
    KnowledgeKind,
    KnowledgeRecord,
    KnowledgeRisk,
    KnowledgeSearchFilters,
    SCHEMA_VERSION,
    SearchResponse,
    SearchResult,
)

MAX_RESULTS = 10
VALID_KINDS = {e.value for e in KnowledgeKind}
VALID_RISKS = {e.value for e in KnowledgeRisk}
_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class KnowledgeIndex:
    """Read-only accessor for the generated SQLite FTS5 knowledge index.

    :param index_path: Path to the SQLite knowledge index file.
    :type index_path: pathlib.Path
    :raises IndexMissingError: If the index file does not exist.
    :raises IndexCorruptError: If the file is not a valid SQLite database.
    :raises IndexIncompatibleError: If the schema version does not match.
    """

    def __init__(self, index_path: Path) -> None:
        """Initialize and validate the knowledge index.

        :param index_path: Path to the SQLite knowledge index file.
        :type index_path: pathlib.Path
        :raises IndexMissingError: If the index file does not exist.
        :raises IndexCorruptError: If the file is not a valid SQLite database.
        :raises IndexIncompatibleError: If schema version does not match.
        """
        self._path = Path(index_path)
        self._validate_index()

    def _validate_index(self) -> None:
        """Validate the index file exists, is readable, and is compatible.

        :raises IndexMissingError: If the index file does not exist.
        :raises IndexCorruptError: If the file is not valid SQLite or has
            corrupt/inconsistent internal data.
        :raises IndexIncompatibleError: If the schema version does not match.
        """
        if not self._path.exists():
            raise IndexMissingError(f"Knowledge index not found: {self._path}")

        try:
            conn = sqlite3.connect(str(self._path))
        except sqlite3.DatabaseError as exc:
            raise IndexCorruptError(
                f"Knowledge index is not a valid SQLite database: {exc}"
            ) from exc

        try:
            conn.execute("SELECT 1 FROM knowledge_records LIMIT 1")
            conn.execute(
                "SELECT COUNT(*) FROM knowledge_fts WHERE knowledge_fts MATCH 'test_probe'"
            )
            manifest = self._read_manifest(conn)
            self._validate_manifest(conn, manifest)

        except (IndexCorruptError, IndexIncompatibleError):
            raise
        except sqlite3.DatabaseError as exc:
            raise IndexCorruptError(
                f"Knowledge index is not a valid SQLite database: {exc}"
            ) from exc
        finally:
            conn.close()

    @staticmethod
    def _read_manifest(conn: sqlite3.Connection) -> dict:
        """Read and deserialize the build manifest from an open connection."""
        row = conn.execute("SELECT value FROM build_manifest WHERE key = 'manifest'").fetchone()
        if row is None:
            raise IndexCorruptError("Knowledge index missing manifest entry")
        try:
            manifest = json.loads(row[0])
        except (json.JSONDecodeError, TypeError) as exc:
            raise IndexCorruptError(f"Knowledge index has corrupt manifest JSON: {exc}") from exc
        if not isinstance(manifest, dict):
            raise IndexCorruptError("Knowledge index manifest is not a JSON object")
        return manifest

    @staticmethod
    def _validate_manifest(conn: sqlite3.Connection, manifest: dict) -> None:
        """Validate manifest compatibility and table record counts."""
        schema_ver = manifest.get("schema_version")
        if schema_ver != SCHEMA_VERSION:
            raise IndexIncompatibleError(
                f"Knowledge index schema version '{schema_ver}' != expected '{SCHEMA_VERSION}'"
            )

        declared_count = manifest.get("record_count")
        if not isinstance(declared_count, int):
            raise IndexCorruptError("Knowledge index manifest has non-integer record_count")

        for table_name in ("knowledge_records", "knowledge_fts"):
            actual_count = conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
            if actual_count != declared_count:
                raise IndexCorruptError(
                    f"Manifest declares {declared_count} records but "
                    f"{table_name} has {actual_count}"
                )

    def _connect(self) -> sqlite3.Connection:
        """Open a read-only connection to the index.

        :returns: A SQLite connection in read-only mode.
        :rtype: sqlite3.Connection
        """
        conn = sqlite3.connect(f"file:{self._path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    def search(
        self,
        query: str,
        *,
        limit: Optional[int] = None,
        filters: Optional[KnowledgeSearchFilters] = None,
    ) -> SearchResponse:
        """Search the knowledge index using FTS5 full-text search.

        :param query: FTS5 search query string.
        :type query: str
        :param limit: Maximum results to return (capped at 10).
        :type limit: Optional[int]
        :param filters: Optional structured applicability and classification filters.
        :type filters: Optional[KnowledgeSearchFilters]
        :returns: Search results with rank scores.
        :rtype: SearchResponse
        :raises InvalidQueryError: If query is empty, not a string, or
            contains malformed FTS5 syntax.
        :raises InvalidLimitError: If limit is not a positive integer.
        :raises InvalidFilterError: If a filter value is not recognized.
        """
        if not isinstance(query, str) or not query.strip():
            raise InvalidQueryError(f"Search query must be a non-empty string, got: {query!r}")

        effective_limit = self._validate_limit(limit)
        resolved_filters = filters or KnowledgeSearchFilters()
        self._validate_filters(resolved_filters)
        where_sql, params = self._build_search_predicate(query.strip(), resolved_filters)

        conn = self._connect()
        try:
            return self._execute_search(conn, where_sql, params, effective_limit)
        except sqlite3.OperationalError as exc:
            msg = str(exc).lower()
            is_fts_query_error = (
                "fts5: syntax error" in msg
                or "unterminated string" in msg
                or "unknown special query" in msg
                or ("no such column:" in msg and "fts5" in msg)
            )
            if is_fts_query_error:
                raise InvalidQueryError(f"Malformed FTS5 query expression: {exc}") from exc
            raise IndexCorruptError(
                f"Knowledge index operational failure during search: {exc}"
            ) from exc
        finally:
            conn.close()

    @classmethod
    def _execute_search(
        cls,
        conn: sqlite3.Connection,
        where_sql: str,
        params: list[object],
        limit: int,
    ) -> SearchResponse:
        """Execute count and result queries for a validated search."""
        count_sql = (
            "SELECT COUNT(*) "
            "FROM knowledge_fts f "
            "JOIN knowledge_records r ON r.rowid = f.rowid "
            f"WHERE {where_sql}"
        )
        total = conn.execute(count_sql, params).fetchone()[0]
        results_sql = (
            "SELECT r.id, r.name, r.description, r.kind, r.risk, "
            "r.provides, r.source_ref, rank "
            "FROM knowledge_fts f "
            "JOIN knowledge_records r ON r.rowid = f.rowid "
            f"WHERE {where_sql} "
            "ORDER BY rank ASC, r.id ASC "
            "LIMIT ?"
        )
        rows = conn.execute(results_sql, [*params, limit]).fetchall()
        return SearchResponse(results=cls._to_search_results(rows), total_matched=total)

    @staticmethod
    def _build_search_predicate(
        query: str,
        filters: KnowledgeSearchFilters,
    ) -> tuple[str, list[object]]:
        """Build a parameterized SQL predicate for a validated search."""
        clauses = ["f.knowledge_fts MATCH ?"]
        params: list[object] = [query]
        scalar_filters = (("kind", filters.kind), ("risk", filters.risk))
        for column, value in scalar_filters:
            if value is not None:
                clauses.append(f"r.{column} = ?")
                params.append(value)

        list_filters = (
            ("component", filters.component),
            ("os_family", filters.os_family),
            ("topology", filters.topology),
        )
        for column, value in list_filters:
            if value is not None:
                clauses.append(f"(',' || r.{column} || ',') LIKE ?")
                params.append(f"%,{value},%")
        return " AND ".join(clauses), params

    @staticmethod
    def _to_search_results(rows: list[sqlite3.Row]) -> tuple[SearchResult, ...]:
        """Convert search rows to immutable typed results."""
        return tuple(
            SearchResult(
                id=row["id"],
                name=row["name"],
                description=row["description"],
                kind=row["kind"],
                risk=row["risk"],
                provides=tuple(row["provides"].split(",")) if row["provides"] else (),
                source_ref=row["source_ref"],
                rank=row["rank"],
            )
            for row in rows
        )

    def get_by_id(self, record_id: str) -> Optional[KnowledgeRecord]:
        """Retrieve a single record by exact ID.

        :param record_id: The knowledge record ID to look up.
        :type record_id: str
        :returns: The full normalized record, or None if not found.
        :rtype: Optional[KnowledgeRecord]
        :raises InvalidQueryError: If record_id is empty or not a string.
        :raises IndexCorruptError: If stored record data cannot be
            deserialized into the schema.
        """
        if not isinstance(record_id, str) or not record_id.strip():
            raise InvalidQueryError(f"Record ID must be a non-empty string, got: {record_id!r}")

        conn = self._connect()
        try:
            row = conn.execute(
                """SELECT id, kind, name, description, provides, risk,
                          execution_ref, source_ref, source_hash,
                          component, os_family, topology, schema_version
                   FROM knowledge_records WHERE id = ?""",
                (record_id,),
            ).fetchone()

            if row is None:
                return None

            try:
                return KnowledgeRecord(
                    id=row["id"],
                    kind=KnowledgeKind(row["kind"]),
                    name=row["name"],
                    description=row["description"],
                    provides=(tuple(row["provides"].split(",")) if row["provides"] else ()),
                    risk=KnowledgeRisk(row["risk"]),
                    execution_ref=row["execution_ref"],
                    source_ref=row["source_ref"],
                    source_hash=row["source_hash"],
                    applies_to=AppliesTo(
                        component=(tuple(row["component"].split(",")) if row["component"] else ()),
                        os_family=(tuple(row["os_family"].split(",")) if row["os_family"] else ()),
                        topology=(tuple(row["topology"].split(",")) if row["topology"] else ()),
                    ),
                )
            except (ValueError, ValidationError) as exc:
                raise IndexCorruptError(
                    f"Record '{record_id}' in index has corrupt data: {exc}"
                ) from exc
        finally:
            conn.close()

    def get_manifest(self) -> dict:
        """Retrieve the build manifest from the index.

        :returns: The manifest dictionary.
        :rtype: dict
        :raises IndexCorruptError: If manifest is missing or corrupt.
        """
        conn = self._connect()
        try:
            return self._read_manifest(conn)
        finally:
            conn.close()

    @staticmethod
    def _validate_limit(limit: Optional[int]) -> int:
        """Validate and cap the result limit.

        :param limit: Caller-requested limit, or None for default.
        :type limit: Optional[int]
        :returns: Effective limit, capped at MAX_RESULTS.
        :rtype: int
        :raises InvalidLimitError: If limit is not a positive integer or
            is a bool.
        """
        if limit is None:
            return MAX_RESULTS
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise InvalidLimitError(f"Limit must be a positive integer, got: {limit!r}")
        return min(limit, MAX_RESULTS)

    @staticmethod
    def _validate_filters(filters: KnowledgeSearchFilters) -> None:
        """Validate that filter values are recognized vocabulary terms.

        :param filters: Structured search filters.
        :type filters: KnowledgeSearchFilters
        :raises InvalidFilterError: If a filter value is not recognized or
            not a valid lowercase slug.
        """
        if filters.kind is not None and filters.kind not in VALID_KINDS:
            raise InvalidFilterError(
                f"Invalid kind filter '{filters.kind}'. Valid values: {sorted(VALID_KINDS)}"
            )
        if filters.risk is not None and filters.risk not in VALID_RISKS:
            raise InvalidFilterError(
                f"Invalid risk filter '{filters.risk}'. Valid values: {sorted(VALID_RISKS)}"
            )
        for name, value in [
            ("component", filters.component),
            ("os_family", filters.os_family),
            ("topology", filters.topology),
        ]:
            if value is not None:
                if not isinstance(value, str) or not _SLUG_RE.match(value):
                    raise InvalidFilterError(
                        f"Invalid {name} filter '{value}': must be a "
                        f"lowercase slug (a-z, 0-9, hyphens only)"
                    )
