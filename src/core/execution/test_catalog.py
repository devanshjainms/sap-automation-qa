# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.


"""Static mapping from STAF test groups to authoritative playbooks."""

from collections.abc import Sequence

TEST_GROUP_PLAYBOOKS: dict[str, str] = {
    "ConfigurationChecks": "playbook_00_configuration_checks.yml",
    "DatabaseHighAvailability": "playbook_00_ha_db_functional_tests.yml",
    "CentralServicesHighAvailability": "playbook_00_ha_scs_functional_tests.yml",
    "AzureBackupDatabase": "playbook_00_backup_db_functional_tests.yml",
}

OFFLINE_PLAYBOOK = "playbook_01_ha_offline_tests.yml"

OFFLINE_TEST_IDS_BY_GROUP: dict[str, frozenset[str]] = {
    "DatabaseHighAvailability": frozenset({"ha-config-offline"}),
    "CentralServicesHighAvailability": frozenset({"ha-config-offline"}),
}


def resolve_offline_test_ids(
    test_group: str,
    requested_test_ids: Sequence[str],
) -> tuple[str, ...]:
    """Resolve and validate test IDs for offline execution.

    :param test_group: Canonical STAF test group.
    :param requested_test_ids: Requested test IDs, or an empty sequence for all
        offline tests in the group.
    :returns: Validated offline test IDs in deterministic request order.
    :raises ValueError: If the group has no offline mode or a requested test is
        not available offline.
    """
    available = OFFLINE_TEST_IDS_BY_GROUP.get(test_group)
    if not available:
        raise ValueError(f"'{test_group}' has no offline mode")

    if not requested_test_ids:
        return tuple(sorted(available))

    requested = tuple(dict.fromkeys(requested_test_ids))
    invalid = sorted(set(requested) - available)
    if invalid:
        raise ValueError(
            f"Offline execution for '{test_group}' supports only "
            f"{sorted(available)}; invalid test_ids: {invalid}"
        )
    return requested
