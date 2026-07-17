# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Tests for the HA/backup test catalog knowledge extractor.
"""

import hashlib
import textwrap
from functools import lru_cache
from pathlib import Path
from typing import List
import pytest
from src.core.exceptions import HAExtractionError
from src.core.services.knowledge.ha_extractors import (
    DEFAULT_HA_CATALOG_PATH,
    HA_TEST_NAMESPACE,
    extract_ha_tests,
)
from src.core.models.knowledge import KnowledgeKind, KnowledgeRecord, KnowledgeRisk

EXPECTED_COUNTS_BY_GROUP = {
    "HA_DB_HANA": 22,
    "HA_SCS": 13,
    "BACKUP_DB_HANA": 5,
}


@lru_cache(maxsize=1)
def _real_records() -> List[KnowledgeRecord]:
    """Extract the full real HA/backup catalog once per session.

    :returns: Every normalized record extracted from the real source.
    :rtype: List[KnowledgeRecord]
    """
    return extract_ha_tests()


def _group_from_id(record_id: str) -> str:
    """Extract the group name segment from a record ID.

    :param record_id: A normalized ID like ``ha-test.ha_db_hana.ha-config``.
    :type record_id: str
    :returns: The group segment (e.g. ``ha_db_hana``).
    :rtype: str
    """
    parts = record_id.split(".")
    return parts[1] if len(parts) >= 3 else ""


class TestKnowledgeHAExtractors:
    """Coverage of the real 40-test-case HA/backup catalog."""

    def test_extracts_all_40_globally_unique_records(self) -> None:
        """Verify every test case across all 3 groups is extracted once."""
        records = _real_records()
        assert len(records) == 40
        ids = [r.id for r in records]
        assert len(set(ids)) == 40

    def test_record_counts_match_expected_per_group(self) -> None:
        """Verify each group contributes its expected number of records."""
        counts: dict = {name.lower().replace("_", "-"): 0 for name in EXPECTED_COUNTS_BY_GROUP}
        for record in _real_records():
            group = _group_from_id(record.id)
            counts[group] = counts.get(group, 0) + 1
        expected = {k.lower().replace("_", "-"): v for k, v in EXPECTED_COUNTS_BY_GROUP.items()}
        assert counts == expected

    def test_stable_ids_disambiguate_colliding_task_names(self) -> None:
        """task_name values like 'ha-config' appear in multiple groups;
        the group prefix in the ID prevents collisions."""
        records = _real_records()
        ha_config_records = [r for r in records if r.id.endswith(".ha-config")]
        assert len(ha_config_records) == 2
        ids = {r.id for r in ha_config_records}
        assert "ha-test.ha-db-hana.ha-config" in ids
        assert "ha-test.ha-scs.ha-config" in ids

    def test_block_network_collision_resolved(self) -> None:
        """block-network appears in both HA_DB_HANA and HA_SCS."""
        records = _real_records()
        block_records = [r for r in records if r.id.endswith(".block-network")]
        assert len(block_records) == 2
        ids = {r.id for r in block_records}
        assert "ha-test.ha-db-hana.block-network" in ids
        assert "ha-test.ha-scs.block-network" in ids

    def test_all_records_have_explicit_risk(self) -> None:
        """Every record must have an explicit risk from mcp metadata."""
        for record in _real_records():
            assert record.risk in (
                KnowledgeRisk.READ_ONLY.value,
                KnowledgeRisk.DESTRUCTIVE.value,
            ), f"Record {record.id} has unexpected risk: {record.risk}"

    def test_all_records_have_non_empty_provides(self) -> None:
        """Every record must have at least one provides value."""
        for record in _real_records():
            assert len(record.provides) > 0, f"Record {record.id} has empty provides"

    def test_provides_are_sorted(self) -> None:
        """Provides lists are deterministically sorted."""
        for record in _real_records():
            assert record.provides == tuple(
                sorted(record.provides)
            ), f"Record {record.id} has unsorted provides: {record.provides}"

    def test_ordering_is_groups_then_cases_in_document_order(self) -> None:
        """Records are ordered by group document order, then case order."""
        records = _real_records()
        groups_seen: List[str] = []
        for record in records:
            group = _group_from_id(record.id)
            if group not in groups_seen:
                groups_seen.append(group)
        assert groups_seen == ["ha-db-hana", "ha-scs", "backup-db-hana"]

    def test_execution_ref_format(self) -> None:
        """execution_ref resolves to group/task identity."""
        records = _real_records()
        for record in records:
            assert record.execution_ref.startswith(f"{HA_TEST_NAMESPACE}:")
            ref_body = record.execution_ref.split(":", 1)[1]
            assert "/" in ref_body
            group, task = ref_body.split("/", 1)
            assert group in ("HA_DB_HANA", "HA_SCS", "BACKUP_DB_HANA")
            assert len(task) > 0

    def test_source_ref_includes_path_and_anchor(self) -> None:
        """source_ref contains the relative path and group/task anchor."""
        records = _real_records()
        for record in records:
            assert "#" in record.source_ref
            path_part, anchor = record.source_ref.split("#", 1)
            assert path_part == "src/vars/input-api.yaml"
            assert "/" in anchor

    def test_source_hash_is_consistent(self) -> None:
        """All records share the same source hash (single file)."""
        records = _real_records()
        hashes = {r.source_hash for r in records}
        assert len(hashes) == 1
        the_hash = hashes.pop()
        assert the_hash.startswith("sha256:")
        raw_bytes = DEFAULT_HA_CATALOG_PATH.read_bytes()
        expected = f"sha256:{hashlib.sha256(raw_bytes).hexdigest()}"
        assert the_hash == expected

    def test_deterministic_extraction(self) -> None:
        """Two extractions from same source produce identical results."""
        first = extract_ha_tests()
        second = extract_ha_tests()
        assert len(first) == len(second)
        for a, b in zip(first, second):
            assert a.model_dump() == b.model_dump()

    def test_representative_db_ha_entry(self) -> None:
        """Spot-check a representative HA_DB_HANA functional test."""
        records = _real_records()
        rec = next(r for r in records if r.id == "ha-test.ha-db-hana.primary-node-crash")
        assert rec.kind == KnowledgeKind.HA_FUNCTIONAL_TEST.value
        assert rec.risk == KnowledgeRisk.DESTRUCTIVE.value
        assert "failover-validation" in rec.provides
        assert rec.applies_to.topology == ("scale-up",)
        assert rec.execution_ref == "ha-test:HA_DB_HANA/primary-node-crash"

    def test_representative_scs_entry(self) -> None:
        """Spot-check a representative HA_SCS test."""
        records = _real_records()
        rec = next(r for r in records if r.id == "ha-test.ha-scs.kill-message-server")
        assert rec.kind == KnowledgeKind.HA_FUNCTIONAL_TEST.value
        assert rec.risk == KnowledgeRisk.DESTRUCTIVE.value
        assert "failover-validation" in rec.provides

    def test_representative_backup_entry(self) -> None:
        """Spot-check a representative BACKUP_DB_HANA test."""
        records = _real_records()
        rec = next(r for r in records if r.id == "ha-test.backup-db-hana.backup-setup-verification")
        assert rec.kind == KnowledgeKind.BACKUP_TEST.value
        assert rec.risk == KnowledgeRisk.READ_ONLY.value
        assert "backup-configuration-status" in rec.provides

    def test_read_only_tests_are_validation_only(self) -> None:
        """Read-only risk is assigned only to non-destructive validation tests."""
        records = _real_records()
        read_only = [r for r in records if r.risk == KnowledgeRisk.READ_ONLY.value]
        expected_task_names = {
            "ha-config",
            "ha-config-offline",
            "azure-lb",
            "sapcontrol-config",
            "backup-setup-verification",
        }
        actual_task_names = set()
        for r in read_only:
            task = r.id.rsplit(".", 1)[-1]
            actual_task_names.add(task)
        assert actual_task_names == expected_task_names

    def test_topology_normalization(self) -> None:
        """Raw topology values are mapped to normalized vocabulary."""
        records = _real_records()
        rec = next(r for r in records if r.id == "ha-test.ha-db-hana.ha-config")
        assert rec.applies_to.topology == ("scale-out-hsr", "scale-up")

    def test_no_topology_when_absent(self) -> None:
        """Groups without applicability.topology get empty topology list."""
        records = _real_records()
        rec = next(r for r in records if r.id == "ha-test.ha-scs.ha-config")
        assert rec.applies_to.topology == ()

    def test_missing_source_file(self, tmp_path: Path) -> None:
        """Raise on missing source file."""
        with pytest.raises(HAExtractionError, match="not found"):
            extract_ha_tests(source_path=tmp_path / "nonexistent.yaml")

    def test_invalid_yaml(self, tmp_path: Path) -> None:
        """Raise on unparseable YAML."""
        bad_file = tmp_path / "bad.yaml"
        bad_file.write_text("{{{{not yaml")
        with pytest.raises(HAExtractionError, match="invalid YAML"):
            extract_ha_tests(source_path=bad_file)

    def test_missing_test_groups_key(self, tmp_path: Path) -> None:
        """Raise when top-level 'test_groups' is absent."""
        f = tmp_path / "no_groups.yaml"
        f.write_text("some_key: value\n")
        with pytest.raises(HAExtractionError, match="test_groups"):
            extract_ha_tests(source_path=f)

    def test_missing_mcp_block(self, tmp_path: Path) -> None:
        """Raise when a test case lacks the 'mcp' metadata block."""
        content = textwrap.dedent("""\
            test_groups:
              - name: HA_DB_HANA
                test_cases:
                  - name: Test Without MCP
                    task_name: no-mcp
                    description: Missing mcp block
                    enabled: true
        """)
        f = tmp_path / "no_mcp.yaml"
        f.write_text(content)
        with pytest.raises(HAExtractionError, match="missing required 'mcp' metadata"):
            extract_ha_tests(source_path=f)

    @pytest.mark.parametrize("field", ["name", "description"])
    def test_whitespace_identity_field_raises(self, tmp_path: Path, field: str) -> None:
        """Reject identity fields that become empty after trimming."""
        values = {
            "name": "Valid name",
            "task_name": "valid-task",
            "description": "Valid description",
        }
        values[field] = "   "
        content = textwrap.dedent(f"""\
            test_groups:
              - name: HA_DB_HANA
                test_cases:
                  - name: "{values['name']}"
                    task_name: {values['task_name']}
                    description: "{values['description']}"
                    enabled: true
                    mcp:
                      risk: read-only
                      provides: [configuration]
        """)
        source = tmp_path / "blank_identity.yaml"
        source.write_text(content)

        with pytest.raises(HAExtractionError, match="missing required field"):
            extract_ha_tests(source_path=source)

    def test_invalid_risk_value(self, tmp_path: Path) -> None:
        """Raise on invalid mcp.risk value."""
        content = textwrap.dedent("""\
            test_groups:
              - name: HA_DB_HANA
                test_cases:
                  - name: Bad Risk
                    task_name: bad-risk
                    description: Has invalid risk
                    enabled: true
                    mcp:
                      risk: dangerous
                      provides: [something]
        """)
        f = tmp_path / "bad_risk.yaml"
        f.write_text(content)
        with pytest.raises(HAExtractionError, match="invalid mcp.risk"):
            extract_ha_tests(source_path=f)

    def test_empty_provides(self, tmp_path: Path) -> None:
        """Raise when mcp.provides is empty."""
        content = textwrap.dedent("""\
            test_groups:
              - name: HA_DB_HANA
                test_cases:
                  - name: Empty Provides
                    task_name: empty-provides
                    description: Has empty provides
                    enabled: true
                    mcp:
                      risk: read-only
                      provides: []
        """)
        f = tmp_path / "empty_provides.yaml"
        f.write_text(content)
        with pytest.raises(HAExtractionError, match="non-empty list"):
            extract_ha_tests(source_path=f)

    def test_duplicate_ids_detected(self, tmp_path: Path) -> None:
        """Raise when two test cases normalize to the same ID."""
        content = textwrap.dedent("""\
            test_groups:
              - name: HA_DB_HANA
                test_cases:
                  - name: First
                    task_name: duplicate-task
                    description: First occurrence
                    enabled: true
                    mcp:
                      risk: read-only
                      provides: [something]
                  - name: Second
                    task_name: duplicate-task
                    description: Second occurrence
                    enabled: true
                    mcp:
                      risk: read-only
                      provides: [something]
        """)
        f = tmp_path / "dup.yaml"
        f.write_text(content)
        with pytest.raises(HAExtractionError, match="Duplicate normalized knowledge id"):
            extract_ha_tests(source_path=f)

    def test_unknown_group_prefix(self, tmp_path: Path) -> None:
        """Raise when group name doesn't match any known prefix."""
        content = textwrap.dedent("""\
            test_groups:
              - name: UNKNOWN_GROUP
                test_cases:
                  - name: Test
                    task_name: test
                    description: Something
                    enabled: true
                    mcp:
                      risk: read-only
                      provides: [something]
        """)
        f = tmp_path / "unknown.yaml"
        f.write_text(content)
        with pytest.raises(HAExtractionError, match="does not match any known prefix"):
            extract_ha_tests(source_path=f)

    def test_invalid_topology_value(self, tmp_path: Path) -> None:
        """Raise on unsupported topology value."""
        content = textwrap.dedent("""\
            test_groups:
              - name: HA_DB_HANA
                test_cases:
                  - name: Bad Topology
                    task_name: bad-topo
                    description: Has bad topology
                    enabled: true
                    applicability:
                      topology: [unknown_topology]
                    mcp:
                      risk: read-only
                      provides: [something]
        """)
        f = tmp_path / "bad_topo.yaml"
        f.write_text(content)
        with pytest.raises(HAExtractionError, match="unsupported applicability.topology"):
            extract_ha_tests(source_path=f)

    def test_missing_task_name(self, tmp_path: Path) -> None:
        """Raise when task_name is missing."""
        content = textwrap.dedent("""\
            test_groups:
              - name: HA_DB_HANA
                test_cases:
                  - name: No Task Name
                    description: Missing task_name
                    enabled: true
                    mcp:
                      risk: read-only
                      provides: [something]
        """)
        f = tmp_path / "no_task.yaml"
        f.write_text(content)
        with pytest.raises(HAExtractionError, match="missing required field"):
            extract_ha_tests(source_path=f)

    def test_non_mapping_applicability_raises(self, tmp_path: Path) -> None:
        """Raise when applicability is present but not a mapping."""
        content = textwrap.dedent("""\
            test_groups:
              - name: HA_DB_HANA
                test_cases:
                  - name: Bad Applicability
                    task_name: bad-app
                    description: Applicability is a string
                    enabled: true
                    applicability: "not-a-mapping"
                    mcp:
                      risk: read-only
                      provides: [something]
        """)
        f = tmp_path / "non_map_app.yaml"
        f.write_text(content)
        with pytest.raises(HAExtractionError, match="must be a mapping"):
            extract_ha_tests(source_path=f)

    def test_scalar_topology_raises(self, tmp_path: Path) -> None:
        """Raise when applicability.topology is a scalar, not a list."""
        content = textwrap.dedent("""\
            test_groups:
              - name: HA_DB_HANA
                test_cases:
                  - name: Scalar Topology
                    task_name: scalar-topo
                    description: Topology is a single string
                    enabled: true
                    applicability:
                      topology: scale_up
                    mcp:
                      risk: read-only
                      provides: [something]
        """)
        f = tmp_path / "scalar_topo.yaml"
        f.write_text(content)
        with pytest.raises(HAExtractionError, match="must be a list"):
            extract_ha_tests(source_path=f)

    def test_invalid_task_name_slug(self, tmp_path: Path) -> None:
        """Raise when task_name contains uppercase or invalid characters."""
        content = textwrap.dedent("""\
            test_groups:
              - name: HA_DB_HANA
                test_cases:
                  - name: Bad Task Name
                    task_name: Bad_Task_Name
                    description: Has invalid task name
                    enabled: true
                    mcp:
                      risk: read-only
                      provides: [something]
        """)
        f = tmp_path / "bad_task_name.yaml"
        f.write_text(content)
        with pytest.raises(HAExtractionError, match="invalid task_name"):
            extract_ha_tests(source_path=f)

    def test_invalid_provides_slug(self, tmp_path: Path) -> None:
        """Raise when a provides entry is not a valid slug."""
        content = textwrap.dedent("""\
            test_groups:
              - name: HA_DB_HANA
                test_cases:
                  - name: Bad Provides Slug
                    task_name: good-task
                    description: Has invalid provides entry
                    enabled: true
                    mcp:
                      risk: read-only
                      provides: [valid-slug, "Invalid Slug"]
        """)
        f = tmp_path / "bad_provides_slug.yaml"
        f.write_text(content)
        with pytest.raises(HAExtractionError, match="invalid mcp.provides entry"):
            extract_ha_tests(source_path=f)

    def test_duplicate_provides_raises(self, tmp_path: Path) -> None:
        """Raise when provides contains duplicate entries."""
        content = textwrap.dedent("""\
            test_groups:
              - name: HA_DB_HANA
                test_cases:
                  - name: Duplicate Provides
                    task_name: dup-provides
                    description: Has duplicate provides
                    enabled: true
                    mcp:
                      risk: read-only
                      provides: [something, something]
        """)
        f = tmp_path / "dup_provides.yaml"
        f.write_text(content)
        with pytest.raises(HAExtractionError, match="duplicate entries in mcp.provides"):
            extract_ha_tests(source_path=f)
