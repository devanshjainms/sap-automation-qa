# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for failure classification enums."""

import pytest
from src.core.models.failure import FailureClass, Severity


class TestFailureClass:
    """Unit tests for FailureClass enum."""

    def test_all_values_are_strings(self) -> None:
        """Verify all FailureClass values are lowercase strings."""
        for member in FailureClass:
            assert isinstance(member.value, str)
            assert member.value == member.value.lower()

    def test_known_members(self) -> None:
        """Verify expected failure classes exist."""
        expected = {
            "fencing_not_triggered",
            "wrong_fs_type",
            "hsr_sync_failure",
            "hsr_takeover_failure",
            "resource_not_started",
            "resource_not_promoted",
            "constraint_blocking",
            "quorum_loss",
            "split_brain",
            "sbd_failure",
            "enqueue_replication_failure",
            "sapstartsrv_failure",
            "load_balancer_misconfigured",
            "os_config_drift",
            "storage_throttling",
            "network_isolation",
            "unknown",
        }
        actual = {m.value for m in FailureClass}
        assert actual == expected

    def test_from_string(self) -> None:
        """Verify FailureClass can be constructed from string value."""
        assert FailureClass("hsr_sync_failure") == FailureClass.HSR_SYNC_FAILURE

    def test_invalid_value_raises(self) -> None:
        """Verify invalid string raises ValueError."""
        with pytest.raises(ValueError):
            FailureClass("nonexistent_failure")

    def test_unknown_is_default_catch_all(self) -> None:
        """Verify UNKNOWN exists as a catch-all."""
        assert FailureClass.UNKNOWN.value == "unknown"


class TestSeverity:
    """Unit tests for Severity enum."""

    def test_all_values_are_strings(self) -> None:
        """Verify all Severity values are uppercase strings."""
        for member in Severity:
            assert isinstance(member.value, str)
            assert member.value == member.value.upper()

    def test_known_members(self) -> None:
        """Verify expected severities exist."""
        expected = {"CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"}
        actual = {m.value for m in Severity}
        assert actual == expected

    def test_ordering_by_value(self) -> None:
        """Verify from-string construction works for each severity."""
        assert Severity("CRITICAL") == Severity.CRITICAL
        assert Severity("INFO") == Severity.INFO

    def test_invalid_value_raises(self) -> None:
        """Verify invalid severity raises ValueError."""
        with pytest.raises(ValueError):
            Severity("EXTREME")
