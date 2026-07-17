# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Tests for the configuration-check knowledge extractor and schema.
"""

import hashlib
from functools import lru_cache
from pathlib import Path
from typing import List
import pytest
from pydantic import ValidationError
from src.core.exceptions import ConfigurationCheckExtractionError
from src.core.services.knowledge.extractors import (
    CONFIGURATION_CHECK_NAMESPACE,
    DEFAULT_CONFIGURATION_CHECKS_DIR,
    REPO_ROOT,
    extract_configuration_checks,
)
from src.core.models.knowledge import KnowledgeKind, KnowledgeRecord, KnowledgeRisk

EXPECTED_COUNTS_BY_FILE = {
    "app.yml": 12,
    "ascs.yml": 6,
    "db2.yml": 30,
    "hana.yml": 73,
    "high_availability.yml": 5,
    "network.yml": 7,
    "oracle.yml": 7,
    "package.yml": 15,
    "sap.yml": 31,
    "virtual_machine.yml": 49,
}


def _source_file_name(record: KnowledgeRecord) -> str:
    """Return the source file name embedded in a record's ``source_ref``.

    :param record: A normalized knowledge record produced by the extractor.
    :type record: KnowledgeRecord
    :returns: The file name component of the record's ``source_ref``.
    :rtype: str
    """
    path_part = record.source_ref.split("#", 1)[0]
    return path_part.rsplit("/", 1)[-1]


def _record_by_raw_id(records: List[KnowledgeRecord], raw_id: str) -> KnowledgeRecord:
    """Look up a single extracted record by its raw (un-namespaced) id.

    :param records: Records produced by :func:`extract_configuration_checks`.
    :type records: List[KnowledgeRecord]
    :param raw_id: The raw source check id, e.g. ``"DB-HANA-0001"``.
    :type raw_id: str
    :returns: The matching normalized record.
    :rtype: KnowledgeRecord
    :raises AssertionError: If no record matches ``raw_id``.
    """
    expected_execution_ref = f"{CONFIGURATION_CHECK_NAMESPACE}:{raw_id}"
    for record in records:
        if record.execution_ref == expected_execution_ref:
            return record
    raise AssertionError(f"No extracted record for raw id {raw_id!r}")


@lru_cache(maxsize=1)
def _real_records() -> List[KnowledgeRecord]:
    """Extract the full real configuration-check catalog once per session.

    :returns: Every normalized record extracted from the real source files.
    :rtype: List[KnowledgeRecord]
    """
    return extract_configuration_checks()


class TestKnowledgeExtractors:
    """Coverage of the real, 235-check, 10-file configuration-check catalog."""

    def test_extracts_all_235_globally_unique_records(self) -> None:
        """
        Verify every check across all 10 files is extracted exactly once.
        """
        records = _real_records()
        assert len(records) == 235
        ids = [record.id for record in records]
        assert len(set(ids)) == 235

    def test_record_counts_match_expected_per_source_file(self) -> None:
        """
        Verify each source file contributes its expected number of records.
        """
        counts = {name: 0 for name in EXPECTED_COUNTS_BY_FILE}
        for record in _real_records():
            counts[_source_file_name(record)] += 1
        assert counts == EXPECTED_COUNTS_BY_FILE

    def test_ordering_is_sorted_by_filename_then_document_order(self) -> None:
        """
        Verify records are grouped by ascending source filename, with each
        file's checks kept in their original document order.
        """
        records = _real_records()
        first_seen_order = []
        for record in records:
            file_name = _source_file_name(record)
            if file_name not in first_seen_order:
                first_seen_order.append(file_name)
        assert first_seen_order == sorted(EXPECTED_COUNTS_BY_FILE)

        hana_records = [r for r in records if _source_file_name(r) == "hana.yml"]
        hana_raw_ids = [r.execution_ref.split(":", 1)[1] for r in hana_records]
        assert hana_raw_ids == sorted(hana_raw_ids, key=lambda v: hana_raw_ids.index(v))
        assert hana_raw_ids[0] == "DB-HANA-0001"

    def test_repeated_extraction_is_byte_for_byte_equal(self) -> None:
        """
        Verify two independent extractions of the same source produce
        identical, identically-ordered records (a rebuild cannot drift).
        """
        first_pass = extract_configuration_checks()
        second_pass = extract_configuration_checks()
        assert first_pass == second_pass
        assert [r.id for r in first_pass] == [r.id for r in second_pass]

    def test_default_source_dir_and_repo_root_point_at_real_repository(self) -> None:
        """
        Verify the extractor's defaults resolve to this repository's actual
        configuration-check directory, independent of the caller's cwd.
        """
        assert DEFAULT_CONFIGURATION_CHECKS_DIR.is_dir()
        assert REPO_ROOT.joinpath("src", "roles", "configuration_checks").is_dir()

    def test_hana_command_collector_check(self) -> None:
        """
        Verify a representative HANA command-collector check is normalized
        with the expected namespaced id, refs, kind and risk.
        """
        record = _record_by_raw_id(_real_records(), "DB-HANA-0001")
        assert record.id == "configuration-check.db-hana-0001"
        assert record.kind == KnowledgeKind.DIAGNOSTIC_PROBE
        assert record.risk == KnowledgeRisk.READ_ONLY
        assert not record.provides
        assert record.execution_ref == "configuration-check:DB-HANA-0001"
        assert record.source_ref == (
            "src/roles/configuration_checks/tasks/files/hana.yml#DB-HANA-0001"
        )
        assert record.applies_to.component == ("hana",)
        assert record.applies_to.os_family == ("redhat", "suse")

    def test_ha_module_collector_check_has_no_database_type(self) -> None:
        """
        Verify a representative Pacemaker module-collector HA check (which
        declares no ``database_type``) normalizes with an empty component
        list and a topology derived from the combined scale-up/scale-out
        enum.
        """
        record = _record_by_raw_id(_real_records(), "HA-HANA-001")
        assert _source_file_name(record) == "high_availability.yml"
        assert not record.applies_to.component
        assert record.applies_to.os_family == ("redhat", "suse")
        assert record.applies_to.topology == ("scale-out", "scale-up")

    def test_vm_check_without_applicability_block_is_unrestricted(self) -> None:
        """
        Verify a VM instance-metadata check with no ``applicability`` block
        at all normalizes to an entirely empty (unrestricted) applies_to.
        """
        record = _record_by_raw_id(_real_records(), "IC-0001")
        assert not record.applies_to.component
        assert not record.applies_to.os_family
        assert not record.applies_to.topology

    def test_boolean_high_availability_maps_to_no_topology(self) -> None:
        """
        Verify ``applicability.high_availability: true|false`` (an HA-
        required flag, not a topology name) maps to no topology values.
        """
        records = _real_records()
        for raw_id in ("DB-HANA-0016", "DB-HANA-0017"):
            record = _record_by_raw_id(records, raw_id)
            assert not record.applies_to.topology

    def test_oracle_linux_case_variant_normalizes_to_one_os_family(self) -> None:
        """
        Verify ``oracle.yml``'s ``"ORACLELINUX"`` raw value and every other
        file's ``"OracleLinux"`` raw value normalize to the same
        ``os_family`` entry.
        """
        record = _record_by_raw_id(_real_records(), "DB-ORA-0001")
        assert record.applies_to.os_family == ("oraclelinux", "redhat")

    def test_ase_database_type_maps_to_ase_component(self) -> None:
        """
        Verify a check applicable to the ASE database type includes ``ase``
        in the normalized component list.
        """
        record = _record_by_raw_id(_real_records(), "IC-0005")
        assert "ase" in record.applies_to.component

    def test_schema_has_no_command_user_or_parser_fields(self) -> None:
        """
        Verify the schema itself has no field capable of carrying a raw
        command, execution user, collector args or validator behavior.
        """
        forbidden_field_names = {
            "command",
            "user",
            "collector_type",
            "collector_args",
            "validator_type",
            "validator_args",
            "windows_command",
        }
        assert forbidden_field_names.isdisjoint(KnowledgeRecord.model_fields)

    def test_extracted_record_dump_is_exactly_the_normalized_contract(self) -> None:
        """
        Verify a serialized record contains exactly the normalized schema
        fields, nothing copied from the source check's execution details.
        """
        record = _record_by_raw_id(_real_records(), "DB-HANA-0001")
        assert set(record.model_dump().keys()) == {
            "schema_version",
            "id",
            "kind",
            "name",
            "description",
            "applies_to",
            "provides",
            "risk",
            "execution_ref",
            "source_ref",
            "source_hash",
        }

    def test_source_hash_matches_exact_file_bytes(self) -> None:
        """
        Verify ``source_hash`` is the SHA-256 of the exact source file
        bytes, not a hash of any parsed/normalized representation.
        """
        records = _real_records()
        hana_file = DEFAULT_CONFIGURATION_CHECKS_DIR / "hana.yml"
        expected_hash = f"sha256:{hashlib.sha256(hana_file.read_bytes()).hexdigest()}"
        record = _record_by_raw_id(records, "DB-HANA-0001")
        assert record.source_hash == expected_hash

        another_hana_record = _record_by_raw_id(records, "DB-HANA-0002")
        assert another_hana_record.source_hash == expected_hash

    def test_every_record_in_a_file_shares_that_files_hash(self) -> None:
        """
        Verify all records sourced from the same file report the same
        ``source_hash``.
        """
        hashes_by_file: dict = {}
        for record in _real_records():
            file_name = _source_file_name(record)
            hashes_by_file.setdefault(file_name, set()).add(record.source_hash)
        assert all(len(hashes) == 1 for hashes in hashes_by_file.values())

    def test_source_ref_and_execution_ref_preserve_raw_id_case(self) -> None:
        """
        Verify the normalized ``id`` is lower-cased while ``execution_ref``
        and ``source_ref`` retain the original raw id casing.
        """
        record = _record_by_raw_id(_real_records(), "DB-HANA-0001")
        assert record.id == "configuration-check.db-hana-0001"
        assert record.execution_ref == "configuration-check:DB-HANA-0001"
        assert record.source_ref.endswith("#DB-HANA-0001")

    def _write(self, tmp_path: Path, file_name: str, content: str) -> Path:
        """Write a fixture YAML file under ``tmp_path``.

        :param tmp_path: Pytest-provided temporary directory.
        :type tmp_path: pathlib.Path
        :param file_name: Name of the file to create.
        :type file_name: str
        :param content: Raw YAML text to write.
        :type content: str
        :returns: Path to the created file.
        :rtype: pathlib.Path
        """
        target = tmp_path / file_name
        target.write_text(content, encoding="utf-8")
        return target

    def test_missing_source_directory_raises(self, tmp_path: Path) -> None:
        """
        Verify a non-existent source directory is a hard failure.

        :param tmp_path: Pytest-provided temporary directory.
        :type tmp_path: pathlib.Path
        """
        with pytest.raises(ConfigurationCheckExtractionError, match="not found"):
            extract_configuration_checks(tmp_path / "does-not-exist")

    def test_duplicate_normalized_id_across_files_raises(self, tmp_path: Path) -> None:
        """
        Verify two checks (even across different files) that normalize to
        the same knowledge id are rejected.

        :param tmp_path: Pytest-provided temporary directory.
        :type tmp_path: pathlib.Path
        """
        self._write(
            tmp_path,
            "a.yml",
            'checks:\n  - id: "X-0001"\n    name: "n"\n    description: "d"\n',
        )
        self._write(
            tmp_path,
            "b.yml",
            'checks:\n  - id: "x-0001"\n    name: "n2"\n    description: "d2"\n',
        )
        with pytest.raises(ConfigurationCheckExtractionError, match="Duplicate normalized"):
            extract_configuration_checks(tmp_path)

    def test_duplicate_normalized_id_within_one_file_raises(self, tmp_path: Path) -> None:
        """
        Verify duplicate ids declared within a single source file are
        rejected the same way as cross-file duplicates.

        :param tmp_path: Pytest-provided temporary directory.
        :type tmp_path: pathlib.Path
        """
        self._write(
            tmp_path,
            "a.yml",
            "checks:\n"
            '  - id: "X-0001"\n    name: "n"\n    description: "d"\n'
            '  - id: "X-0001"\n    name: "n2"\n    description: "d2"\n',
        )
        with pytest.raises(ConfigurationCheckExtractionError, match="Duplicate normalized"):
            extract_configuration_checks(tmp_path)

    @pytest.mark.parametrize(
        "content",
        [
            'checks:\n  - name: "n"\n    description: "d"\n',
            'checks:\n  - id: "X-0001"\n    description: "d"\n',
            'checks:\n  - id: "X-0001"\n    name: "n"\n',
            'checks:\n  - id: ""\n    name: "n"\n    description: "d"\n',
            'checks:\n  - id: "   "\n    name: "n"\n    description: "d"\n',
            'checks:\n  - id: "X-0001"\n    name: "   "\n    description: "d"\n',
            'checks:\n  - id: "X-0001"\n    name: "n"\n    description: "   "\n',
        ],
        ids=[
            "missing-id",
            "missing-name",
            "missing-description",
            "empty-id",
            "whitespace-id",
            "whitespace-name",
            "whitespace-description",
        ],
    )
    def test_missing_required_field_raises(self, tmp_path: Path, content: str) -> None:
        """
        Verify a check missing (or blank) any of ``id``, ``name`` or
        ``description`` is rejected.

        :param tmp_path: Pytest-provided temporary directory.
        :type tmp_path: pathlib.Path
        :param content: Parametrized YAML fixture content for one check
            missing (or blanking) a required field.
        :type content: str
        """
        self._write(tmp_path, "a.yml", content)
        with pytest.raises(ConfigurationCheckExtractionError, match="missing required field"):
            extract_configuration_checks(tmp_path)

    def test_non_string_id_raises(self, tmp_path: Path) -> None:
        """
        Verify a non-string ``id`` is rejected rather than silently
        stringified.

        :param tmp_path: Pytest-provided temporary directory.
        :type tmp_path: pathlib.Path
        """
        self._write(
            tmp_path,
            "a.yml",
            'checks:\n  - id: 1\n    name: "n"\n    description: "d"\n',
        )
        with pytest.raises(ConfigurationCheckExtractionError, match="must be strings"):
            extract_configuration_checks(tmp_path)

    def test_malformed_id_raises_extraction_error(self, tmp_path: Path) -> None:
        """Reject an ID outside the opaque configuration-check grammar."""
        self._write(
            tmp_path,
            "a.yml",
            'checks:\n  - id: "X 0001"\n    name: "n"\n    description: "d"\n',
        )
        with pytest.raises(ConfigurationCheckExtractionError, match="invalid id"):
            extract_configuration_checks(tmp_path)

    def test_malformed_applicability_not_a_mapping_raises(self, tmp_path: Path) -> None:
        """
        Verify an ``applicability`` value that is not a mapping is rejected
        as an unsupported source structure.

        :param tmp_path: Pytest-provided temporary directory.
        :type tmp_path: pathlib.Path
        """
        self._write(
            tmp_path,
            "a.yml",
            'checks:\n  - id: "X-0001"\n    name: "n"\n    description: "d"\n'
            "    applicability: [1, 2]\n",
        )
        with pytest.raises(ConfigurationCheckExtractionError, match="must be a mapping"):
            extract_configuration_checks(tmp_path)

    @pytest.mark.parametrize(
        "applicability_yaml,expected_field",
        [
            ('      os_type: ["BOGUS"]\n', "os_type"),
            ('      database_type: ["BOGUS"]\n', "database_type"),
            ('      high_availability: ["BOGUS"]\n', "high_availability"),
        ],
        ids=["os_type", "database_type", "high_availability"],
    )
    def test_unsupported_applicability_enum_value_raises(
        self, tmp_path: Path, applicability_yaml: str, expected_field: str
    ) -> None:
        """
        Verify an applicability value outside the explicit mapping tables is
        rejected rather than silently dropped or guessed at.

        :param tmp_path: Pytest-provided temporary directory.
        :type tmp_path: pathlib.Path
        :param applicability_yaml: Parametrized applicability YAML snippet
            containing one unmapped raw value.
        :type applicability_yaml: str
        :param expected_field: Applicability field name expected to appear
            in the raised error message.
        :type expected_field: str
        """
        self._write(
            tmp_path,
            "a.yml",
            'checks:\n  - id: "X-0001"\n    name: "n"\n    description: "d"\n'
            "    applicability:\n" + applicability_yaml,
        )
        with pytest.raises(ConfigurationCheckExtractionError, match=expected_field):
            extract_configuration_checks(tmp_path)

    def test_check_entry_not_a_mapping_raises(self, tmp_path: Path) -> None:
        """
        Verify a ``checks`` list entry that is not itself a mapping is
        rejected.

        :param tmp_path: Pytest-provided temporary directory.
        :type tmp_path: pathlib.Path
        """
        self._write(tmp_path, "a.yml", 'checks:\n  - "not-a-mapping"\n')
        with pytest.raises(ConfigurationCheckExtractionError, match="must be a mapping"):
            extract_configuration_checks(tmp_path)

    def test_missing_checks_key_raises(self, tmp_path: Path) -> None:
        """
        Verify a file with no top-level ``checks`` key is rejected.

        :param tmp_path: Pytest-provided temporary directory.
        :type tmp_path: pathlib.Path
        """
        self._write(tmp_path, "a.yml", "not_checks: []\n")
        with pytest.raises(ConfigurationCheckExtractionError, match="expected a mapping"):
            extract_configuration_checks(tmp_path)

    def test_checks_not_a_list_raises(self, tmp_path: Path) -> None:
        """
        Verify a ``checks`` value that is not a list is rejected.

        :param tmp_path: Pytest-provided temporary directory.
        :type tmp_path: pathlib.Path
        """
        self._write(tmp_path, "a.yml", 'checks: "not-a-list"\n')
        with pytest.raises(ConfigurationCheckExtractionError, match="expected a mapping"):
            extract_configuration_checks(tmp_path)

    def test_malformed_yaml_syntax_raises(self, tmp_path: Path) -> None:
        """
        Verify a file that is not parseable YAML at all is rejected.

        :param tmp_path: Pytest-provided temporary directory.
        :type tmp_path: pathlib.Path
        """
        self._write(tmp_path, "a.yml", "checks: [\n  - id: broken\n")
        with pytest.raises(ConfigurationCheckExtractionError, match="invalid YAML"):
            extract_configuration_checks(tmp_path)

    def test_empty_source_directory_returns_no_records(self, tmp_path: Path) -> None:
        """
        Verify an existing but empty source directory yields no records
        rather than failing (there is simply nothing to extract).

        :param tmp_path: Pytest-provided temporary directory.
        :type tmp_path: pathlib.Path
        """
        assert not extract_configuration_checks(tmp_path)

    def _valid_kwargs(self) -> dict:
        """Return a minimal set of valid constructor kwargs.

        :returns: Keyword arguments that construct a valid record.
        :rtype: dict
        """
        return {
            "id": "configuration-check.example-0001",
            "kind": KnowledgeKind.DIAGNOSTIC_PROBE,
            "name": "Example",
            "description": "Example description",
            "risk": KnowledgeRisk.READ_ONLY,
            "execution_ref": "configuration-check:EXAMPLE-0001",
            "source_ref": "src/roles/configuration_checks/tasks/files/example.yml#EXAMPLE-0001",
            "source_hash": f"sha256:{'0' * 64}",
        }

    def test_valid_record_round_trips(self) -> None:
        """
        Verify a minimally valid record constructs and defaults empty
        applies_to/provides tuples.
        """
        record = KnowledgeRecord(**self._valid_kwargs())
        assert not record.model_dump()["applies_to"]["component"]
        assert not record.provides
        assert record.schema_version == "1.0"

    def test_record_collections_are_immutable(self) -> None:
        """Validated applicability and evidence collections cannot be mutated."""
        kwargs = self._valid_kwargs()
        kwargs["applies_to"] = {"component": ["hana"]}
        kwargs["provides"] = ["configuration"]
        record = KnowledgeRecord(**kwargs)
        applies_to = record.model_dump()["applies_to"]

        assert applies_to["component"] == ("hana",)
        assert record.provides == ("configuration",)
        with pytest.raises(ValidationError):
            record.provides = ("changed",)

    def test_invalid_risk_value_rejected(self) -> None:
        """
        Verify an unrecognized ``risk`` value is rejected by the schema.
        """
        kwargs = self._valid_kwargs()
        kwargs["risk"] = "destructive-but-unregistered"
        with pytest.raises(ValidationError):
            KnowledgeRecord(**kwargs)

    def test_invalid_source_hash_format_rejected(self) -> None:
        """
        Verify a ``source_hash`` that is not ``sha256:<64 hex chars>`` is
        rejected.
        """
        kwargs = self._valid_kwargs()
        kwargs["source_hash"] = "not-a-hash"
        with pytest.raises(ValidationError):
            KnowledgeRecord(**kwargs)

    def test_blank_id_rejected(self) -> None:
        """
        Verify an empty ``id`` is rejected by the schema itself.
        """
        kwargs = self._valid_kwargs()
        kwargs["id"] = ""
        with pytest.raises(ValidationError):
            KnowledgeRecord(**kwargs)

    def test_record_is_immutable(self) -> None:
        """
        Verify a constructed record cannot be mutated in place.
        """
        record = KnowledgeRecord(**self._valid_kwargs())
        with pytest.raises(ValidationError):
            record.name = "changed"
