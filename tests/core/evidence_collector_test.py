# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for EvidenceCollector — strategy-based evidence collection."""

import time
from datetime import datetime

import pytest

from src.core.execution.command_allow_list import CommandAllowList
from src.core.execution.evidence_collector import (
    CollectorStrategy,
    EvidenceCollector,
    EvidenceDefinition,
)
from src.core.models.evidence import (
    CollectionStatus,
    CollectorType,
    EvidenceArtifact,
    EvidenceType,
)

# ---------------------------------------------------------------------------
# Test fixtures — mock strategies
# ---------------------------------------------------------------------------


class SuccessStrategy:
    """Always returns a successful artifact."""

    def collect(self, definition: EvidenceDefinition) -> EvidenceArtifact:
        return EvidenceArtifact(
            evidence_id=f"evi-{definition.definition_id}",
            evidence_type=definition.evidence_type,
            collector_type=definition.collector_type,
            status=CollectionStatus.SUCCESS,
            host=definition.host,
            command=definition.command,
            content=f"output of {definition.command}",
            duration_ms=100,
        )


class FailureStrategy:
    """Always raises an exception."""

    def collect(self, definition: EvidenceDefinition) -> EvidenceArtifact:
        raise RuntimeError("SSH connection refused")


class TimeoutStrategy:
    """Always raises TimeoutError."""

    def collect(self, definition: EvidenceDefinition) -> EvidenceArtifact:
        raise TimeoutError("Command timed out after 30s")


class UnreachableStrategy:
    """Always raises ConnectionError."""

    def collect(self, definition: EvidenceDefinition) -> EvidenceArtifact:
        raise ConnectionError("Host unreachable")


# ---------------------------------------------------------------------------
# EvidenceDefinition tests
# ---------------------------------------------------------------------------


class TestEvidenceDefinition:
    """Tests for evidence definition value object."""

    def test_create_with_defaults(self) -> None:
        defn = EvidenceDefinition(
            definition_id="def-001",
            evidence_type=EvidenceType.COMMAND_OUTPUT,
            collector_type=CollectorType.SSH,
        )
        assert defn.definition_id == "def-001"
        assert defn.host == ""
        assert defn.command == ""
        assert defn.timeout_seconds == 30

    def test_create_with_all_fields(self) -> None:
        defn = EvidenceDefinition(
            definition_id="def-002",
            evidence_type=EvidenceType.CIB_XML,
            collector_type=CollectorType.SSH,
            host="node1",
            command="cibadmin --query",
            description="CIB XML dump",
            timeout_seconds=60,
            metadata={"rule_id": "HA-DB-0001"},
        )
        assert defn.host == "node1"
        assert defn.command == "cibadmin --query"
        assert defn.metadata["rule_id"] == "HA-DB-0001"

    def test_frozen(self) -> None:
        defn = EvidenceDefinition(
            definition_id="def-003",
            evidence_type=EvidenceType.COMMAND_OUTPUT,
            collector_type=CollectorType.SSH,
        )
        with pytest.raises(AttributeError):
            defn.host = "changed"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# CollectorStrategy protocol conformance
# ---------------------------------------------------------------------------


class TestCollectorStrategyProtocol:
    """Verify that our test strategies satisfy the protocol."""

    def test_success_strategy_is_collector(self) -> None:
        assert isinstance(SuccessStrategy(), CollectorStrategy)

    def test_failure_strategy_is_collector(self) -> None:
        assert isinstance(FailureStrategy(), CollectorStrategy)


# ---------------------------------------------------------------------------
# EvidenceCollector — basic collection
# ---------------------------------------------------------------------------


class TestEvidenceCollectorBasic:
    """Basic collection scenarios."""

    @pytest.fixture()
    def allow_list(self) -> CommandAllowList:
        return CommandAllowList.from_patterns([r"^crm", r"^sysctl", r"^cibadmin"])

    @pytest.fixture()
    def collector(self, allow_list: CommandAllowList) -> EvidenceCollector:
        ec = EvidenceCollector(allow_list=allow_list, cache_ttl_seconds=0)
        ec.register_strategy(CollectorType.SSH, SuccessStrategy())
        return ec

    def test_collect_one_success(self, collector: EvidenceCollector) -> None:
        defn = EvidenceDefinition(
            definition_id="def-001",
            evidence_type=EvidenceType.COMMAND_OUTPUT,
            collector_type=CollectorType.SSH,
            host="node1",
            command="crm status",
        )
        artifact = collector.collect_one(defn)
        assert artifact.is_usable
        assert artifact.status == CollectionStatus.SUCCESS
        assert "crm status" in artifact.content

    def test_collect_all_multiple(self, collector: EvidenceCollector) -> None:
        defs = [
            EvidenceDefinition(
                definition_id=f"def-{i}",
                evidence_type=EvidenceType.COMMAND_OUTPUT,
                collector_type=CollectorType.SSH,
                host="node1",
                command=f"crm status {i}",
            )
            for i in range(3)
        ]
        artifacts = collector.collect_all(defs)
        assert len(artifacts) == 3
        assert all(a.is_usable for a in artifacts)

    def test_collect_empty_list(self, collector: EvidenceCollector) -> None:
        artifacts = collector.collect_all([])
        assert artifacts == []


