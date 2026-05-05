# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""System properties and applicability matching for rule filtering."""

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass(frozen=True)
class SystemProperties:
    """Properties of the target SAP system used to filter applicable rules.

    :param database_type: Database engine (HANA, DB2, ASE, etc.).
    :param ha_enabled: Whether HA/Pacemaker is configured.
    :param hana_topology: HANA replication topology.
    :param os_family: Operating system family (SUSE, REDHAT).
    :param hsr_provider: HANA SR provider type.
    :param storage_type: Underlying storage technology.
    :param scs_type: SAP Central Services enqueue type.
    :param instance_type: SAP instance type (app, ascs, db, ers).
    """

    database_type: Optional[str] = None
    ha_enabled: Optional[bool] = None
    hana_topology: Optional[str] = None
    os_family: Optional[str] = None
    hsr_provider: Optional[str] = None
    storage_type: Optional[str] = None
    scs_type: Optional[str] = None
    instance_type: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dictionary.

        :returns: Dictionary with non-None properties only.
        :rtype: dict[str, Any]
        """
        return {k: v for k, v in self.__dict__.items() if v is not None}


@dataclass(frozen=True)
class Applicability:
    """Filter criteria that determine whether a rule applies to a system.

    :param database_type: Matching database types.
    :param ha_enabled: Whether HA must be enabled.
    :param hana_topology: Matching HANA topologies.
    :param os_family: Matching OS families.
    :param hsr_provider: Matching HSR providers.
    :param storage_type: Matching storage types.
    :param scs_type: Matching SCS types.
    :param instance_type: Matching instance types.
    """

    database_type: Optional[str] = None
    ha_enabled: Optional[bool] = None
    hana_topology: list[str] = field(default_factory=list)
    os_family: list[str] = field(default_factory=list)
    hsr_provider: list[str] = field(default_factory=list)
    storage_type: Optional[str] = None
    scs_type: Optional[str] = None
    instance_type: Optional[str] = None

    def matches(self, system: SystemProperties) -> bool:
        """Check whether a system matches this applicability filter.

        :param system: Target system properties.
        :type system: SystemProperties
        :returns: True if all specified filters match.
        :rtype: bool
        """
        if self.database_type is not None and system.database_type is not None:
            if self.database_type.upper() != system.database_type.upper():
                return False

        if self.ha_enabled is not None and system.ha_enabled is not None:
            if self.ha_enabled != system.ha_enabled:
                return False

        if self.hana_topology and system.hana_topology is not None:
            if system.hana_topology.lower() not in [t.lower() for t in self.hana_topology]:
                return False

        if self.os_family and system.os_family is not None:
            if system.os_family.upper() not in [f.upper() for f in self.os_family]:
                return False

        if self.hsr_provider and system.hsr_provider is not None:
            if system.hsr_provider not in self.hsr_provider:
                return False

        if self.storage_type is not None and system.storage_type is not None:
            if self.storage_type.lower() != system.storage_type.lower():
                return False

        if self.scs_type is not None and system.scs_type is not None:
            if self.scs_type.upper() != system.scs_type.upper():
                return False

        if self.instance_type is not None and system.instance_type is not None:
            if self.instance_type.lower() != system.instance_type.lower():
                return False

        return True
