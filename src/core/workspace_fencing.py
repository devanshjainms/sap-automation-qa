# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Classify a cluster's fencing mechanism from proven runtime evidence.

Device path naming proves nothing on its own: ``/dev/disk/azure/`` is used by
ordinary Azure data disks as well as shared disks, and a non-Azure path does
not prove an iSCSI transport. Classification therefore uses udev transport
evidence collected in the guest and, for Azure disks, the resolved managed
disk's ``maxShares`` value.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping, Sequence

from src.core.exceptions import WorkspaceConfigError

SBD_AGENTS = frozenset({"external/sbd", "fence_sbd"})

SharedDiskResolver = Callable[[str, str], tuple[str, int]]


def _member_agents(fact: Mapping[str, Any], tier: str) -> list[str]:
    """Read one member's fencing agents, rejecting missing or unusable evidence.

    :param fact: Normalized facts for one cluster member.
    :param tier: Tier name used for diagnostics.
    :returns: The member's sorted, deduplicated fencing agents.
    :raises WorkspaceConfigError: When the member proves no usable fencing evidence.
    """
    cluster = fact.get("cluster")
    agents = cluster.get("fencing_agents") if isinstance(cluster, dict) else None
    if not isinstance(agents, list) or not all(isinstance(agent, str) for agent in agents):
        raise WorkspaceConfigError(f"{tier} fencing evidence is missing")
    if not agents:
        raise WorkspaceConfigError(
            f"{tier} cluster member reported no fencing agents; a member that proves "
            "no fencing configuration cannot be classified from its peers"
        )
    return sorted(set(agents))


def _member_devices(fact: Mapping[str, Any], tier: str) -> list[dict[str, Any]]:
    """Read one member's SBD device evidence in the collector's record form.

    :param fact: Normalized facts for one cluster member.
    :param tier: Tier name used for diagnostics.
    :returns: Device records carrying a path, an Azure LUN, and iSCSI evidence.
    :raises WorkspaceConfigError: When a device record is not in the expected form.
    """
    cluster = fact.get("cluster")
    found = cluster.get("fencing_devices") if isinstance(cluster, dict) else None
    records: list[dict[str, Any]] = []
    for item in found if isinstance(found, list) else []:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise WorkspaceConfigError(
                f"{tier} SBD device evidence is not in the expected form; regenerate "
                "with a current collector"
            )
        if not item["path"]:
            continue
        records.append(
            {
                "path": item["path"],
                "lun": str(item.get("lun") or ""),
                "iscsi": bool(item.get("iscsi")),
            }
        )
    return sorted(records, key=lambda record: record["path"])


def _classify_devices(
    records: Sequence[Mapping[str, Any]],
    resource_id: str,
    tier: str,
    resolve_shared_disk: SharedDiskResolver,
) -> tuple[str, tuple[str, ...]]:
    """Classify one member's SBD devices from transport and shared-disk proof.

    :param records: The member's device records.
    :param resource_id: Azure resource ID of the member reporting the devices.
    :param tier: Tier name used for diagnostics.
    :param resolve_shared_disk: Resolves a VM LUN to its disk ID and ``maxShares``.
    :returns: ``ASD`` or ``ISCSI``, and the managed disks the devices resolve to.
    :raises WorkspaceConfigError: When the evidence does not prove either transport.
    """
    paths = [record["path"] for record in records]
    if all(record["iscsi"] for record in records):
        return "ISCSI", ()
    if any(record["iscsi"] for record in records):
        raise WorkspaceConfigError(f"{tier} SBD mixes iSCSI and non-iSCSI devices: {paths}")
    unresolved = [record["path"] for record in records if not record["lun"]]
    if unresolved:
        raise WorkspaceConfigError(
            f"{tier} SBD devices prove neither an iSCSI transport nor an Azure "
            f"data disk: {unresolved}"
        )
    disks: list[str] = []
    for record in records:
        disk_id, shares = resolve_shared_disk(resource_id, record["lun"])
        if shares < 2:
            raise WorkspaceConfigError(
                f"{tier} SBD device {record['path']} resolves to an Azure disk with "
                f"maxShares {shares}; it is not a shared disk"
            )
        disks.append(disk_id.lower())
    return "ASD", tuple(sorted(disks))


def classify_fencing(
    facts: Sequence[Mapping[str, Any]],
    tier: str,
    resolve_shared_disk: SharedDiskResolver,
) -> str:
    """Classify a cluster's fencing mechanism from unambiguous Pacemaker evidence.

    ``fence_azure_arm`` is AFA. SBD is classified only when every member agrees
    on the same devices and those devices prove their own transport.

    :param facts: Normalized facts from every discovered member of one tier.
    :param tier: Tier name used for diagnostics.
    :param resolve_shared_disk: Resolves a VM LUN to its disk ID and ``maxShares``.
    :returns: ``AFA``, ``ASD``, or ``ISCSI``.
    :raises WorkspaceConfigError: When fencing evidence is missing or ambiguous.
    """
    observed = [_member_agents(fact, tier) for fact in facts]
    if any(item != observed[0] for item in observed[1:]):
        raise WorkspaceConfigError(
            f"{tier} cluster members disagree on the fencing agents in use: "
            f"{sorted(set().union(*observed))}"
        )
    agent_set = set(observed[0])
    if agent_set == {"fence_azure_arm"}:
        return "AFA"
    if not agent_set or not agent_set <= SBD_AGENTS:
        raise WorkspaceConfigError(f"{tier} fencing is ambiguous: {sorted(agent_set)}")

    devices = [_member_devices(fact, tier) for fact in facts]
    paths = [[record["path"] for record in member] for member in devices]
    if any(item != paths[0] for item in paths[1:]):
        raise WorkspaceConfigError(f"{tier} SBD members disagree on their backing devices: {paths}")
    if not paths[0]:
        raise WorkspaceConfigError(f"{tier} SBD exposes no backing devices")

    resolved = set()
    for fact, records in zip(facts, devices):
        identity = fact.get("identity")
        resource_id = identity.get("resource_id", "") if isinstance(identity, dict) else ""
        resolved.add(_classify_devices(records, str(resource_id), tier, resolve_shared_disk))
    transports = {item[0] for item in resolved}
    if len(transports) != 1:
        raise WorkspaceConfigError(
            f"{tier} SBD members prove different device transports: {sorted(transports)}"
        )
    if len(resolved) != 1:
        raise WorkspaceConfigError(
            f"{tier} SBD members resolve their devices to different Azure managed "
            f"disks: {sorted(item[1] for item in resolved)}"
        )
    return transports.pop()