# ---------------------------------------------------------------------------
# EvidenceCollector — allow-list enforcement
# ---------------------------------------------------------------------------


class TestEvidenceCollectorAllowList:
    """Tests for command allow-list enforcement."""

    @pytest.fixture()
    def collector(self) -> EvidenceCollector:
        allow_list = CommandAllowList.from_patterns([r"^crm\s+status"])
        ec = EvidenceCollector(allow_list=allow_list, cache_ttl_seconds=0)
        ec.register_strategy(CollectorType.SSH, SuccessStrategy())
        return ec

    def test_allowed_command_succeeds(self, collector: EvidenceCollector) -> None:
        defn = EvidenceDefinition(
            definition_id="def-ok",
            evidence_type=EvidenceType.COMMAND_OUTPUT,
            collector_type=CollectorType.SSH,
            host="node1",
            command="crm status",
        )
        artifact = collector.collect_one(defn)
        assert artifact.is_usable

    def test_rejected_command_returns_failed(self, collector: EvidenceCollector) -> None:
        defn = EvidenceDefinition(
            definition_id="def-bad",
            evidence_type=EvidenceType.COMMAND_OUTPUT,
            collector_type=CollectorType.SSH,
            host="node1",
            command="rm -rf /",
        )
        artifact = collector.collect_one(defn)
        assert not artifact.is_usable
        assert artifact.status == CollectionStatus.FAILED
        assert "rejected by allow-list" in artifact.error
        assert artifact.metadata.get("rejected") is True

    def test_azure_api_skips_allow_list(self) -> None:
        """Azure API collector doesn't require command validation."""
        allow_list = CommandAllowList()  # Empty — rejects everything
        ec = EvidenceCollector(allow_list=allow_list, cache_ttl_seconds=0)
        ec.register_strategy(CollectorType.AZURE_API, SuccessStrategy())

        defn = EvidenceDefinition(
            definition_id="def-azure",
            evidence_type=EvidenceType.AZURE_METADATA,
            collector_type=CollectorType.AZURE_API,
            host="subscription-id",
        )
        artifact = ec.collect_one(defn)
        assert artifact.is_usable

    def test_local_file_requires_allow_list(self) -> None:
        """LOCAL_FILE with a command still requires allow-list validation."""
        allow_list = CommandAllowList()  # Empty
        ec = EvidenceCollector(allow_list=allow_list, cache_ttl_seconds=0)
        ec.register_strategy(CollectorType.LOCAL_FILE, SuccessStrategy())

        defn = EvidenceDefinition(
            definition_id="def-local",
            evidence_type=EvidenceType.LOG_EXCERPT,
            collector_type=CollectorType.LOCAL_FILE,
            command="cat /var/log/messages",
        )
        artifact = ec.collect_one(defn)
        assert not artifact.is_usable
        assert "rejected" in artifact.error


# ---------------------------------------------------------------------------
# EvidenceCollector — error handling (partial failure)
# ---------------------------------------------------------------------------


