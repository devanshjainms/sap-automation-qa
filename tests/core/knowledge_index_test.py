# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Tests for the knowledge index builder and search API (P1-WP-007C).
All tests use disposable temp files — no repository or site-package shims.
"""

import hashlib
import json
import os
import sqlite3
from pathlib import Path
from typing import List
import pytest
from pytest_mock import MockerFixture
from src.core.exceptions import (
    BuildValidationError,
    IndexCorruptError,
    IndexIncompatibleError,
    IndexMissingError,
    InvalidFilterError,
    InvalidLimitError,
    InvalidQueryError,
)
from src.core.services.knowledge.extractors import extract_configuration_checks
from src.core.services.knowledge.ha_extractors import extract_ha_tests
from src.core.services.knowledge.index_builder import build_index, compute_manifest_hash
from src.core.models.knowledge import (
    AppliesTo,
    KnowledgeKind,
    KnowledgeRecord,
    KnowledgeRisk,
    KnowledgeSearchFilters,
    SCHEMA_VERSION,
)
from src.core.services.knowledge.search import KnowledgeIndex, MAX_RESULTS


def _write_source_file(base: Path, rel_path: str, content: bytes) -> str:
    """Write a source file under base and return its sha256 hash string.

    :param base: Root directory to write under.
    :type base: pathlib.Path
    :param rel_path: Forward-slash relative path.
    :type rel_path: str
    :param content: Raw file bytes.
    :type content: bytes
    :returns: The ``sha256:<hex>`` hash of content.
    :rtype: str
    """
    target = base / rel_path.replace("/", os.sep)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _make_record(
    record_id: str,
    source_root: Path,
    rel_path: str = "src/test.yml",
    content: bytes = b"test-content",
    anchor: str = "check1",
) -> KnowledgeRecord:
    """Create a record with a real on-disk source file.

    :param record_id: Knowledge record ID.
    :type record_id: str
    :param source_root: Root for the source file.
    :type source_root: pathlib.Path
    :param rel_path: Relative file path.
    :type rel_path: str
    :param content: File content bytes.
    :type content: bytes
    :param anchor: Anchor after '#' in source_ref.
    :type anchor: str
    :returns: A valid KnowledgeRecord.
    :rtype: KnowledgeRecord
    """
    source_hash = _write_source_file(source_root, rel_path, content)
    return KnowledgeRecord(
        id=record_id,
        kind=KnowledgeKind.DIAGNOSTIC_PROBE,
        name="Test Record",
        description="A test record for index builder tests",
        applies_to=AppliesTo(),
        provides=(),
        risk=KnowledgeRisk.READ_ONLY,
        execution_ref=f"configuration-check:{record_id}",
        source_ref=f"{rel_path}#{anchor}",
        source_hash=source_hash,
    )


@pytest.fixture(scope="module", name="all_records")
def _all_records_fixture() -> List[KnowledgeRecord]:
    """Extract the full 275-record set from real authoritative sources.

    :returns: Combined configuration-check and HA test records.
    :rtype: List[KnowledgeRecord]
    """
    config_records = extract_configuration_checks()
    ha_records = extract_ha_tests()
    return config_records + ha_records


@pytest.fixture(name="index_path")
def _index_path_fixture(tmp_path: Path) -> Path:
    """Provide a temporary path for an index file.

    :param tmp_path: Pytest temporary directory.
    :type tmp_path: pathlib.Path
    :returns: Path for the knowledge index database.
    :rtype: pathlib.Path
    """
    return tmp_path / "knowledge.db"


@pytest.fixture(name="built_index")
def _built_index_fixture(all_records: List[KnowledgeRecord], index_path: Path) -> Path:
    """Build a complete index and return its path.

    :param all_records: The full record set.
    :type all_records: List[KnowledgeRecord]
    :param index_path: Target path for the index.
    :type index_path: pathlib.Path
    :returns: Path to the built index.
    :rtype: pathlib.Path
    """
    build_index(all_records, index_path)
    return index_path


class TestKnowledgeIndex:
    """Test building the index from the full 275-record real dataset."""

    def test_build_produces_index_file(
        self, all_records: List[KnowledgeRecord], index_path: Path
    ) -> None:
        """The build produces a SQLite file at the target path.

        :param all_records: The full record set.
        :type all_records: List[KnowledgeRecord]
        :param index_path: Target path.
        :type index_path: pathlib.Path
        """
        build_index(all_records, index_path)
        assert index_path.exists()
        assert index_path.stat().st_size > 0

    def test_build_record_count_is_275(
        self, all_records: List[KnowledgeRecord], index_path: Path
    ) -> None:
        """The index contains exactly 275 records (235 config + 40 HA).

        :param all_records: The full record set.
        :type all_records: List[KnowledgeRecord]
        :param index_path: Target path.
        :type index_path: pathlib.Path
        """
        assert len(all_records) == 275
        manifest = build_index(all_records, index_path)
        assert manifest["record_count"] == 275

    def test_build_manifest_schema_version(
        self, all_records: List[KnowledgeRecord], index_path: Path
    ) -> None:
        """The manifest contains the current schema version.

        :param all_records: The full record set.
        :type all_records: List[KnowledgeRecord]
        :param index_path: Target path.
        :type index_path: pathlib.Path
        """
        manifest = build_index(all_records, index_path)
        assert manifest["schema_version"] == SCHEMA_VERSION

    def test_build_manifest_has_source_hashes(
        self, all_records: List[KnowledgeRecord], index_path: Path
    ) -> None:
        """The manifest includes sorted source paths with SHA-256 hashes.

        :param all_records: The full record set.
        :type all_records: List[KnowledgeRecord]
        :param index_path: Target path.
        :type index_path: pathlib.Path
        """
        manifest = build_index(all_records, index_path)
        assert "sources" in manifest
        assert len(manifest["sources"]) > 0
        for entry in manifest["sources"]:
            assert "path" in entry
            assert "hash" in entry
            assert entry["hash"].startswith("sha256:")
            assert len(entry["hash"]) == 71

    def test_build_manifest_sources_are_sorted(
        self, all_records: List[KnowledgeRecord], index_path: Path
    ) -> None:
        """Manifest sources are in sorted path order.

        :param all_records: The full record set.
        :type all_records: List[KnowledgeRecord]
        :param index_path: Target path.
        :type index_path: pathlib.Path
        """
        manifest = build_index(all_records, index_path)
        paths = [s["path"] for s in manifest["sources"]]
        assert paths == sorted(paths)

    def test_build_manifest_no_timestamps_or_machine_paths(
        self, all_records: List[KnowledgeRecord], index_path: Path
    ) -> None:
        """Manifest contains no timestamps, machine paths, or random IDs.

        :param all_records: The full record set.
        :type all_records: List[KnowledgeRecord]
        :param index_path: Target path.
        :type index_path: pathlib.Path
        """
        manifest = build_index(all_records, index_path)
        manifest_json = json.dumps(manifest)
        assert "C:\\" not in manifest_json
        assert "/home/" not in manifest_json
        assert "/Users/" not in manifest_json
        assert set(manifest.keys()) == {"schema_version", "record_count", "sources"}

    def test_manifest_is_byte_stable(
        self, all_records: List[KnowledgeRecord], tmp_path: Path
    ) -> None:
        """Two builds produce identical manifest hashes.

        :param all_records: The full record set.
        :type all_records: List[KnowledgeRecord]
        :param tmp_path: Pytest temporary directory.
        :type tmp_path: pathlib.Path
        """
        path1 = tmp_path / "index1.db"
        path2 = tmp_path / "index2.db"
        manifest1 = build_index(all_records, path1)
        manifest2 = build_index(all_records, path2)
        assert manifest1 == manifest2
        assert compute_manifest_hash(manifest1) == compute_manifest_hash(manifest2)

    def test_logical_content_identical(
        self, all_records: List[KnowledgeRecord], tmp_path: Path
    ) -> None:
        """Two builds produce identical query-visible records.

        :param all_records: The full record set.
        :type all_records: List[KnowledgeRecord]
        :param tmp_path: Pytest temporary directory.
        :type tmp_path: pathlib.Path
        """
        path1 = tmp_path / "index1.db"
        path2 = tmp_path / "index2.db"
        build_index(all_records, path1)
        build_index(all_records, path2)

        conn1 = sqlite3.connect(str(path1))
        conn2 = sqlite3.connect(str(path2))
        try:
            rows1 = conn1.execute("SELECT * FROM knowledge_records ORDER BY id").fetchall()
            rows2 = conn2.execute("SELECT * FROM knowledge_records ORDER BY id").fetchall()
            assert rows1 == rows2
        finally:
            conn1.close()
            conn2.close()

    def test_prior_index_preserved_on_validation_failure(self, tmp_path: Path) -> None:
        """A failed build (duplicate IDs) does not destroy existing index.

        :param tmp_path: Pytest temporary directory.
        :type tmp_path: pathlib.Path
        """
        source_root = tmp_path / "sources"
        index_path = tmp_path / "knowledge.db"

        record = _make_record("test.valid-record", source_root)
        build_index([record], index_path, source_root=source_root)
        original_content = index_path.read_bytes()
        assert len(original_content) > 0

        dup_records = [record, record]
        with pytest.raises(BuildValidationError, match="Duplicate"):
            build_index(dup_records, index_path, source_root=source_root)

        assert index_path.exists()
        assert index_path.read_bytes() == original_content

    def test_prior_index_preserved_when_replace_fails(
        self, tmp_path: Path, mocker: MockerFixture
    ) -> None:
        """If os.replace fails, the prior valid target is untouched.

        :param tmp_path: Pytest temporary directory.
        :type tmp_path: pathlib.Path
        :param mocker: Pytest mock fixture.
        :type mocker: pytest_mock.MockerFixture
        """
        source_root = tmp_path / "sources"
        index_path = tmp_path / "knowledge.db"

        record = _make_record("test.original", source_root)
        build_index([record], index_path, source_root=source_root)
        original_content = index_path.read_bytes()

        record2 = _make_record(
            "test.replacement",
            source_root,
            rel_path="src/other.yml",
            content=b"other-content",
        )
        mock_replace = mocker.patch("src.core.services.knowledge.index_builder.os.replace")
        mock_replace.side_effect = OSError("simulated replace failure")
        with pytest.raises(OSError, match="simulated replace failure"):
            build_index([record2], index_path, source_root=source_root)

        assert index_path.read_bytes() == original_content

    def test_temp_file_cleaned_on_failure(self, tmp_path: Path) -> None:
        """Failed builds do not leave temporary files behind.

        :param tmp_path: Pytest temporary directory.
        :type tmp_path: pathlib.Path
        """
        source_root = tmp_path / "sources"
        record = _make_record("test.valid-record", source_root)
        index_path = tmp_path / "knowledge.db"
        dup_records = [record, record]

        files_before = set(tmp_path.iterdir())
        with pytest.raises(BuildValidationError):
            build_index(dup_records, index_path, source_root=source_root)
        files_after = set(tmp_path.iterdir())
        new_files = files_after - files_before
        assert not any(f.suffix in (".tmp", ".db") for f in new_files)

    def test_basic_search_returns_results(self, built_index: Path) -> None:
        """A search for a known term returns results.

        :param built_index: Path to built index.
        :type built_index: pathlib.Path
        """
        idx = KnowledgeIndex(built_index)
        response = idx.search("HANA")
        assert response.total_matched > 0
        assert len(response.results) > 0

    def test_search_results_have_typed_fields(self, built_index: Path) -> None:
        """Search results include all expected fields.

        :param built_index: Path to built index.
        :type built_index: pathlib.Path
        """
        idx = KnowledgeIndex(built_index)
        response = idx.search("HANA")
        result = response.results[0]
        assert result.id
        assert result.name
        assert result.description
        assert result.kind
        assert result.risk
        assert isinstance(result.provides, tuple)
        assert result.source_ref
        assert isinstance(result.rank, float)

    def test_search_no_executable_content_in_results(self, built_index: Path) -> None:
        """Search results never contain executable content.

        :param built_index: Path to built index.
        :type built_index: pathlib.Path
        """
        idx = KnowledgeIndex(built_index)
        response = idx.search("check")
        for result in response.results:
            assert "sudo" not in result.id
            assert "/bin/" not in result.id
            assert "|" not in result.id

    def test_unmatched_quote_raises_invalid_query(self, built_index: Path) -> None:
        """An unmatched quote in the query raises InvalidQueryError.

        :param built_index: Path to built index.
        :type built_index: pathlib.Path
        """
        idx = KnowledgeIndex(built_index)
        with pytest.raises(InvalidQueryError, match="[Mm]alformed"):
            idx.search('"unmatched quote')

    def test_invalid_fts_operator_raises_invalid_query(self, built_index: Path) -> None:
        """Invalid FTS5 operator syntax raises InvalidQueryError.

        :param built_index: Path to built index.
        :type built_index: pathlib.Path
        """
        idx = KnowledgeIndex(built_index)
        with pytest.raises(InvalidQueryError, match="[Mm]alformed"):
            idx.search("AND OR NOT")

    def test_damaged_table_raises_index_corrupt(self, built_index: Path) -> None:
        """Dropping a table after open causes IndexCorruptError on search.

        :param built_index: Path to built index.
        :type built_index: pathlib.Path
        """
        idx = KnowledgeIndex(built_index)
        conn = sqlite3.connect(str(built_index))
        conn.execute("DROP TABLE knowledge_records")
        conn.commit()
        conn.close()

        with pytest.raises(IndexCorruptError):
            idx.search("HANA")

    def test_renamed_column_raises_index_corrupt(self, built_index: Path) -> None:
        """Renaming a records column after open causes IndexCorruptError.

        :param built_index: Path to built index.
        :type built_index: pathlib.Path
        """
        idx = KnowledgeIndex(built_index)
        conn = sqlite3.connect(str(built_index))
        conn.execute("ALTER TABLE knowledge_records RENAME COLUMN kind TO kind_broken")
        conn.commit()
        conn.close()

        with pytest.raises(IndexCorruptError):
            idx.search("HANA")

    def test_results_ordered_by_rank_then_id(self, built_index: Path) -> None:
        """Results are ordered by rank (ascending) then id (ascending).

        :param built_index: Path to built index.
        :type built_index: pathlib.Path
        """
        idx = KnowledgeIndex(built_index)
        response = idx.search("configuration")
        if len(response.results) > 1:
            for i in range(len(response.results) - 1):
                curr = response.results[i]
                nxt = response.results[i + 1]
                assert (curr.rank, curr.id) <= (nxt.rank, nxt.id)

    def test_deterministic_across_repeated_searches(self, built_index: Path) -> None:
        """Repeated identical searches return identical results.

        :param built_index: Path to built index.
        :type built_index: pathlib.Path
        """
        idx = KnowledgeIndex(built_index)
        response1 = idx.search("replication")
        response2 = idx.search("replication")
        assert response1 == response2

    def test_default_limit_is_10(self, built_index: Path) -> None:
        """Without explicit limit, returns at most 10 results.

        :param built_index: Path to built index.
        :type built_index: pathlib.Path
        """
        idx = KnowledgeIndex(built_index)
        response = idx.search("check")
        assert len(response.results) <= MAX_RESULTS
        assert MAX_RESULTS == 10

    def test_limit_above_10_capped(self, built_index: Path) -> None:
        """A limit > 10 is silently capped to 10.

        :param built_index: Path to built index.
        :type built_index: pathlib.Path
        """
        idx = KnowledgeIndex(built_index)
        response = idx.search("check", limit=100)
        assert len(response.results) <= 10

    def test_limit_below_10_honored(self, built_index: Path) -> None:
        """A limit < 10 is honored.

        :param built_index: Path to built index.
        :type built_index: pathlib.Path
        """
        idx = KnowledgeIndex(built_index)
        response = idx.search("check", limit=3)
        assert len(response.results) <= 3

    def test_total_matched_exceeds_limit(self, built_index: Path) -> None:
        """total_matched reflects all matches, not just returned ones.

        :param built_index: Path to built index.
        :type built_index: pathlib.Path
        """
        idx = KnowledgeIndex(built_index)
        response = idx.search("check", limit=2)
        assert response.total_matched > 2

    def test_bool_limit_rejected(self, built_index: Path) -> None:
        """A boolean limit raises InvalidLimitError.

        :param built_index: Path to built index.
        :type built_index: pathlib.Path
        """
        idx = KnowledgeIndex(built_index)
        with pytest.raises(InvalidLimitError):
            idx.search("check", limit=True)

    def test_filter_by_kind(self, built_index: Path) -> None:
        """Filtering by kind returns only matching records.

        :param built_index: Path to built index.
        :type built_index: pathlib.Path
        """
        idx = KnowledgeIndex(built_index)
        response = idx.search("test", filters=KnowledgeSearchFilters(kind="ha-functional-test"))
        for result in response.results:
            assert result.kind == "ha-functional-test"

    def test_filter_by_risk(self, built_index: Path) -> None:
        """Filtering by risk returns only matching records.

        :param built_index: Path to built index.
        :type built_index: pathlib.Path
        """
        idx = KnowledgeIndex(built_index)
        response = idx.search("check", filters=KnowledgeSearchFilters(risk="read-only"))
        for result in response.results:
            assert result.risk == "read-only"

    def test_filter_by_component(self, built_index: Path) -> None:
        """Filtering by component returns only matching records.

        :param built_index: Path to built index.
        :type built_index: pathlib.Path
        """
        idx = KnowledgeIndex(built_index)
        response = idx.search("check", filters=KnowledgeSearchFilters(component="hana"))
        assert response.total_matched > 0
        for result in response.results:
            record = idx.get_by_id(result.id)
            assert record is not None
            applies_to = record.model_dump()["applies_to"]
            assert "hana" in applies_to["component"]

    def test_filter_by_os_family(self, built_index: Path) -> None:
        """Filtering by os_family returns only matching records.

        :param built_index: Path to built index.
        :type built_index: pathlib.Path
        """
        idx = KnowledgeIndex(built_index)
        response = idx.search("check", filters=KnowledgeSearchFilters(os_family="suse"))
        assert response.total_matched > 0
        for result in response.results:
            record = idx.get_by_id(result.id)
            assert record is not None
            applies_to = record.model_dump()["applies_to"]
            assert "suse" in applies_to["os_family"]

    def test_filter_by_topology(self, built_index: Path) -> None:
        """Filtering by topology returns only matching records.

        :param built_index: Path to built index.
        :type built_index: pathlib.Path
        """
        idx = KnowledgeIndex(built_index)
        response = idx.search("scale", filters=KnowledgeSearchFilters(topology="scale-up"))
        if response.total_matched > 0:
            for result in response.results:
                record = idx.get_by_id(result.id)
                assert record is not None
                applies_to = record.model_dump()["applies_to"]
                assert "scale-up" in applies_to["topology"]

    def test_combined_filters(self, built_index: Path) -> None:
        """Multiple filters are applied conjunctively.

        :param built_index: Path to built index.
        :type built_index: pathlib.Path
        """
        idx = KnowledgeIndex(built_index)
        response = idx.search(
            "check",
            filters=KnowledgeSearchFilters(kind="diagnostic-probe", risk="read-only"),
        )
        for result in response.results:
            assert result.kind == "diagnostic-probe"
            assert result.risk == "read-only"

    def test_wildcard_in_component_filter_rejected(self, built_index: Path) -> None:
        """LIKE wildcards in component filter are rejected.

        :param built_index: Path to built index.
        :type built_index: pathlib.Path
        """
        idx = KnowledgeIndex(built_index)
        with pytest.raises(InvalidFilterError):
            idx.search("check", filters=KnowledgeSearchFilters(component="han%"))

    def test_underscore_in_os_family_filter_rejected(self, built_index: Path) -> None:
        """Underscores (LIKE single-char wildcard) are rejected.

        :param built_index: Path to built index.
        :type built_index: pathlib.Path
        """
        idx = KnowledgeIndex(built_index)
        with pytest.raises(InvalidFilterError):
            idx.search("check", filters=KnowledgeSearchFilters(os_family="sus_"))

    def test_uppercase_topology_filter_rejected(self, built_index: Path) -> None:
        """Uppercase values in topology filter are rejected.

        :param built_index: Path to built index.
        :type built_index: pathlib.Path
        """
        idx = KnowledgeIndex(built_index)
        with pytest.raises(InvalidFilterError):
            idx.search("check", filters=KnowledgeSearchFilters(topology="Scale-Up"))

    def test_get_existing_record(self, built_index: Path) -> None:
        """Get an existing record by its exact ID.

        :param built_index: Path to built index.
        :type built_index: pathlib.Path
        """
        idx = KnowledgeIndex(built_index)
        response = idx.search("HANA")
        assert response.total_matched > 0
        record_id = response.results[0].id
        record = idx.get_by_id(record_id)
        assert record is not None
        assert record.id == record_id
        assert isinstance(record, KnowledgeRecord)

    def test_get_nonexistent_record_returns_none(self, built_index: Path) -> None:
        """Getting a non-existent ID returns None (not an error).

        :param built_index: Path to built index.
        :type built_index: pathlib.Path
        """
        idx = KnowledgeIndex(built_index)
        record = idx.get_by_id("nonexistent.record.id")
        assert record is None

    def test_get_returns_full_record_fields(self, built_index: Path) -> None:
        """Retrieved record has all schema fields populated.

        :param built_index: Path to built index.
        :type built_index: pathlib.Path
        """
        idx = KnowledgeIndex(built_index)
        response = idx.search("check")
        record = idx.get_by_id(response.results[0].id)
        assert record is not None
        assert record.schema_version == SCHEMA_VERSION
        assert record.id
        assert record.kind in [e.value for e in KnowledgeKind]
        assert record.name
        assert record.description
        assert record.risk in [e.value for e in KnowledgeRisk]
        assert record.execution_ref
        assert record.source_ref
        assert str(record.source_hash).startswith("sha256:")

    def test_get_record_no_executable_content(self, built_index: Path) -> None:
        """Retrieved records contain no executable content.

        :param built_index: Path to built index.
        :type built_index: pathlib.Path
        """
        idx = KnowledgeIndex(built_index)
        response = idx.search("check", limit=10)
        for result in response.results:
            record = idx.get_by_id(result.id)
            assert record is not None
            assert "|" not in record.execution_ref
            assert "sudo" not in record.execution_ref
            assert "/bin/" not in record.execution_ref

    def test_missing_index_raises(self, tmp_path: Path) -> None:
        """Opening a non-existent index raises IndexMissingError.

        :param tmp_path: Pytest temporary directory.
        :type tmp_path: pathlib.Path
        """
        with pytest.raises(IndexMissingError):
            KnowledgeIndex(tmp_path / "does_not_exist.db")

    def test_corrupt_index_raises(self, tmp_path: Path) -> None:
        """Opening a corrupt file raises IndexCorruptError.

        :param tmp_path: Pytest temporary directory.
        :type tmp_path: pathlib.Path
        """
        corrupt_path = tmp_path / "corrupt.db"
        corrupt_path.write_text("this is not a sqlite database")
        with pytest.raises(IndexCorruptError):
            KnowledgeIndex(corrupt_path)

    def test_incompatible_schema_raises(self, tmp_path: Path) -> None:
        """An index with wrong schema version raises IndexIncompatibleError.

        :param tmp_path: Pytest temporary directory.
        :type tmp_path: pathlib.Path
        """
        db_path = tmp_path / "wrong_version.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "CREATE TABLE knowledge_records (id TEXT PRIMARY KEY, "
            "kind TEXT, name TEXT, description TEXT, provides TEXT, "
            "risk TEXT, execution_ref TEXT, source_ref TEXT, "
            "source_hash TEXT, component TEXT, os_family TEXT, "
            "topology TEXT, schema_version TEXT)"
        )
        conn.execute(
            "CREATE VIRTUAL TABLE knowledge_fts USING fts5("
            "id, name, description, provides, applicability, content='')"
        )
        conn.execute("CREATE TABLE build_manifest (key TEXT PRIMARY KEY, value TEXT)")
        bad_manifest = json.dumps({"schema_version": "99.0", "record_count": 0, "sources": []})
        conn.execute(
            "INSERT INTO build_manifest (key, value) VALUES ('manifest', ?)",
            (bad_manifest,),
        )
        conn.commit()
        conn.close()

        with pytest.raises(IndexIncompatibleError):
            KnowledgeIndex(db_path)

    def test_corrupt_manifest_json_raises_corrupt(self, tmp_path: Path) -> None:
        """Malformed manifest JSON raises IndexCorruptError not JSONError.

        :param tmp_path: Pytest temporary directory.
        :type tmp_path: pathlib.Path
        """
        db_path = tmp_path / "bad_json.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "CREATE TABLE knowledge_records (id TEXT PRIMARY KEY, "
            "kind TEXT, name TEXT, description TEXT, provides TEXT, "
            "risk TEXT, execution_ref TEXT, source_ref TEXT, "
            "source_hash TEXT, component TEXT, os_family TEXT, "
            "topology TEXT, schema_version TEXT)"
        )
        conn.execute(
            "CREATE VIRTUAL TABLE knowledge_fts USING fts5("
            "id, name, description, provides, applicability, content='')"
        )
        conn.execute("CREATE TABLE build_manifest (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute(
            "INSERT INTO build_manifest (key, value) VALUES (?, ?)",
            ("manifest", "{not valid json |||}"),
        )
        conn.commit()
        conn.close()

        with pytest.raises(IndexCorruptError, match="corrupt manifest"):
            KnowledgeIndex(db_path)

    def test_record_count_mismatch_raises_corrupt(self, tmp_path: Path) -> None:
        """Manifest record_count not matching actual rows is corrupt.

        :param tmp_path: Pytest temporary directory.
        :type tmp_path: pathlib.Path
        """
        db_path = tmp_path / "count_mismatch.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "CREATE TABLE knowledge_records (id TEXT PRIMARY KEY, "
            "kind TEXT, name TEXT, description TEXT, provides TEXT, "
            "risk TEXT, execution_ref TEXT, source_ref TEXT, "
            "source_hash TEXT, component TEXT, os_family TEXT, "
            "topology TEXT, schema_version TEXT)"
        )
        conn.execute(
            "CREATE VIRTUAL TABLE knowledge_fts USING fts5("
            "id, name, description, provides, applicability, content='')"
        )
        conn.execute("CREATE TABLE build_manifest (key TEXT PRIMARY KEY, value TEXT)")
        # Declare 10 records but table has 0
        manifest = json.dumps({"schema_version": SCHEMA_VERSION, "record_count": 10, "sources": []})
        conn.execute(
            "INSERT INTO build_manifest (key, value) VALUES ('manifest', ?)",
            (manifest,),
        )
        conn.commit()
        conn.close()

        with pytest.raises(IndexCorruptError, match="declares.*records"):
            KnowledgeIndex(db_path)

    def test_corrupt_record_enum_raises_corrupt(self, tmp_path: Path) -> None:
        """Invalid enum stored in a record raises IndexCorruptError.

        :param tmp_path: Pytest temporary directory.
        :type tmp_path: pathlib.Path
        """
        db_path = tmp_path / "bad_enum.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "CREATE TABLE knowledge_records (id TEXT PRIMARY KEY, "
            "kind TEXT, name TEXT, description TEXT, provides TEXT, "
            "risk TEXT, execution_ref TEXT, source_ref TEXT, "
            "source_hash TEXT, component TEXT, os_family TEXT, "
            "topology TEXT, schema_version TEXT)"
        )
        conn.execute(
            "CREATE VIRTUAL TABLE knowledge_fts USING fts5("
            "id, name, description, provides, applicability, content='')"
        )
        conn.execute("CREATE TABLE build_manifest (key TEXT PRIMARY KEY, value TEXT)")
        # Insert a record with invalid kind
        conn.execute(
            "INSERT INTO knowledge_records VALUES "
            "('test.bad', 'NOT_A_KIND', 'n', 'd', '', "
            "'read-only', 'ref:x', 'p#a', 'sha256:aa', '', '', '', '1.0')"
        )
        conn.execute(
            "INSERT INTO knowledge_fts (rowid, id, name, description, "
            "provides, applicability) VALUES (1, 'test.bad', 'n', 'd', '', '')"
        )
        manifest = json.dumps({"schema_version": SCHEMA_VERSION, "record_count": 1, "sources": []})
        conn.execute(
            "INSERT INTO build_manifest (key, value) VALUES ('manifest', ?)",
            (manifest,),
        )
        conn.commit()
        conn.close()

        idx = KnowledgeIndex(db_path)
        with pytest.raises(IndexCorruptError, match="corrupt data"):
            idx.get_by_id("test.bad")

    def test_get_manifest_missing_raises_corrupt(self, tmp_path: Path) -> None:
        """get_manifest raises IndexCorruptError if manifest row missing.

        :param tmp_path: Pytest temporary directory.
        :type tmp_path: pathlib.Path
        """
        source_root = tmp_path / "sources"
        db_path = tmp_path / "knowledge.db"
        record = _make_record("test.rec", source_root)
        build_index([record], db_path, source_root=source_root)

        conn = sqlite3.connect(str(db_path))
        conn.execute("DELETE FROM build_manifest")
        conn.execute(
            "UPDATE build_manifest SET value = ? WHERE key = 'manifest'",
            (json.dumps({"schema_version": SCHEMA_VERSION, "record_count": 1, "sources": []}),),
        )
        conn.commit()
        conn.close()

        db_path2 = tmp_path / "knowledge2.db"
        build_index([record], db_path2, source_root=source_root)
        idx = KnowledgeIndex(db_path2)

        # Now corrupt the manifest in place
        conn = sqlite3.connect(str(db_path2))
        conn.execute("DELETE FROM build_manifest")
        conn.commit()
        conn.close()

        with pytest.raises(IndexCorruptError, match="missing manifest"):
            idx.get_manifest()

    def test_empty_query_raises(self, built_index: Path) -> None:
        """An empty search query raises InvalidQueryError.

        :param built_index: Path to built index.
        :type built_index: pathlib.Path
        """
        idx = KnowledgeIndex(built_index)
        with pytest.raises(InvalidQueryError):
            idx.search("")

    def test_whitespace_query_raises(self, built_index: Path) -> None:
        """A whitespace-only query raises InvalidQueryError.

        :param built_index: Path to built index.
        :type built_index: pathlib.Path
        """
        idx = KnowledgeIndex(built_index)
        with pytest.raises(InvalidQueryError):
            idx.search("   ")

    def test_invalid_limit_zero_raises(self, built_index: Path) -> None:
        """A limit of 0 raises InvalidLimitError.

        :param built_index: Path to built index.
        :type built_index: pathlib.Path
        """
        idx = KnowledgeIndex(built_index)
        with pytest.raises(InvalidLimitError):
            idx.search("check", limit=0)

    def test_invalid_limit_negative_raises(self, built_index: Path) -> None:
        """A negative limit raises InvalidLimitError.

        :param built_index: Path to built index.
        :type built_index: pathlib.Path
        """
        idx = KnowledgeIndex(built_index)
        with pytest.raises(InvalidLimitError):
            idx.search("check", limit=-5)

    def test_invalid_kind_filter_raises(self, built_index: Path) -> None:
        """An unrecognized kind filter raises InvalidFilterError.

        :param built_index: Path to built index.
        :type built_index: pathlib.Path
        """
        idx = KnowledgeIndex(built_index)
        with pytest.raises(InvalidFilterError):
            idx.search("check", filters=KnowledgeSearchFilters(kind="not-a-real-kind"))

    def test_invalid_risk_filter_raises(self, built_index: Path) -> None:
        """An unrecognized risk filter raises InvalidFilterError.

        :param built_index: Path to built index.
        :type built_index: pathlib.Path
        """
        idx = KnowledgeIndex(built_index)
        with pytest.raises(InvalidFilterError):
            idx.search("check", filters=KnowledgeSearchFilters(risk="not-a-real-risk"))

    def test_empty_component_filter_raises(self, built_index: Path) -> None:
        """An empty component filter raises InvalidFilterError.

        :param built_index: Path to built index.
        :type built_index: pathlib.Path
        """
        idx = KnowledgeIndex(built_index)
        with pytest.raises(InvalidFilterError):
            idx.search("check", filters=KnowledgeSearchFilters(component=""))

    def test_empty_record_id_raises(self, built_index: Path) -> None:
        """An empty record ID raises InvalidQueryError.

        :param built_index: Path to built index.
        :type built_index: pathlib.Path
        """
        idx = KnowledgeIndex(built_index)
        with pytest.raises(InvalidQueryError):
            idx.get_by_id("")

    def test_duplicate_ids_rejected(self, tmp_path: Path) -> None:
        """Duplicate record IDs cause BuildValidationError.

        :param tmp_path: Pytest temporary directory.
        :type tmp_path: pathlib.Path
        """
        source_root = tmp_path / "sources"
        record = _make_record("test.duplicate", source_root)
        with pytest.raises(BuildValidationError, match="Duplicate"):
            build_index([record, record], tmp_path / "index.db", source_root=source_root)

    def test_empty_records_rejected(self, tmp_path: Path) -> None:
        """An empty record list causes BuildValidationError.

        :param tmp_path: Pytest temporary directory.
        :type tmp_path: pathlib.Path
        """
        with pytest.raises(BuildValidationError, match="empty"):
            build_index([], tmp_path / "index.db", source_root=tmp_path)

    def test_non_opaque_execution_ref_rejected(self, tmp_path: Path) -> None:
        """An execution_ref with shell content causes BuildValidationError.

        :param tmp_path: Pytest temporary directory.
        :type tmp_path: pathlib.Path
        """
        source_root = tmp_path / "sources"
        source_hash = _write_source_file(source_root, "src/file.yml", b"content")
        record = KnowledgeRecord(
            id="test.shell-ref",
            kind=KnowledgeKind.DIAGNOSTIC_PROBE,
            name="Bad ref test",
            description="Has a shell command in execution_ref",
            applies_to=AppliesTo(),
            provides=(),
            risk=KnowledgeRisk.READ_ONLY,
            execution_ref="sudo /bin/bash -c 'echo hello'",
            source_ref="src/file.yml#check1",
            source_hash=source_hash,
        )
        with pytest.raises(BuildValidationError, match="non-opaque"):
            build_index([record], tmp_path / "index.db", source_root=source_root)

    def test_missing_source_file_rejected(self, tmp_path: Path) -> None:
        """A source_ref pointing to a non-existent file is rejected.

        :param tmp_path: Pytest temporary directory.
        :type tmp_path: pathlib.Path
        """
        source_root = tmp_path / "sources"
        source_root.mkdir()
        record = KnowledgeRecord(
            id="test.missing-file",
            kind=KnowledgeKind.DIAGNOSTIC_PROBE,
            name="Missing file test",
            description="Source file does not exist",
            applies_to=AppliesTo(),
            provides=(),
            risk=KnowledgeRisk.READ_ONLY,
            execution_ref="configuration-check:test",
            source_ref="src/nonexistent.yml#check1",
            source_hash="sha256:" + "a" * 64,
        )
        with pytest.raises(BuildValidationError, match="not found"):
            build_index([record], tmp_path / "index.db", source_root=source_root)

    def test_path_traversal_rejected(self, tmp_path: Path) -> None:
        """A source_ref with '..' path traversal is rejected.

        :param tmp_path: Pytest temporary directory.
        :type tmp_path: pathlib.Path
        """
        source_root = tmp_path / "sources"
        source_root.mkdir()
        record = KnowledgeRecord(
            id="test.traversal",
            kind=KnowledgeKind.DIAGNOSTIC_PROBE,
            name="Traversal test",
            description="Path traversal in source_ref",
            applies_to=AppliesTo(),
            provides=(),
            risk=KnowledgeRisk.READ_ONLY,
            execution_ref="configuration-check:test",
            source_ref="../etc/passwd#check1",
            source_hash="sha256:" + "a" * 64,
        )
        with pytest.raises(BuildValidationError, match="traversal"):
            build_index([record], tmp_path / "index.db", source_root=source_root)

    def test_hash_mismatch_rejected(self, tmp_path: Path) -> None:
        """A source_hash that doesn't match actual file bytes is rejected.

        :param tmp_path: Pytest temporary directory.
        :type tmp_path: pathlib.Path
        """
        source_root = tmp_path / "sources"
        _write_source_file(source_root, "src/test.yml", b"actual content")
        record = KnowledgeRecord(
            id="test.hash-mismatch",
            kind=KnowledgeKind.DIAGNOSTIC_PROBE,
            name="Hash mismatch test",
            description="Declared hash does not match file content",
            applies_to=AppliesTo(),
            provides=(),
            risk=KnowledgeRisk.READ_ONLY,
            execution_ref="configuration-check:test",
            source_ref="src/test.yml#check1",
            source_hash="sha256:" + "f" * 64,
        )
        with pytest.raises(BuildValidationError, match="mismatch"):
            build_index([record], tmp_path / "index.db", source_root=source_root)

    def test_empty_anchor_rejected(self, tmp_path: Path) -> None:
        """A source_ref with empty anchor (trailing #) is rejected.

        :param tmp_path: Pytest temporary directory.
        :type tmp_path: pathlib.Path
        """
        source_root = tmp_path / "sources"
        source_hash = _write_source_file(source_root, "src/test.yml", b"content")
        record = KnowledgeRecord(
            id="test.empty-anchor",
            kind=KnowledgeKind.DIAGNOSTIC_PROBE,
            name="Empty anchor test",
            description="Source ref has empty anchor after hash",
            applies_to=AppliesTo(),
            provides=(),
            risk=KnowledgeRisk.READ_ONLY,
            execution_ref="configuration-check:test",
            source_ref="src/test.yml#",
            source_hash=source_hash,
        )
        with pytest.raises(BuildValidationError, match="empty anchor"):
            build_index([record], tmp_path / "index.db", source_root=source_root)

    def test_conflicting_hashes_for_same_path_rejected(self, tmp_path: Path) -> None:
        """Two records referencing same file with different hashes are rejected.

        :param tmp_path: Pytest temporary directory.
        :type tmp_path: pathlib.Path
        """
        source_root = tmp_path / "sources"
        real_hash = _write_source_file(source_root, "src/shared.yml", b"shared content")
        record1 = KnowledgeRecord(
            id="test.rec-one",
            kind=KnowledgeKind.DIAGNOSTIC_PROBE,
            name="Record One",
            description="First record referencing shared file",
            applies_to=AppliesTo(),
            provides=(),
            risk=KnowledgeRisk.READ_ONLY,
            execution_ref="configuration-check:rec-one",
            source_ref="src/shared.yml#check1",
            source_hash=real_hash,
        )
        # Second record claims a different hash for the same file
        record2 = KnowledgeRecord(
            id="test.rec-two",
            kind=KnowledgeKind.DIAGNOSTIC_PROBE,
            name="Record Two",
            description="Second record with wrong hash for same file",
            applies_to=AppliesTo(),
            provides=(),
            risk=KnowledgeRisk.READ_ONLY,
            execution_ref="configuration-check:rec-two",
            source_ref="src/shared.yml#check2",
            source_hash="sha256:" + "0" * 64,
        )
        # The second record will fail on hash mismatch (actual != declared)
        with pytest.raises(BuildValidationError, match="mismatch"):
            build_index(
                [record1, record2],
                tmp_path / "index.db",
                source_root=source_root,
            )

    def test_backslash_in_source_ref_rejected(self, tmp_path: Path) -> None:
        """A source_ref containing backslash is rejected.

        :param tmp_path: Pytest temporary directory.
        :type tmp_path: pathlib.Path
        """
        source_root = tmp_path / "sources"
        source_root.mkdir()
        record = KnowledgeRecord(
            id="test.backslash",
            kind=KnowledgeKind.DIAGNOSTIC_PROBE,
            name="Backslash test",
            description="Backslash in source_ref path",
            applies_to=AppliesTo(),
            provides=(),
            risk=KnowledgeRisk.READ_ONLY,
            execution_ref="configuration-check:test",
            source_ref="src\\..\\etc\\passwd#check1",
            source_hash="sha256:" + "a" * 64,
        )
        with pytest.raises(BuildValidationError, match="backslash"):
            build_index([record], tmp_path / "index.db", source_root=source_root)

    def test_symlink_escape_rejected(self, tmp_path: Path) -> None:
        """A symlink pointing outside source_root is rejected.

        :param tmp_path: Pytest temporary directory.
        :type tmp_path: pathlib.Path
        """
        source_root = tmp_path / "sources"
        source_root.mkdir()
        (source_root / "src").mkdir()

        outside = tmp_path / "outside"
        outside.mkdir()
        secret = outside / "secret.yml"
        secret.write_bytes(b"secret content")
        link_path = source_root / "src" / "escape.yml"
        try:
            link_path.symlink_to(secret)
        except OSError:
            pytest.skip("Cannot create symlinks (insufficient privileges)")

        source_hash = f"sha256:{hashlib.sha256(secret.read_bytes()).hexdigest()}"
        record = KnowledgeRecord(
            id="test.symlink-escape",
            kind=KnowledgeKind.DIAGNOSTIC_PROBE,
            name="Symlink escape test",
            description="Symlink target outside source root",
            applies_to=AppliesTo(),
            provides=(),
            risk=KnowledgeRisk.READ_ONLY,
            execution_ref="configuration-check:test",
            source_ref="src/escape.yml#check1",
            source_hash=source_hash,
        )
        with pytest.raises(BuildValidationError, match="escapes source_root"):
            build_index([record], tmp_path / "index.db", source_root=source_root)

    def test_all_real_records_have_valid_source_hash(
        self, all_records: List[KnowledgeRecord]
    ) -> None:
        """Every extracted record has a valid sha256 source hash.

        :param all_records: The full record set.
        :type all_records: List[KnowledgeRecord]
        """
        for record in all_records:
            assert record.source_hash.startswith("sha256:")
            hex_part = record.source_hash[7:]
            assert len(hex_part) == 64
            int(hex_part, 16)

    def test_all_real_records_have_path_anchor_source_ref(
        self, all_records: List[KnowledgeRecord]
    ) -> None:
        """Every extracted record has source_ref with path#anchor format.

        :param all_records: The full record set.
        :type all_records: List[KnowledgeRecord]
        """
        for record in all_records:
            assert "#" in record.source_ref
            path_part, anchor = record.source_ref.split("#", 1)
            assert path_part
            assert anchor

    def test_no_shell_commands_in_database(self, built_index: Path) -> None:
        """The raw database contains no shell command patterns.

        :param built_index: Path to built index.
        :type built_index: pathlib.Path
        """
        conn = sqlite3.connect(str(built_index))
        try:
            rows = conn.execute("SELECT execution_ref FROM knowledge_records").fetchall()
            for (ref,) in rows:
                assert "|" not in ref
                assert "&&" not in ref
                assert "sudo " not in ref
                assert "/bin/" not in ref
                assert "/usr/" not in ref
        finally:
            conn.close()
