# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for test-group capability classification."""

import pytest

from src.core.execution.capability_classification import get_capability


class TestCapabilityClassification:
    """Verify online and offline capability semantics."""

    def test_offline_dispatch_is_read_only(self) -> None:
        """Classify offline validation as read-only and deterministic."""
        capability = get_capability("DatabaseHighAvailability").for_dispatch(offline=True)

        assert capability.read_only is True
        assert capability.destructive is False
        assert capability.idempotent is True
        assert capability.open_world is False

    def test_online_dispatch_preserves_group_risk(self) -> None:
        """Preserve destructive HA semantics for online dispatch."""
        capability = get_capability("DatabaseHighAvailability").for_dispatch(offline=False)

        assert capability.read_only is False
        assert capability.destructive is True
        assert capability.idempotent is False

    def test_ineligible_group_rejects_offline_dispatch(self) -> None:
        """Reject offline dispatch for groups without an offline catalog."""
        with pytest.raises(ValueError, match="has no offline mode"):
            get_capability("ConfigurationChecks").for_dispatch(offline=True)

    def test_unknown_group_is_never_defaulted(self) -> None:
        """Reject groups missing from the authoritative registry."""
        with pytest.raises(KeyError, match="Unclassified test group"):
            get_capability("UnknownGroup")