class TestEvidenceCollectorPartialFailure:
    """Tests for graceful handling of strategy failures."""

    @pytest.fixture()
    def allow_list(self) -> CommandAllowList:
        return CommandAllowList.from_patterns([r".*"])

    def test_strategy_exception_returns_failed(self, allow_list: CommandAllowList) -> None:
        ec = EvidenceCollector(allow_list=allow_list, cache_ttl_seconds=0)
        ec.register_strategy(CollectorType.SSH, FailureStrategy())

        defn = EvidenceDefinition(
            definition_id="def-fail",
            evidence_type=EvidenceType.COMMAND_OUTPUT,
            collector_type=CollectorType.SSH,
            host="node1",
            command="crm status",
        )
        artifact = ec.collect_one(defn)
        assert not artifact.is_usable
        assert artifact.status == CollectionStatus.FAILED
        assert "SSH connection refused" in artifact.error

    def test_timeout_returns_timeout_status(self, allow_list: CommandAllowList) -> None:
        ec = EvidenceCollector(allow_list=allow_list, cache_ttl_seconds=0)
        ec.register_strategy(CollectorType.SSH, TimeoutStrategy())

        defn = EvidenceDefinition(
            definition_id="def-timeout",
            evidence_type=EvidenceType.COMMAND_OUTPUT,
            collector_type=CollectorType.SSH,
            host="node1",
            command="crm status",
        )
        artifact = ec.collect_one(defn)
        assert artifact.status == CollectionStatus.TIMEOUT

    def test_unreachable_returns_unreachable_status(self, allow_list: CommandAllowList) -> None:
        ec = EvidenceCollector(allow_list=allow_list, cache_ttl_seconds=0)
        ec.register_strategy(CollectorType.SSH, UnreachableStrategy())

        defn = EvidenceDefinition(
            definition_id="def-unreach",
            evidence_type=EvidenceType.COMMAND_OUTPUT,
            collector_type=CollectorType.SSH,
            host="node1",
            command="crm status",
        )
        artifact = ec.collect_one(defn)
        assert artifact.status == CollectionStatus.UNREACHABLE

    def test_missing_strategy_returns_failed(self, allow_list: CommandAllowList) -> None:
        ec = EvidenceCollector(allow_list=allow_list, cache_ttl_seconds=0)
        # No strategy registered for IMDS

        defn = EvidenceDefinition(
            definition_id="def-imds",
            evidence_type=EvidenceType.AZURE_METADATA,
            collector_type=CollectorType.IMDS,
            host="169.254.169.254",
        )
        artifact = ec.collect_one(defn)
        assert not artifact.is_usable
        assert "No collector strategy" in artifact.error

    def test_mixed_success_and_failure(self, allow_list: CommandAllowList) -> None:
        """collect_all continues after individual failures."""
        ec = EvidenceCollector(allow_list=allow_list, cache_ttl_seconds=0)
        ec.register_strategy(CollectorType.SSH, SuccessStrategy())
        ec.register_strategy(CollectorType.IMDS, FailureStrategy())

        defs = [
            EvidenceDefinition(
                definition_id="def-ssh",
                evidence_type=EvidenceType.COMMAND_OUTPUT,
                collector_type=CollectorType.SSH,
                host="node1",
                command="crm status",
            ),
            EvidenceDefinition(
                definition_id="def-imds",
                evidence_type=EvidenceType.AZURE_METADATA,
                collector_type=CollectorType.IMDS,
                host="169.254.169.254",
            ),
            EvidenceDefinition(
                definition_id="def-ssh2",
                evidence_type=EvidenceType.COMMAND_OUTPUT,
                collector_type=CollectorType.SSH,
                host="node2",
                command="crm status",
            ),
        ]
        artifacts = ec.collect_all(defs)
        assert len(artifacts) == 3
        assert artifacts[0].is_usable  # SSH succeeded
        assert not artifacts[1].is_usable  # IMDS failed
        assert artifacts[2].is_usable  # SSH succeeded


# ---------------------------------------------------------------------------
# EvidenceCollector — caching
# ---------------------------------------------------------------------------


