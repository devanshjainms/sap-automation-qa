# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for workspace fact classification and document rendering."""

# pylint: disable=redefined-outer-name,unused-import

import json
import re
import subprocess
import time
from dataclasses import replace
from pathlib import Path

import pytest

from src.core.exceptions import WorkspaceConfigError, WorkspaceValidationError
from src.core.workspace_collector import COMPACT_COLLECTOR
from src.core.workspace_config import (
    CredentialMaterial,
    GenerateRequest,
    WorkspaceConfigGenerator,
)
from tests.core.workspace_config_fixtures import (
    clusters,
    generate_request,
    generator,
    RESOURCE_ID,
    facts_envelope,
    inventory,
    make_fact,
    run_command_envelope,
)

DISK_ID = "/subscriptions/00000000-0000-0000-0000-000000000000/disks/sbd"


def test_render_accepts_complete_afa_topology(
    generator: WorkspaceConfigGenerator,
    generate_request: GenerateRequest,
    clusters: dict[str, list[dict[str, object]]],
) -> None:
    """Render required HA groups and parameters from complete AFA evidence.

    :param generator: Isolated generator.
    :param generate_request: Valid generation request.
    :param clusters: Complete normalized cluster facts.
    """
    generated = generator._render(
        generate_request.workspace_root / generate_request.workspace_id,
        clusters,
        generate_request,
    )

    assert generated.sap_parameters["scs_cluster_type"] == "AFA"
    assert generated.sap_parameters["database_cluster_type"] == "AFA"
    assert generated.sap_parameters["database_scale_out"] is False
    assert set(generated.hosts) == {"SH7_DB", "SH7_SCS", "SH7_ERS"}


def _device(path: str, lun: str = "", iscsi: bool = False) -> dict[str, object]:
    """Build one collector SBD device record.

    :param path: Configured SBD device path.
    :param lun: Azure data disk LUN the path resolves to, when it resolves to one.
    :param iscsi: Whether udev proves the device uses an iSCSI transport.
    :returns: A device record in the collector's published form.
    """
    return {"path": path, "lun": lun, "iscsi": iscsi}


def _set_fencing(
    clusters: dict[str, list[dict[str, object]]],
    tier: str,
    agents: list[str],
    devices: list[dict[str, object]],
) -> None:
    """Apply identical fencing evidence to every member of one cluster tier.

    :param clusters: Normalized cluster facts.
    :param tier: Cluster tier key to modify.
    :param agents: Normalized fencing resource-agent types.
    :param devices: Backing device records for SBD fencing agents.
    """
    for fact in clusters[tier]:
        cluster = fact["cluster"]
        assert isinstance(cluster, dict)
        cluster["fencing_agents"] = agents
        cluster["fencing_devices"] = [dict(device) for device in devices]


