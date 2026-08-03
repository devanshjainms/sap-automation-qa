# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for safe initial workspace configuration generation."""

# pylint: disable=redefined-outer-name

import json
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from src.core.exceptions import WorkspaceConfigError, WorkspaceValidationError
from src.core.workspace_config import (
    CredentialMaterial,
    GenerateRequest,
    WorkspaceConfigGenerator,
)


def _fact(
    hostname: str,
    resource_id: str,
    address: str,
    *,
    fencing_agents: list[str] | None = None,
    fencing_devices: list[str] | None = None,
    instances: list[dict[str, str]] | None = None,
    hana: dict[str, object] | None = None,
) -> dict[str, object]:
    """Create a normalized collector fact for isolated service tests.

    :param hostname: Guest host name.
    :param resource_id: Exact IMDS resource identifier.
    :param address: Guest private address.
    :param fencing_agents: Normalized fencing resource-agent types.
    :param fencing_devices: Backing block devices for SBD fencing agents.
    :param instances: Semantic SCS/ERS resource facts.
    :param hana: Normalized HANA facts.
    :returns: Collector fact document.
    """
    return {
        "schema_version": 2,
        "identity": {
            "resource_id": resource_id,
            "hostname": hostname,
            "private_ip": address,
            "vm_name": hostname.upper(),
            "admin_user": "azureadm",
        },
        "cluster": {
            "members": [hostname],
            "fencing_agents": fencing_agents or ["fence_azure_arm"],
            "fencing_devices": fencing_devices or [],
            "sap_instances": instances or [],
        },
        "hana": hana,
        "storage": {
            "nfs_sources": ["127.0.0.1:/sapfiles/sapmnt/sapmntSH7"],
            "sapmnt_source": "127.0.0.1:/sapfiles/sapmnt/sapmntSH7",
        },
    }


@pytest.fixture
def generator(tmp_path: Path) -> WorkspaceConfigGenerator:
    """Create a generator with a local repository root.

    :param tmp_path: Pytest temporary directory.
    :returns: Isolated generator.
    """

    def run(command: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        """Return exact Azure Files metadata for the test mount endpoint.

        :returns: Successful Azure CLI process result.
        """
        assert command[:3] == ["az", "storage", "account"]
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(
                {"primaryEndpoints": {"file": "https://sapfiles.file.core.windows.net/"}}
            ),
            stderr="",
        )

    return WorkspaceConfigGenerator(tmp_path, run=run)


@pytest.fixture
def generate_request(tmp_path: Path) -> GenerateRequest:
    """Create a valid request with explicit local credential selection.

    :param tmp_path: Pytest temporary directory.
    :returns: Valid generation request.
    """
    credential = tmp_path / "source-key"
    credential.write_text("private-key", encoding="utf-8")
    return GenerateRequest(
        workspace_root=tmp_path / "WORKSPACES" / "SYSTEM",
        workspace_id="DEV-EUS2-SAP01-SH7",
        resource_group="rg",
        scs_seed_vm="scs01",
        db_seed_vm="db01",
        credential=CredentialMaterial(credential, "ssh_key"),
    )


@pytest.fixture
def clusters() -> dict[str, list[dict[str, object]]]:
    """Create an unambiguous two-node AFA SCS and HANA topology.

    :returns: Normalized cluster facts.
    """
    instances = [
        {
            "sid": "SH7",
            "role": "ASCS",
            "instance_number": "01",
            "virtual_host": "sh7ascs",
            "vip": "10.0.0.10",
        },
        {
            "sid": "SH7",
            "role": "ERS",
            "instance_number": "02",
            "virtual_host": "sh7ers",
            "vip": "10.0.0.11",
        },
    ]
    return {
        "scs": [
            _fact(
                "scs01",
                "/subscriptions/a/resourceGroups/rg/providers/"
                "Microsoft.Compute/virtualMachines/scs01",
                "10.0.0.4",
                instances=instances,
            ),
            _fact(
                "scs02",
                "/subscriptions/a/resourceGroups/rg/providers/"
                "Microsoft.Compute/virtualMachines/scs02",
                "10.0.0.5",
                instances=instances,
            ),
        ],
        "db": [
            _fact(
                "db01",
                "/subscriptions/a/resourceGroups/rg/providers/"
                "Microsoft.Compute/virtualMachines/db01",
                "10.0.1.4",
                hana={
                    "sid": "HDB",
                    "instance_number": "00",
                    "virtual_host": "vdb01",
                    "scale_out": False,
                },
            ),
            _fact(
                "db02",
                "/subscriptions/a/resourceGroups/rg/providers/"
                "Microsoft.Compute/virtualMachines/db02",
                "10.0.1.5",
                hana={
                    "sid": "HDB",
                    "instance_number": "00",
                    "virtual_host": "vdb02",
                    "scale_out": False,
                },
            ),
        ],
    }


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


