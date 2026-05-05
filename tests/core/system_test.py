# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for system properties and applicability matching."""

import pytest
from src.core.models.system import Applicability, SystemProperties


class TestSystemProperties:
    """Unit tests for SystemProperties frozen dataclass."""

    def test_create_full(self) -> None:
        """Verify creation with all fields populated."""
        sp = SystemProperties(
            database_type="HANA",
            ha_enabled=True,
            hana_topology="scale_up",
            os_family="SUSE",
            hsr_provider="SAPHanaSR",
            storage_type="premium_ssd",
            scs_type="ENSA2",
            instance_type="db",
        )
        assert sp.database_type == "HANA"
        assert sp.ha_enabled is True
        assert sp.instance_type == "db"

    def test_create_minimal(self) -> None:
        """Verify creation with all defaults (None)."""
        sp = SystemProperties()
        assert sp.database_type is None
        assert sp.ha_enabled is None

    def test_frozen(self) -> None:
        """Verify immutability."""
        sp = SystemProperties(database_type="HANA")
        with pytest.raises(AttributeError):
            sp.database_type = "DB2"  # type: ignore[misc]

    def test_to_dict_filters_none(self) -> None:
        """Verify to_dict only includes non-None values."""
        sp = SystemProperties(database_type="HANA", ha_enabled=True)
        d = sp.to_dict()
        assert d == {"database_type": "HANA", "ha_enabled": True}

    def test_to_dict_empty(self) -> None:
        """Verify to_dict returns empty dict when all None."""
        sp = SystemProperties()
        assert sp.to_dict() == {}


class TestApplicability:
    """Unit tests for Applicability matching logic."""

    def test_empty_matches_anything(self) -> None:
        """Empty applicability matches any system."""
        app = Applicability()
        system = SystemProperties(database_type="HANA", ha_enabled=True, os_family="SUSE")
        assert app.matches(system) is True

    def test_database_type_match(self) -> None:
        """Matching database_type returns True."""
        app = Applicability(database_type="HANA")
        system = SystemProperties(database_type="HANA")
        assert app.matches(system) is True

    def test_database_type_case_insensitive(self) -> None:
        """Database type matching is case-insensitive."""
        app = Applicability(database_type="hana")
        system = SystemProperties(database_type="HANA")
        assert app.matches(system) is True

    def test_database_type_mismatch(self) -> None:
        """Non-matching database_type returns False."""
        app = Applicability(database_type="HANA")
        system = SystemProperties(database_type="DB2")
        assert app.matches(system) is False

    def test_ha_enabled_match(self) -> None:
        """Matching ha_enabled returns True."""
        app = Applicability(ha_enabled=True)
        system = SystemProperties(ha_enabled=True)
        assert app.matches(system) is True

    def test_ha_enabled_mismatch(self) -> None:
        """Non-matching ha_enabled returns False."""
        app = Applicability(ha_enabled=True)
        system = SystemProperties(ha_enabled=False)
        assert app.matches(system) is False

    def test_hana_topology_list_match(self) -> None:
        """System topology in the list returns True."""
        app = Applicability(hana_topology=["scale_up", "scale_out_hsr"])
        system = SystemProperties(hana_topology="scale_up")
        assert app.matches(system) is True

    def test_hana_topology_list_mismatch(self) -> None:
        """System topology not in the list returns False."""
        app = Applicability(hana_topology=["scale_up"])
        system = SystemProperties(hana_topology="scale_out_standby")
        assert app.matches(system) is False

    def test_hana_topology_case_insensitive(self) -> None:
        """Topology matching is case-insensitive."""
        app = Applicability(hana_topology=["Scale_Up"])
        system = SystemProperties(hana_topology="scale_up")
        assert app.matches(system) is True

    def test_os_family_list_match(self) -> None:
        """System OS in the list returns True."""
        app = Applicability(os_family=["SUSE", "REDHAT"])
        system = SystemProperties(os_family="SUSE")
        assert app.matches(system) is True

    def test_os_family_case_insensitive(self) -> None:
        """OS family matching is case-insensitive."""
        app = Applicability(os_family=["suse"])
        system = SystemProperties(os_family="SUSE")
        assert app.matches(system) is True

    def test_os_family_mismatch(self) -> None:
        """System OS not in the list returns False."""
        app = Applicability(os_family=["SUSE"])
        system = SystemProperties(os_family="REDHAT")
        assert app.matches(system) is False

    def test_hsr_provider_match(self) -> None:
        """Matching HSR provider returns True."""
        app = Applicability(hsr_provider=["SAPHanaSR", "SAPHanaSR-angi"])
        system = SystemProperties(hsr_provider="SAPHanaSR")
        assert app.matches(system) is True

    def test_hsr_provider_mismatch(self) -> None:
        """Non-matching HSR provider returns False."""
        app = Applicability(hsr_provider=["SAPHanaSR-angi"])
        system = SystemProperties(hsr_provider="SAPHanaSR")
        assert app.matches(system) is False

    def test_storage_type_match(self) -> None:
        """Matching storage_type returns True."""
        app = Applicability(storage_type="anf")
        system = SystemProperties(storage_type="ANF")
        assert app.matches(system) is True

    def test_storage_type_mismatch(self) -> None:
        """Non-matching storage_type returns False."""
        app = Applicability(storage_type="anf")
        system = SystemProperties(storage_type="premium_ssd")
        assert app.matches(system) is False

    def test_scs_type_match(self) -> None:
        """Matching SCS type returns True."""
        app = Applicability(scs_type="ENSA2")
        system = SystemProperties(scs_type="ensa2")
        assert app.matches(system) is True

    def test_instance_type_match(self) -> None:
        """Matching instance type returns True."""
        app = Applicability(instance_type="db")
        system = SystemProperties(instance_type="DB")
        assert app.matches(system) is True

    def test_multiple_filters_all_match(self) -> None:
        """All filters matching returns True."""
        app = Applicability(
            database_type="HANA",
            ha_enabled=True,
            os_family=["SUSE"],
            hana_topology=["scale_up"],
        )
        system = SystemProperties(
            database_type="HANA",
            ha_enabled=True,
            os_family="SUSE",
            hana_topology="scale_up",
        )
        assert app.matches(system) is True

    def test_multiple_filters_one_mismatch(self) -> None:
        """One filter not matching returns False."""
        app = Applicability(
            database_type="HANA",
            ha_enabled=True,
            os_family=["SUSE"],
        )
        system = SystemProperties(
            database_type="HANA",
            ha_enabled=True,
            os_family="REDHAT",
        )
        assert app.matches(system) is False

    def test_none_system_value_skips_check(self) -> None:
        """When system property is None, that filter is skipped."""
        app = Applicability(database_type="HANA")
        system = SystemProperties()
        assert app.matches(system) is True

    def test_empty_list_matches_anything(self) -> None:
        """Empty list filter matches any system value."""
        app = Applicability(os_family=[])
        system = SystemProperties(os_family="SUSE")
        assert app.matches(system) is True
