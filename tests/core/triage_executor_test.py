# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for TriageExecutor — the triage session lifecycle orchestrator."""

import json
from pathlib import Path

import pytest

from src.core.execution.command_allow_list import CommandAllowList
from src.core.execution.evidence_collector import (
    CollectorStrategy,
    EvidenceCollector,
    EvidenceDefinition,
)
from src.core.execution.triage_executor import (
    ArtifactWriter,
    TriageExecutor,
    TriageExecutorProtocol,
)
from src.core.models.evidence import (
    CollectionStatus,
    CollectorType,
    EvidenceArtifact,
    EvidenceType,
)
from src.core.models.triage import TriageSession, TriageStatus

# ---------------------------------------------------------------------------
# Test strategies
# ---------------------------------------------------------------------------


class SuccessStrategy:
    """Returns SUCCESS for every definition."""

    def collect(self, definition: EvidenceDefinition) -> EvidenceArtifact:
        return EvidenceArtifact(
            evidence_id=f"evi-{definition.definition_id}",
            evidence_type=definition.evidence_type,
            collector_type=definition.collector_type,
            status=CollectionStatus.SUCCESS,
            host=definition.host,
            command=definition.command,
            content=f"output of {definition.command}",
            duration_ms=50,
        )


class MixedStrategy:
    """Fails for definitions whose ID contains 'fail'."""

    def collect(self, definition: EvidenceDefinition) -> EvidenceArtifact:
        if "fail" in definition.definition_id:
            raise RuntimeError("simulated failure")
        return EvidenceArtifact(
            evidence_id=f"evi-{definition.definition_id}",
            evidence_type=definition.evidence_type,
            collector_type=definition.collector_type,
            status=CollectionStatus.SUCCESS,
            host=definition.host,
            command=definition.command,
            content=f"output of {definition.command}",
            duration_ms=30,
        )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_definitions(count: int = 3) -> list[EvidenceDefinition]:
    """Create a list of SSH evidence definitions."""
    return [
        EvidenceDefinition(
            definition_id=f"def-{i:03d}",
            evidence_type=EvidenceType.COMMAND_OUTPUT,
            collector_type=CollectorType.SSH,
            host="node1",
            command=f"crm status {i}",
            description=f"Test definition {i}",
        )
        for i in range(count)
    ]


def _make_executor(
    tmp_path: Path,
    strategy: CollectorStrategy = None,
) -> TriageExecutor:
    """Create a TriageExecutor with default configuration."""
    allow_list = CommandAllowList.from_patterns([r".*"])
    collector = EvidenceCollector(allow_list=allow_list, cache_ttl_seconds=0)
    collector.register_strategy(CollectorType.SSH, strategy or SuccessStrategy())
    writer = ArtifactWriter(base_dir=tmp_path / "artifacts")
    return TriageExecutor(collector=collector, artifact_writer=writer)


# ---------------------------------------------------------------------------
# TriageExecutorProtocol conformance
# ---------------------------------------------------------------------------


class TestTriageExecutorProtocol:
    """Verify TriageExecutor satisfies its protocol."""

    def test_conforms_to_protocol(self, tmp_path: Path) -> None:
        executor = _make_executor(tmp_path)
        assert isinstance(executor, TriageExecutorProtocol)


# ---------------------------------------------------------------------------
# ArtifactWriter tests
# ---------------------------------------------------------------------------


