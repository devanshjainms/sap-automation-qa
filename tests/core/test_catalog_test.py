# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for authoritative STAF execution catalogs."""

import pytest
from src.core.execution.test_catalog import resolve_offline_test_ids


class TestOfflineTestCatalog:
    """Verify offline test defaults and validation."""

    def test_resolves_default_test(self) -> None:
        """Resolve an empty request to the group's offline test."""
        resolved = resolve_offline_test_ids("DatabaseHighAvailability", [])

        assert resolved == ("ha-config-offline",)

    def test_preserves_valid_request_order(self) -> None:
        """Preserve valid IDs while removing duplicates."""
        resolved = resolve_offline_test_ids(
            "CentralServicesHighAvailability",
            ["ha-config-offline", "ha-config-offline"],
        )

        assert resolved == ("ha-config-offline",)

    def test_rejects_group_without_offline_mode(self) -> None:
        """Reject groups that have no offline execution path."""
        with pytest.raises(ValueError, match="has no offline mode"):
            resolve_offline_test_ids("ConfigurationChecks", [])

    def test_rejects_online_only_test(self) -> None:
        """Reject test IDs that are unavailable in offline mode."""
        with pytest.raises(ValueError, match="invalid test_ids"):
            resolve_offline_test_ids(
                "DatabaseHighAvailability",
                ["primary-node-crash"],
            )
