# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Deterministic SQLite FTS5 index builder for the STAF knowledge base.
"""

import hashlib
import json
import os
import re
import sqlite3
import tempfile
from pathlib import Path
from typing import List, Optional
from src.core.exceptions import BuildValidationError
from src.core.models.knowledge import SCHEMA_VERSION, KnowledgeRecord

_HA_GROUP_PATTERN = r"(?:HA_DB_HANA|HA_SCS|BACKUP_DB_HANA)"
_EXECUTION_REF_PATTERNS = (
    re.compile(r"^configuration-check:[A-Za-z0-9][A-Za-z0-9-]*$"),
    re.compile(rf"^ha-test:{_HA_GROUP_PATTERN}/[a-z0-9]+(?:-[a-z0-9]+)*$"),
)

_RECORDS_TABLE_DDL = """\
CREATE TABLE knowledge_records (
    id TEXT PRIMARY KEY NOT NULL,
    kind TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    provides TEXT NOT NULL,
    risk TEXT NOT NULL,
    execution_ref TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    component TEXT NOT NULL,
    os_family TEXT NOT NULL,
    topology TEXT NOT NULL,
    schema_version TEXT NOT NULL
);
"""

_FTS_TABLE_DDL = """\
CREATE VIRTUAL TABLE knowledge_fts USING fts5(
    id,
    name,
    description,
    provides,
    applicability,
    content=''
);
"""

_MANIFEST_TABLE_DDL = """\
CREATE TABLE build_manifest (
    key TEXT PRIMARY KEY NOT NULL,
    value TEXT NOT NULL
);
"""


def build_index(
    records: List[KnowledgeRecord],
    target_path: Path,
    *,
    source_root: Optional[Path] = None,
) -> dict:
    """Build the SQLite FTS5 knowledge index atomically.

    :param records: The complete set of normalized knowledge records to index.
    :type records: List[KnowledgeRecord]
    :param target_path: Destination file path for the generated index.
    :type target_path: pathlib.Path
    :param source_root: Root directory for authoritative source validation.
        Defaults to the repository root (three parents up from this file).
    :type source_root: Optional[pathlib.Path]
    :returns: The manifest dictionary written into the index.
    :rtype: dict
    :raises BuildValidationError: If validation fails (duplicate IDs,
        invalid source refs, non-opaque execution refs, source mismatch).
    """
    resolved_root = Path(source_root) if source_root is not None else _default_repo_root()
    _validate_records(records, resolved_root)
    manifest = _compute_manifest(records)

    target_path = Path(target_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        suffix=".db.tmp",
        dir=str(target_path.parent),
    )
    os.close(fd)

    try:
        _write_database(records, manifest, tmp_path)
        _validate_database(tmp_path, len(records), manifest)
        os.replace(tmp_path, str(target_path))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    return manifest


def _default_repo_root() -> Path:
    """Return the repository root derived from this file's location.

    :returns: Repository root path.
    :rtype: pathlib.Path
    """
    return Path(__file__).resolve().parents[4]


def _validate_records(records: List[KnowledgeRecord], source_root: Path) -> None:
    """Validate records before building.

    :param records: Records to validate.
    :type records: List[KnowledgeRecord]
    :param source_root: Root directory for source file validation.
    :type source_root: pathlib.Path
    :raises BuildValidationError: On duplicate IDs, invalid content, or
        source validation failure.
    """
    if not records:
        raise BuildValidationError("Cannot build index from empty record set")

    seen_ids: dict[str, str] = {}
    hash_by_path: dict[str, str] = {}
    resolved_root = source_root.resolve()

    for record in records:
        _register_record_id(record, seen_ids)
        path_part, source_file = _validate_source_ref(record, resolved_root)
        _validate_source_hash(record, path_part, source_file)
        _register_source_hash(record, path_part, hash_by_path)
        _validate_opaque_execution_ref(record)


def _register_record_id(record: KnowledgeRecord, seen_ids: dict[str, str]) -> None:
    """Reject duplicate record identifiers and register a unique record."""
    previous_source = seen_ids.get(record.id)
    if previous_source is not None:
        raise BuildValidationError(
            f"Duplicate record ID '{record.id}': appears in "
            f"'{record.source_ref}' and '{previous_source}'"
        )
    seen_ids[record.id] = record.source_ref


def _validate_source_ref(record: KnowledgeRecord, source_root: Path) -> tuple[str, Path]:
    """Validate a record source reference and resolve its source file."""
    if not record.source_ref or "#" not in record.source_ref:
        raise BuildValidationError(
            f"Record '{record.id}' has invalid source_ref "
            f"(missing '#' separator): '{record.source_ref}'"
        )

    path_part, anchor = record.source_ref.split("#", 1)
    if not path_part or not anchor:
        missing = "path" if not path_part else "anchor"
        raise BuildValidationError(
            f"Record '{record.id}' has empty {missing} in source_ref: '{record.source_ref}'"
        )
    if "\\" in path_part:
        raise BuildValidationError(
            f"Record '{record.id}' source_ref contains backslash: '{record.source_ref}'"
        )

    path_obj = Path(path_part)
    if path_obj.is_absolute():
        raise BuildValidationError(
            f"Record '{record.id}' source_ref is not relative: '{record.source_ref}'"
        )
    if ".." in path_obj.parts:
        raise BuildValidationError(
            f"Record '{record.id}' source_ref contains path traversal: '{record.source_ref}'"
        )

    source_file = (source_root / path_obj).resolve()
    try:
        source_file.relative_to(source_root)
    except ValueError as exc:
        raise BuildValidationError(
            f"Record '{record.id}' source file escapes source_root: "
            f"'{path_part}' resolves to '{source_file}' which is outside '{source_root}'"
        ) from exc
    if not source_file.is_file():
        raise BuildValidationError(
            f"Record '{record.id}' source file not found: "
            f"'{path_part}' (resolved: {source_file})"
        )
    return path_part, source_file


def _validate_source_hash(
    record: KnowledgeRecord,
    path_part: str,
    source_file: Path,
) -> None:
    """Verify one record's declared source hash against its source file."""
    if not record.source_hash.startswith("sha256:"):
        raise BuildValidationError(
            f"Record '{record.id}' has invalid source_hash format: '{record.source_hash}'"
        )
    actual_hash = f"sha256:{hashlib.sha256(source_file.read_bytes()).hexdigest()}"
    if record.source_hash != actual_hash:
        raise BuildValidationError(
            f"Record '{record.id}' source_hash mismatch for "
            f"'{path_part}': declared {record.source_hash}, actual {actual_hash}"
        )