def test_render_classifies_azure_shared_disk_sbd_as_asd(
    generator: WorkspaceConfigGenerator,
    generate_request: GenerateRequest,
    clusters: dict[str, list[dict[str, object]]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Classify SBD backed by proven Azure shared disks as the ASD cluster type.

    :param generator: Isolated generator.
    :param generate_request: Valid generation request.
    :param clusters: Cluster facts modified to contain Azure shared-disk SBD.
    :param monkeypatch: Stubs the resolved managed disk's maxShares value.
    """
    devices = [_device("/dev/disk/azure/scsi1/lun5", lun="5")]
    _set_fencing(clusters, "scs", ["fence_sbd"], devices)
    _set_fencing(clusters, "db", ["fence_sbd"], devices)
    monkeypatch.setattr(generator, "_shared_disk", lambda _resource, _lun: (DISK_ID, 2))

    generated = generator._render(
        generate_request.workspace_root / generate_request.workspace_id,
        clusters,
        generate_request,
    )

    assert generated.sap_parameters["scs_cluster_type"] == "ASD"
    assert generated.sap_parameters["database_cluster_type"] == "ASD"


def test_render_classifies_non_azure_disk_sbd_as_iscsi(
    generator: WorkspaceConfigGenerator,
    generate_request: GenerateRequest,
    clusters: dict[str, list[dict[str, object]]],
) -> None:
    """Classify SBD backed by non-Azure block devices as the iSCSI cluster type.

    :param generator: Isolated generator.
    :param generate_request: Valid generation request.
    :param clusters: Cluster facts modified to contain iSCSI-backed SBD.
    """
    devices = [
        _device("/dev/disk/by-id/scsi-360014059", iscsi=True),
        _device("/dev/disk/by-id/scsi-360014060", iscsi=True),
    ]
    _set_fencing(clusters, "scs", ["external/sbd"], devices)
    _set_fencing(clusters, "db", ["external/sbd"], devices)

    generated = generator._render(
        generate_request.workspace_root / generate_request.workspace_id,
        clusters,
        generate_request,
    )

    assert generated.sap_parameters["scs_cluster_type"] == "ISCSI"
    assert generated.sap_parameters["database_cluster_type"] == "ISCSI"


def test_render_rejects_sbd_without_any_backing_device(
    generator: WorkspaceConfigGenerator,
    generate_request: GenerateRequest,
    clusters: dict[str, list[dict[str, object]]],
) -> None:
    """Refuse SBD evidence that proves no backing device rather than guessing.

    :param generator: Isolated generator.
    :param generate_request: Valid generation request.
    :param clusters: Cluster facts modified to contain deviceless SBD.
    """
    _set_fencing(clusters, "scs", ["external/sbd"], [])

    with pytest.raises(WorkspaceConfigError, match="SBD"):
        generator._render(
            generate_request.workspace_root / generate_request.workspace_id,
            clusters,
            generate_request,
        )


def test_render_rejects_mixed_azure_and_non_azure_sbd_devices(
    generator: WorkspaceConfigGenerator,
    generate_request: GenerateRequest,
    clusters: dict[str, list[dict[str, object]]],
) -> None:
    """Refuse SBD backed by a mixture the framework has no single label for.

    :param generator: Isolated generator.
    :param generate_request: Valid generation request.
    :param clusters: Cluster facts modified to contain mixed SBD devices.
    """
    _set_fencing(
        clusters,
        "scs",
        ["fence_sbd"],
        [
            _device("/dev/disk/azure/scsi1/lun5", lun="5"),
            _device("/dev/disk/by-id/scsi-360014059", iscsi=True),
        ],
    )

    with pytest.raises(WorkspaceConfigError, match="SBD"):
        generator._render(
            generate_request.workspace_root / generate_request.workspace_id,
            clusters,
            generate_request,
        )


def test_render_rejects_sbd_members_that_disagree_on_devices(
    generator: WorkspaceConfigGenerator,
    generate_request: GenerateRequest,
    clusters: dict[str, list[dict[str, object]]],
) -> None:
    """Refuse SBD evidence when one member cannot see a peer's backing devices.

    :param generator: Isolated generator.
    :param generate_request: Valid generation request.
    :param clusters: Cluster facts modified to contain disagreeing SBD devices.
    """
    _set_fencing(clusters, "scs", ["external/sbd"], [_device("/dev/disk/azure/scsi1/lun5", "5")])
    cluster = clusters["scs"][1]["cluster"]
    assert isinstance(cluster, dict)
    cluster["fencing_devices"] = [_device("/dev/disk/by-id/scsi-360014059", iscsi=True)]

    with pytest.raises(WorkspaceConfigError, match="disagree on their backing devices"):
        generator._render(
            generate_request.workspace_root / generate_request.workspace_id,
            clusters,
            generate_request,
        )


def test_render_rejects_an_sbd_member_that_reports_no_devices(
    generator: WorkspaceConfigGenerator,
    generate_request: GenerateRequest,
    clusters: dict[str, list[dict[str, object]]],
) -> None:
    """Refuse SBD when one member proves no devices, rather than trusting its peer.

    :param generator: Isolated generator.
    :param generate_request: Valid generation request.
    :param clusters: Cluster facts where one SBD member reports no devices.
    """
    _set_fencing(clusters, "scs", ["external/sbd"], [_device("/dev/disk/azure/scsi1/lun5", "5")])
    cluster = clusters["scs"][1]["cluster"]
    assert isinstance(cluster, dict)
    cluster["fencing_devices"] = []

    with pytest.raises(WorkspaceConfigError, match="disagree on their backing devices"):
        generator._render(
            generate_request.workspace_root / generate_request.workspace_id,
            clusters,
            generate_request,
        )


def test_render_rejects_ambiguous_mixed_fencing_agents(
    generator: WorkspaceConfigGenerator,
    generate_request: GenerateRequest,
    clusters: dict[str, list[dict[str, object]]],
) -> None:
    """Refuse a tier whose members disagree on the fencing mechanism in use.

    :param generator: Isolated generator.
    :param generate_request: Valid generation request.
    :param clusters: Cluster facts modified to contain conflicting fencing.
    """
    for member in clusters["scs"]:
        member["cluster"]["fencing_agents"] = [  # type: ignore[index]
            "external/sbd",
            "fence_azure_arm",
        ]

    with pytest.raises(WorkspaceConfigError, match="ambiguous"):
        generator._render(
            generate_request.workspace_root / generate_request.workspace_id,
            clusters,
            generate_request,
        )


def test_render_rejects_members_that_disagree_on_fencing(
    generator: WorkspaceConfigGenerator,
    generate_request: GenerateRequest,
    clusters: dict[str, list[dict[str, object]]],
) -> None:
    """Refuse a tier whose members report different fencing agents.

    :param generator: Isolated generator.
    :param generate_request: Valid generation request.
    :param clusters: Cluster facts modified so one member disagrees.
    """
    clusters["scs"][0]["cluster"]["fencing_agents"] = ["external/sbd"]  # type: ignore[index]

    with pytest.raises(WorkspaceConfigError, match="disagree on the fencing agents"):
        generator._render(
            generate_request.workspace_root / generate_request.workspace_id,
            clusters,
            generate_request,
        )


def test_render_rejects_a_member_that_proves_no_fencing(
    generator: WorkspaceConfigGenerator,
    generate_request: GenerateRequest,
    clusters: dict[str, list[dict[str, object]]],
) -> None:
    """Refuse to let a peer's evidence mask a member with no fencing configuration.

    An empty list is exactly what a failed CIB parse produces, so unioning the
    members' agents would let a healthy peer's ``fence_azure_arm`` publish ``AFA``
    for a cluster one member proved unfenced.

    :param generator: Isolated generator.
    :param generate_request: Valid generation request.
    :param clusters: Cluster facts modified so one member reports no fencing.
    """
    clusters["scs"][0]["cluster"]["fencing_agents"] = []  # type: ignore[index]

    with pytest.raises(WorkspaceConfigError, match="reported no fencing agents"):
        generator._render(
            generate_request.workspace_root / generate_request.workspace_id,
            clusters,
            generate_request,
        )


def test_render_rejects_an_unrecognized_fencing_agent(
    generator: WorkspaceConfigGenerator,
    generate_request: GenerateRequest,
    clusters: dict[str, list[dict[str, object]]],
) -> None:
    """Refuse a tier that reports a fencing agent outside the classified families.

    The collector reports every ``stonith`` primitive rather than only the agents
    it recognizes, so an unclassified agent must surface here instead of being
    silently discarded and leaving the remaining agents to imply a clean verdict.

    :param generator: Isolated generator.
    :param generate_request: Valid generation request.
    :param clusters: Cluster facts modified to contain an unclassified agent.
    """
    clusters["scs"][0]["cluster"]["fencing_agents"] = [  # type: ignore[index]
        "fence_azure_arm",
        "fence_vmware_soap",
    ]
    clusters["scs"][1]["cluster"]["fencing_agents"] = [  # type: ignore[index]
        "fence_azure_arm",
        "fence_vmware_soap",
    ]

    with pytest.raises(WorkspaceConfigError, match="ambiguous"):
        generator._render(
            generate_request.workspace_root / generate_request.workspace_id,
            clusters,
            generate_request,
        )


def test_render_derives_scale_out_from_the_hana_host_list(
    generator: WorkspaceConfigGenerator,
    generate_request: GenerateRequest,
    clusters: dict[str, list[dict[str, object]]],
) -> None:
    """Report scale-out when HANA itself spans more than one host.

    The Pacemaker member count cannot answer this: a scale-up pair with a
    majority maker also has three members. Only the host list HANA reports for
    its own system distinguishes the two.

    :param generator: Isolated generator.
    :param generate_request: Valid generation request.
    :param clusters: Cluster facts modified to describe a multi-host system.
    """
    for member in clusters["db"]:
        hana = member["hana"]
        assert isinstance(hana, dict)
        hana["hosts"] = ["db01", "db02"]

    rendered = generator._render(
        generate_request.workspace_root / generate_request.workspace_id,
        clusters,
        generate_request,
    )

    assert rendered.sap_parameters["database_scale_out"] is True


def test_render_rejects_a_database_without_a_reported_host_list(
    generator: WorkspaceConfigGenerator,
    generate_request: GenerateRequest,
    clusters: dict[str, list[dict[str, object]]],
) -> None:
    """Refuse to guess the topology when HANA reported no hosts.

    :param generator: Isolated generator.
    :param generate_request: Valid generation request.
    :param clusters: Cluster facts modified to omit the host list.
    """
    hana = clusters["db"][0]["hana"]
    assert isinstance(hana, dict)
    del hana["hosts"]

    with pytest.raises(WorkspaceConfigError, match="host list"):
        generator._render(
            generate_request.workspace_root / generate_request.workspace_id,
            clusters,
            generate_request,
        )


def test_render_excludes_a_majority_maker_from_the_database_tier(
    generator: WorkspaceConfigGenerator,
    generate_request: GenerateRequest,
    clusters: dict[str, list[dict[str, object]]],
) -> None:
    """Model the majority maker rather than rejecting the topology it belongs to.

    A scale-out cluster's majority maker is a Pacemaker member that runs no HANA.
    Requiring HANA facts from every member would make that supported topology
    impossible to generate, so a node that proves HANA is not installed is treated
    as a witness and left out of the rendered database hosts.

    :param generator: Isolated generator.
    :param generate_request: Valid generation request.
    :param clusters: Cluster facts extended with a majority maker.
    """
    witness = make_fact(
        "db03",
        "/subscriptions/a/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/db03",
        "10.0.1.6",
        hana={"installed": False},
    )
    witness["cluster"]["fencing_agents"] = ["fence_azure_arm"]  # type: ignore[index]
    clusters["db"].append(witness)

    rendered = generator._render(
        generate_request.workspace_root / generate_request.workspace_id,
        clusters,
        generate_request,
    )

    db_hosts = rendered.hosts[f"{rendered.sap_parameters['sap_sid']}_DB"]["hosts"]
    assert "db03" not in db_hosts
    assert set(db_hosts) == {"db01", "db02"}


def test_render_rejects_a_database_node_whose_replication_is_offline(
    generator: WorkspaceConfigGenerator,
    generate_request: GenerateRequest,
    clusters: dict[str, list[dict[str, object]]],
) -> None:
    """Refuse a HANA node whose system replication is not online.

    A node with HANA installed but replication offline must not be mistaken for a
    majority maker and quietly dropped from the topology.

    :param generator: Isolated generator.
    :param generate_request: Valid generation request.
    :param clusters: Cluster facts modified so one node reports offline replication.
    """
    hana = clusters["db"][1]["hana"]
    assert isinstance(hana, dict)
    hana["sr_online"] = False

    with pytest.raises(WorkspaceConfigError, match="replication is not online"):
        generator._render(
            generate_request.workspace_root / generate_request.workspace_id,
            clusters,
            generate_request,
        )


def test_render_rejects_disagreeing_scale_out_topology(
    generator: WorkspaceConfigGenerator,
    generate_request: GenerateRequest,
    clusters: dict[str, list[dict[str, object]]],
) -> None:
    """Refuse a database tier whose members report a different HANA topology.

    Scale-out is derived from the hosts HANA reports for its own system, so
    accepting the first member's host list while another member reports a
    different one would publish a topology half the cluster contradicts.

    :param generator: Isolated generator.
    :param generate_request: Valid generation request.
    :param clusters: Cluster facts modified to contain conflicting host lists.
    """
    first = clusters["db"][0]["hana"]
    second = clusters["db"][1]["hana"]
    assert isinstance(first, dict) and isinstance(second, dict)
    second["hosts"] = list(first["hosts"]) + ["db02"]

    with pytest.raises(WorkspaceConfigError, match="host list"):
        generator._render(
            generate_request.workspace_root / generate_request.workspace_id,
            clusters,
            generate_request,
        )


def test_render_rejects_missing_database_virtual_host(
    generator: WorkspaceConfigGenerator,
    generate_request: GenerateRequest,
    clusters: dict[str, list[dict[str, object]]],
) -> None:
    """Reject a database topology that has no verified virtual host.

    :param generator: Isolated generator.
    :param generate_request: Valid generation request.
    :param clusters: Cluster facts with incomplete HANA virtual-host evidence.
    """
    clusters["db"][1]["hana"]["virtual_host"] = ""  # type: ignore[index]

    with pytest.raises(WorkspaceConfigError, match="missing a virtual host"):
        generator._render(
            generate_request.workspace_root / generate_request.workspace_id,
            clusters,
            generate_request,
        )


def test_parse_run_command_rejects_oversized_collector_output(
    generator: WorkspaceConfigGenerator,
) -> None:
    """Reject output beyond Azure Action Run Command's fixed output limit.

    :param generator: Isolated generator.
    """
    envelope = run_command_envelope(
        json.dumps({"schema_version": 2, "padding": "x" * 4200}, separators=(",", ":"))
    )

    with pytest.raises(WorkspaceConfigError, match="exceeds 4096"):
        generator._parse_run_command(envelope, "scs01")


def test_publish_never_overwrites_existing_configuration(
    generator: WorkspaceConfigGenerator,
    generate_request: GenerateRequest,
    clusters: dict[str, list[dict[str, object]]],
) -> None:
    """Refuse publication when a user configuration appears before the write.

    :param generator: Isolated generator.
    :param generate_request: Valid generation request.
    :param clusters: Complete normalized cluster facts.
    """
    generated = generator._render(
        generate_request.workspace_root / generate_request.workspace_id,
        clusters,
        generate_request,
    )
    generated.workspace_path.mkdir(parents=True)
    (generated.workspace_path / "hosts.yaml").write_text("user-owned", encoding="utf-8")

    with pytest.raises(WorkspaceConfigError, match="does not overwrite"):
        generator._publish(generated.workspace_path, generated, generate_request.credential)


def test_publish_writes_a_complete_initial_workspace(
    generator: WorkspaceConfigGenerator,
    generate_request: GenerateRequest,
    clusters: dict[str, list[dict[str, object]]],
) -> None:
    """Publish a complete, validated pair into an empty workspace directory.

    :param generator: Isolated generator.
    :param generate_request: Valid generation request.
    :param clusters: Complete normalized cluster facts.
    """
    generated = generator._render(
        generate_request.workspace_root / generate_request.workspace_id,
        clusters,
        generate_request,
    )

    generator._publish(generated.workspace_path, generated, generate_request.credential)

    assert (generated.workspace_path / "sap-parameters.yaml").is_file()
    assert (generated.workspace_path / "hosts.yaml").is_file()
    assert (generated.workspace_path / "ssh_key").is_file()


def test_parse_run_command_accepts_one_compact_fact(generator: WorkspaceConfigGenerator) -> None:
    """Accept a schema-versioned compact collector document from Azure CLI.

    :param generator: Isolated generator.
    """
    facts = make_fact(
        "scs01",
        "/subscriptions/a/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/scs01",
        "10.0.0.4",
    )
    envelope = {
        "value": [
            {
                "code": "ComponentStatus/StdOut/succeeded",
                "message": json.dumps(facts, separators=(",", ":")),
            }
        ]
    }

    assert generator._parse_run_command(json.dumps(envelope), "scs01") == facts


def test_collector_reads_sbd_devices_from_the_guest_sbd_configuration() -> None:
    """Prove the collector sources SBD devices from /etc/sysconfig/sbd, not only the CIB.

    A SUSE ``external/sbd`` STONITH primitive carries no device parameter - the
    repository's own fixture in ``tests/modules/pcmk_constants.py`` only sets
    ``pcmk_delay_max`` - so the configured devices must come from the guest.
    """
    assert "/etc/sysconfig/sbd" in COMPACT_COLLECTOR

    pattern = re.search(r"re\.findall\(r'(.+?)',sbd_conf\)", COMPACT_COLLECTOR)
    assert pattern is not None
    expression = pattern.group(1)

    azure = 'SBD_DEVICE="/dev/disk/azure/scsi1/lun0;/dev/disk/azure/scsi1/lun1"\n'
    iscsi = "SBD_DEVICE=/dev/disk/by-id/scsi-360014051 /dev/disk/by-id/scsi-360014052\n"
    ignored = "#SBD_DEVICE=\"/dev/commented/out\"\nSBD_DEVICE=''\n"

    def parse(text: str) -> list[str]:
        """Apply the collector's own expression to a sample sbd configuration.

        :param text: Sample ``/etc/sysconfig/sbd`` content.
        :returns: Devices the collector would report for that content.
        """
        found: list[str] = []
        for value in re.findall(expression, text):
            found += [part for part in re.split(r"[;,\s]+", value) if part]
        return found

    assert parse(azure) == ["/dev/disk/azure/scsi1/lun0", "/dev/disk/azure/scsi1/lun1"]
    assert parse(iscsi) == [
        "/dev/disk/by-id/scsi-360014051",
        "/dev/disk/by-id/scsi-360014052",
    ]
    assert parse(ignored) == []


def test_render_rejects_an_azure_disk_that_is_not_shared(
    generator: WorkspaceConfigGenerator,
    generate_request: GenerateRequest,
    clusters: dict[str, list[dict[str, object]]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Refuse an ordinary Azure data disk that merely looks like a shared disk.

    :param generator: Isolated generator.
    :param generate_request: Valid generation request.
    :param clusters: Cluster facts modified to contain an unshared Azure disk.
    :param monkeypatch: Stubs the resolved managed disk's maxShares value.
    """
    _set_fencing(clusters, "scs", ["fence_sbd"], [_device("/dev/disk/azure/scsi1/lun5", "5")])
    monkeypatch.setattr(generator, "_shared_disk", lambda _resource, _lun: (DISK_ID, 1))

    with pytest.raises(WorkspaceConfigError, match="not a shared disk"):
        generator._render(
            generate_request.workspace_root / generate_request.workspace_id,
            clusters,
            generate_request,
        )


def test_render_rejects_a_device_that_proves_no_transport(
    generator: WorkspaceConfigGenerator,
    generate_request: GenerateRequest,
    clusters: dict[str, list[dict[str, object]]],
) -> None:
    """Refuse a device path that proves neither an iSCSI transport nor an Azure disk.

    :param generator: Isolated generator.
    :param generate_request: Valid generation request.
    :param clusters: Cluster facts modified to contain an unprovable device.
    """
    _set_fencing(clusters, "scs", ["external/sbd"], [_device("/dev/disk/by-id/scsi-360014059")])

    with pytest.raises(WorkspaceConfigError, match="prove neither an iSCSI transport"):
        generator._render(
            generate_request.workspace_root / generate_request.workspace_id,
            clusters,
            generate_request,
        )


def test_render_rejects_legacy_string_device_evidence(
    generator: WorkspaceConfigGenerator,
    generate_request: GenerateRequest,
    clusters: dict[str, list[dict[str, object]]],
) -> None:
    """Refuse device evidence produced by a collector predating transport proof.

    :param generator: Isolated generator.
    :param generate_request: Valid generation request.
    :param clusters: Cluster facts modified to contain bare device strings.
    """
    for fact in clusters["scs"]:
        cluster = fact["cluster"]
        assert isinstance(cluster, dict)
        cluster["fencing_agents"] = ["external/sbd"]
        cluster["fencing_devices"] = ["/dev/disk/azure/scsi1/lun5"]

    with pytest.raises(WorkspaceConfigError, match="not in the expected form"):
        generator._render(
            generate_request.workspace_root / generate_request.workspace_id,
            clusters,
            generate_request,
        )


def test_render_rejects_members_resolving_devices_to_different_disks(
    generator: WorkspaceConfigGenerator,
    generate_request: GenerateRequest,
    clusters: dict[str, list[dict[str, object]]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Refuse share-capable disks that are not the same disk on every member.

    :param generator: Isolated generator.
    :param generate_request: Valid generation request.
    :param clusters: Cluster facts modified to contain a shared-disk SBD device.
    :param monkeypatch: Resolves each member's LUN to a distinct managed disk.
    """
    _set_fencing(clusters, "scs", ["fence_sbd"], [_device("/dev/disk/azure/scsi1/lun5", "5")])
    seen: list[str] = []

    def resolve(resource_id: str, _lun: str) -> tuple[str, int]:
        """Return a distinct share-capable disk for each calling member.

        :param resource_id: Azure resource ID of the calling member.
        :param _lun: Unused data disk LUN.
        :returns: A per-member managed disk ID and a shared ``maxShares``.
        """
        if resource_id not in seen:
            seen.append(resource_id)
        return f"{DISK_ID}-{seen.index(resource_id)}", 2

    monkeypatch.setattr(generator, "_shared_disk", resolve)

    with pytest.raises(WorkspaceConfigError, match="different Azure managed"):
        generator._render(
            generate_request.workspace_root / generate_request.workspace_id,
            clusters,
            generate_request,
        )