def _set_fencing(
    clusters: dict[str, list[dict[str, object]]],
    tier: str,
    agents: list[str],
    devices: list[str],
) -> None:
    """Apply identical fencing evidence to every member of one cluster tier.

    :param clusters: Normalized cluster facts.
    :param tier: Cluster tier key to modify.
    :param agents: Normalized fencing resource-agent types.
    :param devices: Backing block devices for SBD fencing agents.
    """
    for fact in clusters[tier]:
        cluster = fact["cluster"]
        assert isinstance(cluster, dict)
        cluster["fencing_agents"] = agents
        cluster["fencing_devices"] = devices


def test_render_classifies_azure_shared_disk_sbd_as_asd(
    generator: WorkspaceConfigGenerator,
    generate_request: GenerateRequest,
    clusters: dict[str, list[dict[str, object]]],
) -> None:
    """Classify SBD backed by Azure shared disks as the ASD cluster type.

    :param generator: Isolated generator.
    :param generate_request: Valid generation request.
    :param clusters: Cluster facts modified to contain Azure shared-disk SBD.
    """
    devices = ["/dev/disk/azure/data/by-lun/5"]
    _set_fencing(clusters, "scs", ["fence_sbd"], devices)
    _set_fencing(clusters, "db", ["fence_sbd"], devices)

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
    devices = ["/dev/disk/by-id/scsi-360014059", "/dev/disk/by-id/scsi-360014060"]
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
        ["/dev/disk/azure/data/by-lun/5", "/dev/disk/by-id/scsi-360014059"],
    )

    with pytest.raises(WorkspaceConfigError, match="SBD"):
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
    clusters["scs"][0]["cluster"]["fencing_agents"] = ["external/sbd"]  # type: ignore[index]

    with pytest.raises(WorkspaceConfigError, match="ambiguous"):
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
    envelope = _run_command_envelope(
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
    facts = _fact(
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


RESOURCE_ID = "/subscriptions/a/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/{0}"


def _inventory(names: list[str]) -> list[dict[str, object]]:
    """Create an Azure VM inventory whose computer names match cluster members.

    :param names: Guest host names present in the resource group.
    :returns: Azure CLI VM inventory entries.
    """
    return [
        {
            "id": RESOURCE_ID.format(name),
            "name": name,
            "osProfile": {"computerName": name, "adminUsername": "azureadm"},
        }
        for name in names
    ]


def _run_command_envelope(payload: str) -> str:
    """Wrap collector output in the exact Azure Run Command response envelope.

    Azure returns a single provisioning-state entry whose message embeds both
    streams, so the fixture reproduces that shape rather than a per-stream entry.

    :param payload: Raw standard-output text produced by the collector.
    :returns: Serialized Run Command response.
    """
    return json.dumps(
        {
            "value": [
                {
                    "code": "ProvisioningState/succeeded",
                    "displayStatus": "Provisioning succeeded",
                    "level": "Info",
                    "message": f"Enable succeeded: \n[stdout]\n{payload}\n\n[stderr]\n",
                    "time": None,
                }
            ]
        }
    )


def _facts_envelope(facts: dict[str, object]) -> str:
    """Wrap collector facts in the exact Azure Run Command response envelope.

    :param facts: Normalized collector facts.
    :returns: Serialized Run Command response.
    """
    return _run_command_envelope(json.dumps(facts, separators=(",", ":")))


@pytest.fixture
def discovered_facts(clusters: dict[str, list[dict[str, object]]]) -> dict[str, dict[str, object]]:
    """Index complete cluster facts by guest host name and declare both members.

    :param clusters: Complete normalized cluster facts.
    :returns: Collector facts keyed by guest host name.
    """
    indexed: dict[str, dict[str, object]] = {}
    for tier_facts in clusters.values():
        members = [str(fact["identity"]["hostname"]) for fact in tier_facts]  # type: ignore[index]
        for fact in tier_facts:
            fact["cluster"]["members"] = members  # type: ignore[index]
            indexed[str(fact["identity"]["hostname"])] = fact  # type: ignore[index]
    return indexed


@pytest.fixture
def azure_generator(
    tmp_path: Path, discovered_facts: dict[str, dict[str, object]]
) -> WorkspaceConfigGenerator:
    """Create a generator backed by a scripted Azure CLI and validator runner.

    :param tmp_path: Pytest temporary directory.
    :param discovered_facts: Collector facts keyed by guest host name.
    :returns: Generator that discovers a complete two-node AFA topology.
    """

    def run(command: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        """Answer each scripted Azure CLI and validator invocation.

        :param command: Executed command line.
        :param _kwargs: Ignored subprocess options.
        :returns: Successful process result for the recognized command.
        """

        def result(stdout: str) -> subprocess.CompletedProcess[str]:
            """Build a successful completed process.

            :param stdout: Standard output for the caller to parse.
            :returns: Successful process result.
            """
            return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

        if command[0] != "az":
            return result("")
        if command[1:3] == ["vm", "list"]:
            return result(json.dumps(_inventory(sorted(discovered_facts))))
        name = command[command.index("--name") + 1]
        if command[1:3] == ["vm", "show"]:
            return result(
                json.dumps(
                    {
                        "id": RESOURCE_ID.format(name),
                        "osProfile": {"adminUsername": "azureadm"},
                    }
                )
            )
        if command[1:3] == ["vm", "run-command"]:
            return result(_facts_envelope(discovered_facts[name]))
        return result(
            json.dumps({"primaryEndpoints": {"file": "https://sapfiles.file.core.windows.net/"}})
        )

    return WorkspaceConfigGenerator(tmp_path, run=run)


def test_generate_publishes_a_discovered_workspace(
    azure_generator: WorkspaceConfigGenerator, generate_request: GenerateRequest
) -> None:
    """Discover both clusters from Azure and publish a complete workspace.

    :param azure_generator: Generator backed by a scripted Azure CLI.
    :param generate_request: Valid generation request.
    """
    generated = azure_generator.generate(generate_request)

    assert set(generated.hosts) == {"SH7_DB", "SH7_SCS", "SH7_ERS"}
    assert (generated.workspace_path / "sap-parameters.yaml").is_file()
    assert (generated.workspace_path / "hosts.yaml").is_file()
    assert "SAP SID: SH7" in generated.preview()


def test_generate_dry_run_leaves_the_workspace_absent(
    azure_generator: WorkspaceConfigGenerator, generate_request: GenerateRequest
) -> None:
    """Discover the topology without writing anything during a dry run.

    :param azure_generator: Generator backed by a scripted Azure CLI.
    :param generate_request: Valid generation request.
    """
    generated = azure_generator.generate(replace(generate_request, dry_run=True))

    assert not generated.workspace_path.exists()


def test_generate_rejects_an_already_configured_workspace(
    azure_generator: WorkspaceConfigGenerator, generate_request: GenerateRequest
) -> None:
    """Refuse to touch a workspace that already contains user configuration.

    :param azure_generator: Generator backed by a scripted Azure CLI.
    :param generate_request: Valid generation request.
    """
    workspace = generate_request.workspace_root / generate_request.workspace_id
    workspace.mkdir(parents=True)
    (workspace / "sap-parameters.yaml").write_text("user-owned", encoding="utf-8")

    with pytest.raises(WorkspaceConfigError, match="already contains configuration"):
        azure_generator.generate(generate_request)


def test_request_rejects_a_workspace_identifier_that_escapes_the_root(
    generate_request: GenerateRequest,
) -> None:
    """Reject a traversing workspace identifier before any discovery starts.

    :param generate_request: Valid generation request.
    """
    with pytest.raises(WorkspaceValidationError):
        replace(generate_request, workspace_id="../escaped")


def test_generate_rejects_a_guest_identity_that_differs_from_azure(
    tmp_path: Path,
    generate_request: GenerateRequest,
    discovered_facts: dict[str, dict[str, object]],
) -> None:
    """Reject a seed VM whose guest IMDS identity is not the nominated resource.

    :param tmp_path: Pytest temporary directory.
    :param generate_request: Valid generation request.
    :param discovered_facts: Collector facts keyed by guest host name.
    """
    identity = discovered_facts["scs01"]["identity"]
    identity["resource_id"] = RESOURCE_ID.format("impostor")  # type: ignore[index]

    def run(command: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        """Return inventory, VM metadata, and collector facts for the seed VM.

        :param command: Executed command line.
        :param _kwargs: Ignored subprocess options.
        :returns: Successful process result.
        """
        if command[1:3] == ["vm", "list"]:
            stdout = json.dumps(_inventory(sorted(discovered_facts)))
        elif command[1:3] == ["vm", "show"]:
            name = command[command.index("--name") + 1]
            stdout = json.dumps(
                {"id": RESOURCE_ID.format(name), "osProfile": {"adminUsername": "azureadm"}}
            )
        else:
            name = command[command.index("--name") + 1]
            stdout = _facts_envelope(discovered_facts[name])
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    with pytest.raises(WorkspaceConfigError, match="does not match Azure VM identity"):
        WorkspaceConfigGenerator(tmp_path, run=run).generate(generate_request)


def test_az_reports_a_failed_azure_cli_invocation(tmp_path: Path) -> None:
    """Surface Azure CLI failure detail instead of continuing with empty output.

    :param tmp_path: Pytest temporary directory.
    """

    def run(command: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        """Return a failed Azure CLI result.

        :param command: Executed command line.
        :param _kwargs: Ignored subprocess options.
        :returns: Failed process result.
        """
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="not logged in")

    with pytest.raises(WorkspaceConfigError, match="not logged in"):
        WorkspaceConfigGenerator(tmp_path, run=run)._list_vms("rg")


def test_az_reports_an_unavailable_azure_cli(tmp_path: Path) -> None:
    """Report a missing Azure CLI rather than raising an unhandled OS error.

    :param tmp_path: Pytest temporary directory.
    """

    def run(_command: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        """Simulate an Azure CLI that is not installed.

        :raises OSError: Always, to simulate a missing executable.
        """
        raise OSError("az not found")

    with pytest.raises(WorkspaceConfigError, match="Azure CLI invocation failed"):
        WorkspaceConfigGenerator(tmp_path, run=run)._list_vms("rg")


def test_list_vms_rejects_inventory_that_is_not_json(tmp_path: Path) -> None:
    """Reject an Azure VM inventory response that cannot be parsed.

    :param tmp_path: Pytest temporary directory.
    """

    def run(command: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        """Return unparsable inventory output.

        :param command: Executed command line.
        :param _kwargs: Ignored subprocess options.
        :returns: Successful process result with invalid JSON.
        """
        return subprocess.CompletedProcess(command, 0, stdout="not-json", stderr="")

    with pytest.raises(WorkspaceConfigError, match="not valid JSON"):
        WorkspaceConfigGenerator(tmp_path, run=run)._list_vms("rg")


def test_find_vm_candidate_rejects_an_ambiguous_computer_name(
    generator: WorkspaceConfigGenerator,
) -> None:
    """Reject cluster members that resolve to more than one Azure VM.

    :param generator: Isolated generator.
    """
    inventory = _inventory(["scs01"]) + _inventory(["scs01"])

    with pytest.raises(WorkspaceConfigError, match="found 2"):
        generator._find_vm_candidate(inventory, "scs01")


def test_find_vm_candidate_rejects_an_unknown_computer_name(
    generator: WorkspaceConfigGenerator,
) -> None:
    """Reject a cluster member that has no Azure VM in the resource group.

    :param generator: Isolated generator.
    """
    with pytest.raises(WorkspaceConfigError, match="found 0"):
        generator._find_vm_candidate(_inventory(["scs01"]), "scs99")


def test_parse_run_command_reports_a_failed_collector_run(
    generator: WorkspaceConfigGenerator,
) -> None:
    """Surface Run Command failures instead of treating them as empty facts.

    :param generator: Isolated generator.
    """
    envelope = {"value": [{"code": "ComponentStatus/StdErr/failed", "message": "denied"}]}

    with pytest.raises(WorkspaceConfigError, match="Run Command failed"):
        generator._parse_run_command(json.dumps(envelope), "scs01")


def test_parse_run_command_rejects_an_unsupported_collector_schema(
    generator: WorkspaceConfigGenerator,
) -> None:
    """Reject collector output produced by an unrecognized schema version.

    :param generator: Isolated generator.
    """
    envelope = {
        "value": [
            {
                "code": "ComponentStatus/StdOut/succeeded",
                "message": json.dumps({"schema_version": 99}),
            }
        ]
    }

    with pytest.raises(WorkspaceConfigError, match="unsupported schema"):
        generator._parse_run_command(json.dumps(envelope), "scs01")


def test_recover_interrupted_publication_removes_matching_partial_files(
    generator: WorkspaceConfigGenerator, tmp_path: Path
) -> None:
    """Remove generator-owned partial files whose digests match a stale marker.

    :param generator: Isolated generator.
    :param tmp_path: Pytest temporary directory.
    """
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    partial = workspace / "hosts.yaml"
    partial.write_text("partial", encoding="utf-8")
    (workspace / ".workspace-config-generation.json").write_text(
        json.dumps({"files": {"hosts.yaml": generator._sha256(partial)}}), encoding="utf-8"
    )

    generator._recover_interrupted_publication(workspace)

    assert not partial.exists()
    assert not (workspace / ".workspace-config-generation.json").exists()


def test_recover_interrupted_publication_keeps_unrecognized_files(
    generator: WorkspaceConfigGenerator, tmp_path: Path
) -> None:
    """Refuse automatic recovery when a partial file no longer matches its digest.

    :param generator: Isolated generator.
    :param tmp_path: Pytest temporary directory.
    """
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "hosts.yaml").write_text("edited-by-user", encoding="utf-8")
    (workspace / ".workspace-config-generation.json").write_text(
        json.dumps({"files": {"hosts.yaml": "0" * 64}}), encoding="utf-8"
    )

    with pytest.raises(WorkspaceConfigError, match="repair manually"):
        generator._recover_interrupted_publication(workspace)


def test_recover_interrupted_publication_rejects_unsafe_marker_entries(
    generator: WorkspaceConfigGenerator, tmp_path: Path
) -> None:
    """Reject a transaction marker that names files the generator does not own.

    :param generator: Isolated generator.
    :param tmp_path: Pytest temporary directory.
    """
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".workspace-config-generation.json").write_text(
        json.dumps({"files": {"../escape.yaml": "0" * 64}}), encoding="utf-8"
    )

    with pytest.raises(WorkspaceConfigError, match="unsafe file name"):
        generator._recover_interrupted_publication(workspace)


def test_recover_interrupted_publication_rejects_an_unreadable_marker(
    generator: WorkspaceConfigGenerator, tmp_path: Path
) -> None:
    """Reject a transaction marker that cannot be parsed as generator state.

    :param generator: Isolated generator.
    :param tmp_path: Pytest temporary directory.
    """
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".workspace-config-generation.json").write_text("not-json", encoding="utf-8")

    with pytest.raises(WorkspaceConfigError, match="unreadable generation transaction marker"):
        generator._recover_interrupted_publication(workspace)


def test_validate_staged_reports_validator_output(
    tmp_path: Path,
    generate_request: GenerateRequest,
    clusters: dict[str, list[dict[str, object]]],
) -> None:
    """Report validator diagnostics instead of publishing an invalid workspace.

    :param tmp_path: Pytest temporary directory.
    :param generate_request: Valid generation request.
    :param clusters: Complete normalized cluster facts.
    """

    def run(command: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        """Return Azure Files metadata but a failing validator result.

        :param command: Executed command line.
        :param _kwargs: Ignored subprocess options.
        :returns: Process result for the recognized command.
        """
        if command[0] == "az":
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=json.dumps(
                    {"primaryEndpoints": {"file": "https://sapfiles.file.core.windows.net/"}}
                ),
                stderr="",
            )
        return subprocess.CompletedProcess(command, 1, stdout="missing required key", stderr="")

    failing = WorkspaceConfigGenerator(tmp_path, run=run)
    workspace = generate_request.workspace_root / generate_request.workspace_id
    generated = failing._render(workspace, clusters, generate_request)
    workspace.parent.mkdir(parents=True, exist_ok=True)

    with pytest.raises(WorkspaceConfigError, match="failed validation"):
        failing._validate_staged(workspace, generated, generate_request)


def test_stage_credential_rejects_a_missing_source(
    generator: WorkspaceConfigGenerator, tmp_path: Path
) -> None:
    """Reject a credential selection that does not point at a readable file.

    :param generator: Isolated generator.
    :param tmp_path: Pytest temporary directory.
    """
    with pytest.raises(WorkspaceConfigError, match="Credential source does not exist"):
        generator._stage_credential(tmp_path, CredentialMaterial(tmp_path / "absent", "ssh_key"))


def test_nfs_provider_accepts_a_sovereign_cloud_files_endpoint(
    tmp_path: Path,
    clusters: dict[str, list[dict[str, object]]],
) -> None:
    """Accept Azure Files accounts whose endpoint suffix is not the public cloud.

    :param tmp_path: Pytest temporary directory.
    :param clusters: Normalized cluster facts.
    """

    def run(command: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        """Return sovereign-cloud Azure Files metadata.

        :param command: Azure CLI argument vector.
        :returns: Successful Azure CLI process result.
        """
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(
                {"primaryEndpoints": {"file": "https://sapfiles.file.core.usgovcloudapi.net/"}}
            ),
            stderr="",
        )

    generator = WorkspaceConfigGenerator(tmp_path, run=run)

    assert generator._nfs_provider(clusters["scs"] + clusters["db"], "rg") == "AFS"


def test_nfs_provider_rejects_an_account_that_does_not_match_the_mount(
    tmp_path: Path,
    clusters: dict[str, list[dict[str, object]]],
) -> None:
    """Refuse metadata whose account does not match the discovered mount path.

    :param tmp_path: Pytest temporary directory.
    :param clusters: Normalized cluster facts.
    """

    def run(command: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        """Return metadata for an unrelated storage account.

        :param command: Azure CLI argument vector.
        :returns: Successful Azure CLI process result.
        """
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(
                {"primaryEndpoints": {"file": "https://other.file.core.windows.net/"}}
            ),
            stderr="",
        )

    generator = WorkspaceConfigGenerator(tmp_path, run=run)

    with pytest.raises(WorkspaceConfigError, match="expected Azure Files account"):
        generator._nfs_provider(clusters["scs"], "rg")


def test_parse_run_command_surfaces_guest_standard_error(
    generator: WorkspaceConfigGenerator,
) -> None:
    """Report guest diagnostics when the collector emitted no fact document.

    :param generator: Isolated generator.
    """
    message = "Enable succeeded: \n[stdout]\n\n[stderr]\nTypeError: unexpected keyword\n"
    envelope = json.dumps({"value": [{"code": "ProvisioningState/succeeded", "message": message}]})

    with pytest.raises(WorkspaceConfigError, match="TypeError: unexpected keyword"):
        generator._parse_run_command(envelope, "scs01")


def test_render_uses_the_virtual_host_name_rather_than_the_cluster_address(
    generator: WorkspaceConfigGenerator,
    generate_request: GenerateRequest,
    clusters: dict[str, list[dict[str, object]]],
) -> None:
    """Publish the SAP virtual host name that the framework resolves for SCS and ERS.

    :param generator: Isolated generator.
    :param generate_request: Valid generation request.
    :param clusters: Normalized cluster facts.
    """
    generated = generator._render(
        generate_request.workspace_root / generate_request.workspace_id,
        clusters,
        generate_request,
    )

    scs = generated.hosts["SH7_SCS"]["hosts"]
    ers = generated.hosts["SH7_ERS"]["hosts"]
    assert [host["virtual_host"] for host in scs.values()] == ["sh7ascs"]
    assert [host["virtual_host"] for host in ers.values()] == ["sh7ers"]