def _register_source_hash(
    record: KnowledgeRecord,
    path_part: str,
    hash_by_path: dict[str, str],
) -> None:
    """Ensure all records from one source declare the same hash."""
    previous_hash = hash_by_path.get(path_part)
    if previous_hash is not None and previous_hash != record.source_hash:
        raise BuildValidationError(
            f"Conflicting source_hash for '{path_part}': "
            f"'{previous_hash}' vs '{record.source_hash}'"
        )
    hash_by_path[path_part] = record.source_hash


def _validate_opaque_execution_ref(record: KnowledgeRecord) -> None:
    """Ensure execution_ref is an opaque reference, not executable content.

    :param record: Record to validate.
    :type record: KnowledgeRecord
    :raises BuildValidationError: If execution_ref is outside the supported
        opaque-reference grammars.
    """
    ref = record.execution_ref
    if not any(pattern.fullmatch(ref) for pattern in _EXECUTION_REF_PATTERNS):
        raise BuildValidationError(
            f"Record '{record.id}' execution_ref contains non-opaque content: '{ref}'"
        )


def _compute_manifest(records: List[KnowledgeRecord]) -> dict:
    """Compute a deterministic manifest from the records.

    :param records: The complete record set.
    :type records: List[KnowledgeRecord]
    :returns: Manifest dictionary with schema_version, record_count,
        and sorted source entries with hashes.
    :rtype: dict
    """
    source_entries: dict = {}
    for record in records:
        path_part = record.source_ref.split("#", 1)[0]
        source_entries[path_part] = record.source_hash
    sorted_sources = [
        {"path": path, "hash": source_entries[path]} for path in sorted(source_entries.keys())
    ]

    return {
        "schema_version": SCHEMA_VERSION,
        "record_count": len(records),
        "sources": sorted_sources,
    }


