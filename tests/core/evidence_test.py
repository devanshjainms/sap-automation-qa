# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for evidence artifact models."""

import pytest
from src.core.models.evidence import (
    CollectionStatus,
    CollectorType,
    EvidenceArtifact,
    EvidenceType,
)


class TestEvidenceType:
    """Unit tests for EvidenceType enum."""

    def test_known_members(self) -> None:
        """Verify expected evidence types exist."""
        expected = {
            "command_output",
            "azure_metadata",
            "cib_xml",
            "log_excerpt",
            "log_output",
            "sap_process_list",
        }
        actual = {m.value for m in EvidenceType}
        assert actual == expected

    def test_from_string(self) -> None:
        """Verify EvidenceType can be constructed from string."""
        assert EvidenceType("cib_xml") == EvidenceType.CIB_XML


class TestCollectorType:
    """Unit tests for CollectorType enum."""

    def test_known_members(self) -> None:
        """Verify expected collector types exist."""
        expected = {"ssh", "azure_api", "azure_mcp", "local_file", "imds"}
        actual = {m.value for m in CollectorType}
        assert actual == expected


class TestCollectionStatus:
    """Unit tests for CollectionStatus enum."""

    def test_known_members(self) -> None:
        """Verify expected statuses exist."""
        expected = {"success", "failed", "timeout", "unreachable"}
        actual = {m.value for m in CollectionStatus}
        assert actual == expected


class TestEvidenceArtifact:
    """Unit tests for EvidenceArtifact frozen dataclass."""

    def test_create_success(self) -> None:
        """Verify successful artifact creation with all fields."""
        artifact = EvidenceArtifact(
            evidence_id="EV-001",
            evidence_type=EvidenceType.COMMAND_OUTPUT,
            collector_type=CollectorType.SSH,
            status=CollectionStatus.SUCCESS,
            host="node1",
            command="crm_mon -1",
            content="<xml>...</xml>",
            duration_ms=250,
        )
        assert artifact.evidence_id == "EV-001"
        assert artifact.is_usable is True

    def test_create_failed(self) -> None:
        """Verify failed artifact has is_usable=False."""
        artifact = EvidenceArtifact(
            evidence_id="EV-002",
            evidence_type=EvidenceType.COMMAND_OUTPUT,
            collector_type=CollectorType.SSH,
            status=CollectionStatus.FAILED,
            host="node2",
            error="Connection refused",
        )
        assert artifact.is_usable is False
        assert artifact.error == "Connection refused"

    def test_create_timeout(self) -> None:
        """Verify timeout artifact has is_usable=False."""
        artifact = EvidenceArtifact(
            evidence_id="EV-003",
            evidence_type=EvidenceType.AZURE_METADATA,
            collector_type=CollectorType.AZURE_API,
            status=CollectionStatus.TIMEOUT,
            host="vm-hana-01",
        )
        assert artifact.is_usable is False

    def test_create_unreachable(self) -> None:
        """Verify unreachable artifact has is_usable=False."""
        artifact = EvidenceArtifact(
            evidence_id="EV-004",
            evidence_type=EvidenceType.LOG_EXCERPT,
            collector_type=CollectorType.SSH,
            status=CollectionStatus.UNREACHABLE,
            host="node3",
        )
        assert artifact.is_usable is False

    def test_frozen(self) -> None:
        """Verify artifact is immutable."""
        artifact = EvidenceArtifact(
            evidence_id="EV-005",
            evidence_type=EvidenceType.CIB_XML,
            collector_type=CollectorType.SSH,
            status=CollectionStatus.SUCCESS,
            host="node1",
        )
        with pytest.raises(AttributeError):
            artifact.host = "node2"  # type: ignore[misc]

    def test_to_dict(self) -> None:
        """Verify to_dict produces a complete dictionary."""
        artifact = EvidenceArtifact(
            evidence_id="EV-006",
            evidence_type=EvidenceType.SAP_PROCESS_LIST,
            collector_type=CollectorType.SSH,
            status=CollectionStatus.SUCCESS,
            host="node1",
            command="sapcontrol -nr 00 -function GetProcessList",
            content="name, dispstatus, pid\nhdbdaemon, GREEN, 12345",
            duration_ms=100,
            metadata={"sid": "HDB"},
        )
        d = artifact.to_dict()
        assert d["evidence_id"] == "EV-006"
        assert d["evidence_type"] == "sap_process_list"
        assert d["collector_type"] == "ssh"
        assert d["status"] == "success"
        assert d["host"] == "node1"
        assert d["duration_ms"] == 100
        assert d["metadata"] == {"sid": "HDB"}
        assert "collected_at" in d

    def test_defaults(self) -> None:
        """Verify default values for optional fields."""
        artifact = EvidenceArtifact(
            evidence_id="EV-007",
            evidence_type=EvidenceType.COMMAND_OUTPUT,
            collector_type=CollectorType.SSH,
            status=CollectionStatus.SUCCESS,
            host="node1",
        )
        assert artifact.command == ""
        assert artifact.content == ""
        assert artifact.duration_ms == 0
        assert artifact.error is None
        assert artifact.metadata == {}

    def test_metadata_in_dict(self) -> None:
        """Verify metadata dict is included in to_dict output."""
        meta = {"rule_id": "DB-001", "definition_id": "DEF-001"}
        artifact = EvidenceArtifact(
            evidence_id="EV-008",
            evidence_type=EvidenceType.COMMAND_OUTPUT,
            collector_type=CollectorType.SSH,
            status=CollectionStatus.SUCCESS,
            host="node1",
            metadata=meta,
        )
        assert artifact.to_dict()["metadata"] == meta