class TestEvidenceCollectorCaching:
    """Tests for TTL-based caching of evidence artifacts."""

    @pytest.fixture()
    def allow_list(self) -> CommandAllowList:
        return CommandAllowList.from_patterns([r".*"])

    def test_cache_hit(self, allow_list: CommandAllowList) -> None:
        """Second collect_one returns cached artifact."""
        call_count = 0

        class CountingStrategy:
            def collect(self, definition: EvidenceDefinition) -> EvidenceArtifact:
                nonlocal call_count
                call_count += 1
                return EvidenceArtifact(
                    evidence_id=f"evi-{call_count}",
                    evidence_type=definition.evidence_type,
                    collector_type=definition.collector_type,
                    status=CollectionStatus.SUCCESS,
                    host=definition.host,
                    content=f"call-{call_count}",
                )

        ec = EvidenceCollector(allow_list=allow_list, cache_ttl_seconds=300)
        ec.register_strategy(CollectorType.SSH, CountingStrategy())

        defn = EvidenceDefinition(
            definition_id="def-cache",
            evidence_type=EvidenceType.COMMAND_OUTPUT,
            collector_type=CollectorType.SSH,
            host="node1",
            command="crm status",
        )

        first = ec.collect_one(defn)
        second = ec.collect_one(defn)

        assert call_count == 1
        assert first.evidence_id == second.evidence_id

    def test_cache_disabled_when_ttl_zero(self, allow_list: CommandAllowList) -> None:
        call_count = 0

        class CountingStrategy:
            def collect(self, definition: EvidenceDefinition) -> EvidenceArtifact:
                nonlocal call_count
                call_count += 1
                return EvidenceArtifact(
                    evidence_id=f"evi-{call_count}",
                    evidence_type=definition.evidence_type,
                    collector_type=definition.collector_type,
                    status=CollectionStatus.SUCCESS,
                    host=definition.host,
                    content=f"call-{call_count}",
                )

        ec = EvidenceCollector(allow_list=allow_list, cache_ttl_seconds=0)
        ec.register_strategy(CollectorType.SSH, CountingStrategy())

        defn = EvidenceDefinition(
            definition_id="def-nocache",
            evidence_type=EvidenceType.COMMAND_OUTPUT,
            collector_type=CollectorType.SSH,
            host="node1",
            command="crm status",
        )

        ec.collect_one(defn)
        ec.collect_one(defn)

        assert call_count == 2

    def test_failed_artifacts_not_cached(self, allow_list: CommandAllowList) -> None:
        call_count = 0

        class FailOnceStrategy:
            def collect(self, definition: EvidenceDefinition) -> EvidenceArtifact:
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    raise RuntimeError("temporary failure")
                return EvidenceArtifact(
                    evidence_id=f"evi-ok",
                    evidence_type=definition.evidence_type,
                    collector_type=definition.collector_type,
                    status=CollectionStatus.SUCCESS,
                    host=definition.host,
                    content="recovered",
                )

        ec = EvidenceCollector(allow_list=allow_list, cache_ttl_seconds=300)
        ec.register_strategy(CollectorType.SSH, FailOnceStrategy())

        defn = EvidenceDefinition(
            definition_id="def-retry",
            evidence_type=EvidenceType.COMMAND_OUTPUT,
            collector_type=CollectorType.SSH,
            host="node1",
            command="crm status",
        )

        first = ec.collect_one(defn)
        assert not first.is_usable

        second = ec.collect_one(defn)
        assert second.is_usable
        assert call_count == 2

    def test_clear_cache(self, allow_list: CommandAllowList) -> None:
        call_count = 0

        class CountingStrategy:
            def collect(self, definition: EvidenceDefinition) -> EvidenceArtifact:
                nonlocal call_count
                call_count += 1
                return EvidenceArtifact(
                    evidence_id=f"evi-{call_count}",
                    evidence_type=definition.evidence_type,
                    collector_type=definition.collector_type,
                    status=CollectionStatus.SUCCESS,
                    host=definition.host,
                )

        ec = EvidenceCollector(allow_list=allow_list, cache_ttl_seconds=300)
        ec.register_strategy(CollectorType.SSH, CountingStrategy())

        defn = EvidenceDefinition(
            definition_id="def-clear",
            evidence_type=EvidenceType.COMMAND_OUTPUT,
            collector_type=CollectorType.SSH,
            host="node1",
            command="crm status",
        )

        ec.collect_one(defn)
        ec.clear_cache()
        ec.collect_one(defn)

        assert call_count == 2


# ---------------------------------------------------------------------------
# EvidenceCollector — strategy registration
# ---------------------------------------------------------------------------


class TestEvidenceCollectorRegistration:
    """Tests for strategy registration and replacement."""

    def test_register_multiple_strategies(self) -> None:
        allow_list = CommandAllowList.from_patterns([r".*"])
        ec = EvidenceCollector(allow_list=allow_list)
        ec.register_strategy(CollectorType.SSH, SuccessStrategy())
        ec.register_strategy(CollectorType.AZURE_API, SuccessStrategy())
        ec.register_strategy(CollectorType.IMDS, SuccessStrategy())
        # No assertion needed — registration should not raise

    def test_replace_strategy(self) -> None:
        allow_list = CommandAllowList.from_patterns([r".*"])
        ec = EvidenceCollector(allow_list=allow_list, cache_ttl_seconds=0)

        ec.register_strategy(CollectorType.SSH, FailureStrategy())
        defn = EvidenceDefinition(
            definition_id="def-replace",
            evidence_type=EvidenceType.COMMAND_OUTPUT,
            collector_type=CollectorType.SSH,
            host="node1",
            command="crm status",
        )
        assert not ec.collect_one(defn).is_usable

        ec.register_strategy(CollectorType.SSH, SuccessStrategy())
        assert ec.collect_one(defn).is_usable