class TestArtifactWriter:
    """Tests for artifact persistence."""

    @pytest.fixture()
    def writer(self, tmp_path: Path) -> ArtifactWriter:
        return ArtifactWriter(base_dir=tmp_path / "artifacts")

    @pytest.fixture()
    def sample_artifact(self) -> EvidenceArtifact:
        return EvidenceArtifact(
            evidence_id="evi-001",
            evidence_type=EvidenceType.COMMAND_OUTPUT,
            collector_type=CollectorType.SSH,
            status=CollectionStatus.SUCCESS,
            host="node1",
            command="crm status",
            content="cluster is running",
            duration_ms=50,
        )

    def test_write_creates_file(
        self, writer: ArtifactWriter, sample_artifact: EvidenceArtifact
    ) -> None:
        path = writer.write("session-001", sample_artifact)
        assert path.exists()
        assert path.name == "evi-001.json"

    def test_write_creates_session_directory(
        self, writer: ArtifactWriter, sample_artifact: EvidenceArtifact
    ) -> None:
        writer.write("session-002", sample_artifact)
        session_dir = writer._base_dir / "session-002"
        assert session_dir.is_dir()

    def test_write_produces_valid_json(
        self, writer: ArtifactWriter, sample_artifact: EvidenceArtifact
    ) -> None:
        path = writer.write("session-003", sample_artifact)
        data = json.loads(path.read_text())
        assert data["evidence_id"] == "evi-001"
        assert data["status"] == "success"
        assert data["content"] == "cluster is running"

    def test_write_all(self, writer: ArtifactWriter, sample_artifact: EvidenceArtifact) -> None:
        artifact2 = EvidenceArtifact(
            evidence_id="evi-002",
            evidence_type=EvidenceType.CIB_XML,
            collector_type=CollectorType.SSH,
            status=CollectionStatus.SUCCESS,
            host="node1",
            content="<cib/>",
        )
        paths = writer.write_all("session-004", [sample_artifact, artifact2])
        assert len(paths) == 2
        assert all(p.exists() for p in paths)

    def test_read_existing_artifact(
        self, writer: ArtifactWriter, sample_artifact: EvidenceArtifact
    ) -> None:
        writer.write("session-005", sample_artifact)
        data = writer.read("session-005", "evi-001")
        assert data is not None
        assert data["evidence_id"] == "evi-001"

    def test_read_nonexistent_returns_none(self, writer: ArtifactWriter) -> None:
        result = writer.read("session-999", "evi-nonexistent")
        assert result is None

    def test_list_artifacts_empty_session(self, writer: ArtifactWriter) -> None:
        result = writer.list_artifacts("session-empty")
        assert result == []

    def test_list_artifacts(
        self, writer: ArtifactWriter, sample_artifact: EvidenceArtifact
    ) -> None:
        writer.write("session-006", sample_artifact)
        ids = writer.list_artifacts("session-006")
        assert "evi-001" in ids


# ---------------------------------------------------------------------------
# TriageExecutor — happy path
# ---------------------------------------------------------------------------


class TestTriageExecutorHappyPath:
    """Tests for successful triage execution."""

    def test_collect_advances_session_state(self, tmp_path: Path) -> None:
        executor = _make_executor(tmp_path)
        session = TriageSession(workspace_id="ws-001")
        defs = _make_definitions(2)

        artifacts = executor.collect(session, defs)

        assert len(artifacts) == 2
        assert session.status == TriageStatus.ANALYZING.value
        assert len(session.evidence) == 2

    def test_collect_returns_usable_artifacts(self, tmp_path: Path) -> None:
        executor = _make_executor(tmp_path)
        session = TriageSession(workspace_id="ws-002")
        defs = _make_definitions(3)

        artifacts = executor.collect(session, defs)

        assert all(a.is_usable for a in artifacts)

    def test_artifacts_persisted_to_disk(self, tmp_path: Path) -> None:
        executor = _make_executor(tmp_path)
        session = TriageSession(workspace_id="ws-003")
        session_id = str(session.id)
        defs = _make_definitions(2)

        executor.collect(session, defs)

        artifact_ids = executor.artifact_writer.list_artifacts(session_id)
        assert len(artifact_ids) == 2

    def test_session_events_emitted(self, tmp_path: Path) -> None:
        executor = _make_executor(tmp_path)
        session = TriageSession(workspace_id="ws-004")
        defs = _make_definitions(1)

        executor.collect(session, defs)

        event_types = [e.event_type for e in session.events]
        assert "collection_started" in event_types
        assert "collection_completed" in event_types


# ---------------------------------------------------------------------------
# TriageExecutor — partial failure
# ---------------------------------------------------------------------------