def _write_database(
    records: List[KnowledgeRecord],
    manifest: dict,
    db_path: str,
) -> None:
    """Write the SQLite database with records and FTS index.

    :param records: Records to insert.
    :type records: List[KnowledgeRecord]
    :param manifest: Manifest to store.
    :type manifest: dict
    :param db_path: Path to the temporary database file.
    :type db_path: str
    """
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(_RECORDS_TABLE_DDL)
        conn.execute(_FTS_TABLE_DDL)
        conn.execute(_MANIFEST_TABLE_DDL)

        for record in sorted(records, key=lambda r: r.id):
            provides_str = ",".join(record.provides)
            component_str = ",".join(record.applies_to.component)
            os_family_str = ",".join(record.applies_to.os_family)
            topology_str = ",".join(record.applies_to.topology)

            conn.execute(
                """INSERT INTO knowledge_records
                   (id, kind, name, description, provides, risk,
                    execution_ref, source_ref, source_hash,
                    component, os_family, topology, schema_version)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    record.id,
                    record.kind,
                    record.name,
                    record.description,
                    provides_str,
                    record.risk,
                    record.execution_ref,
                    record.source_ref,
                    record.source_hash,
                    component_str,
                    os_family_str,
                    topology_str,
                    record.schema_version,
                ),
            )

            applicability_text = " ".join(
                record.applies_to.component
                + record.applies_to.os_family
                + record.applies_to.topology
            )
            conn.execute(
                """INSERT INTO knowledge_fts
                   (rowid, id, name, description, provides, applicability)
                   VALUES (
                       (SELECT rowid FROM knowledge_records WHERE id = ?),
                       ?, ?, ?, ?, ?
                   )""",
                (
                    record.id,
                    record.id,
                    record.name,
                    record.description,
                    provides_str,
                    applicability_text,
                ),
            )

        conn.execute(
            "INSERT INTO build_manifest (key, value) VALUES (?, ?)",
            ("manifest", json.dumps(manifest, sort_keys=True)),
        )

        conn.commit()
    finally:
        conn.close()


def _validate_database(db_path: str, expected_count: int, manifest: dict) -> None:
    """Validate the built database has correct record count and manifest.

    :param db_path: Path to the database to validate.
    :type db_path: str
    :param expected_count: Expected number of records.
    :type expected_count: int
    :param manifest: Expected manifest content.
    :type manifest: dict
    :raises BuildValidationError: If validation fails.
    """
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT COUNT(*) FROM knowledge_records").fetchone()
        if row[0] != expected_count:
            raise BuildValidationError(
                f"Database record count {row[0]} != expected {expected_count}"
            )

        fts_row = conn.execute("SELECT COUNT(*) FROM knowledge_fts").fetchone()
        if fts_row[0] != expected_count:
            raise BuildValidationError(f"FTS row count {fts_row[0]} != expected {expected_count}")

        manifest_row = conn.execute(
            "SELECT value FROM build_manifest WHERE key = 'manifest'"
        ).fetchone()
        if manifest_row is None:
            raise BuildValidationError("Manifest not found in database")

        stored_manifest = json.loads(manifest_row[0])
        if stored_manifest != manifest:
            raise BuildValidationError("Stored manifest does not match computed manifest")
    finally:
        conn.close()


def compute_manifest_hash(manifest: dict) -> str:
    """Compute a SHA-256 hash of the canonical manifest JSON.

    :param manifest: The manifest dictionary.
    :type manifest: dict
    :returns: Hex digest of the manifest's canonical JSON.
    :rtype: str
    """
    canonical = json.dumps(manifest, sort_keys=True).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()