class TestTriageExecutorPartialFailure:
    """Tests for partial failure handling."""

    def test_partial_failure_continues(self, tmp_path: Path) -> None:
        """Executor continues collecting after individual failures."""
        executor = _make_executor(tmp_path, strategy=MixedStrategy())
        session = TriageSession(workspace_id="ws-005")

        defs = [
            EvidenceDefinition(
                definition_id="def-ok-001",
                evidence_type=EvidenceType.COMMAND_OUTPUT,
                collector_type=CollectorType.SSH,
                host="node1",
                command="crm status",
            ),
            EvidenceDefinition(
                definition_id="def-fail-002",
                evidence_type=EvidenceType.COMMAND_OUTPUT,
                collector_type=CollectorType.SSH,
                host="node2",
                command="crm status",
            ),
            EvidenceDefinition(
                definition_id="def-ok-003",
                evidence_type=EvidenceType.COMMAND_OUTPUT,
                collector_type=CollectorType.SSH,
                host="node1",
                command="sysctl -a",
            ),
        ]

        artifacts = executor.collect(session, defs)

        assert len(artifacts) == 3
        assert artifacts[0].is_usable  # ok-001 succeeded
        assert not artifacts[1].is_usable  # fail-002 failed
        assert artifacts[2].is_usable  # ok-003 succeeded

        # Session still advances to ANALYZING
        assert session.status == TriageStatus.ANALYZING.value

    def test_all_failures_still_advances(self, tmp_path: Path) -> None:
        """Even with all failures, session reaches ANALYZING state."""

        class AllFailStrategy:
            def collect(self, defn: EvidenceDefinition) -> EvidenceArtifact:
                raise RuntimeError("all fail")

        executor = _make_executor(tmp_path, strategy=AllFailStrategy())
        session = TriageSession(workspace_id="ws-006")
        defs = _make_definitions(2)

        artifacts = executor.collect(session, defs)

        assert len(artifacts) == 2
        assert all(not a.is_usable for a in artifacts)
        assert session.status == TriageStatus.ANALYZING.value


# ---------------------------------------------------------------------------
# TriageExecutor — validation
# ---------------------------------------------------------------------------


class TestTriageExecutorValidation:
    """Tests for input validation."""

    def test_empty_definitions_raises(self, tmp_path: Path) -> None:
        executor = _make_executor(tmp_path)
        session = TriageSession(workspace_id="ws-007")

        with pytest.raises(ValueError, match="No evidence definitions"):
            executor.collect(session, [])

    def test_session_must_be_pending(self, tmp_path: Path) -> None:
        executor = _make_executor(tmp_path)
        session = TriageSession(workspace_id="ws-008")
        session.start_collection()  # Now COLLECTING

        with pytest.raises(ValueError, match="Invalid transition"):
            executor.collect(session, _make_definitions(1))


# ---------------------------------------------------------------------------
# TriageExecutor — allow-list integration
# ---------------------------------------------------------------------------


class TestTriageExecutorAllowList:
    """Tests for allow-list enforcement through the executor."""

    def test_rejected_commands_produce_failed_artifacts(self, tmp_path: Path) -> None:
        allow_list = CommandAllowList.from_patterns([r"^crm\s+status"])
        collector = EvidenceCollector(allow_list=allow_list, cache_ttl_seconds=0)
        collector.register_strategy(CollectorType.SSH, SuccessStrategy())
        writer = ArtifactWriter(base_dir=tmp_path / "artifacts")
        executor = TriageExecutor(collector=collector, artifact_writer=writer)

        session = TriageSession(workspace_id="ws-009")
        defs = [
            EvidenceDefinition(
                definition_id="def-allowed",
                evidence_type=EvidenceType.COMMAND_OUTPUT,
                collector_type=CollectorType.SSH,
                host="node1",
                command="crm status",
            ),
            EvidenceDefinition(
                definition_id="def-rejected",
                evidence_type=EvidenceType.COMMAND_OUTPUT,
                collector_type=CollectorType.SSH,
                host="node1",
                command="rm -rf /",
            ),
        ]

        artifacts = executor.collect(session, defs)

        assert artifacts[0].is_usable
        assert not artifacts[1].is_usable
        assert "rejected" in artifacts[1].error


# ---------------------------------------------------------------------------
# TriageExecutor — properties
# ---------------------------------------------------------------------------


class TestTriageExecutorProperties:
    """Tests for executor properties."""

    def test_collector_property(self, tmp_path: Path) -> None:
        executor = _make_executor(tmp_path)
        assert isinstance(executor.collector, EvidenceCollector)

    def test_artifact_writer_property(self, tmp_path: Path) -> None:
        executor = _make_executor(tmp_path)
        assert isinstance(executor.artifact_writer, ArtifactWriter)
