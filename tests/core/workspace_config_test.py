# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for safe initial workspace configuration generation."""

# pylint: disable=redefined-outer-name

import json
import subprocess
from pathlib import Path

import pytest

from src.core.exceptions import WorkspaceConfigError
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
    instances: list[dict[str, str]] | None = None,
    hana: dict[str, object] | None = None,
) -> dict[str, object]:
    """Create a normalized collector fact for isolated service tests.

    :param hostname: Guest host name.
    :param resource_id: Exact IMDS resource identifier.
    :param address: Guest private address.
    :param fencing_agents: Normalized fencing resource-agent types.
    :param instances: Semantic SCS/ERS resource facts.
    :param hana: Normalized HANA facts.
    :returns: Collector fact document.
    """
    return {
        "schema_version": 1,
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
            "sap_instances": instances or [],
        },
        "hana": hana,
        "storage": {"nfs_sources": ["sapfiles.file.core.windows.net:/sapmnt"]},
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
        {"sid": "SH7", "role": "ASCS", "instance_number": "01", "vip": "sh7ascs"},
        {"sid": "SH7", "role": "ERS", "instance_number": "02", "vip": "sh7ers"},
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


def test_render_rejects_sbd_without_proven_backing_type(
    generator: WorkspaceConfigGenerator,
    generate_request: GenerateRequest,
    clusters: dict[str, list[dict[str, object]]],
) -> None:
    """Refuse SBD evidence rather than guessing ASD or iSCSI classification.

    :param generator: Isolated generator.
    :param generate_request: Valid generation request.
    :param clusters: Cluster facts modified to contain SBD evidence.
    """
    clusters["scs"][0]["cluster"]["fencing_agents"] = ["external/sbd"]  # type: ignore[index]

    with pytest.raises(WorkspaceConfigError, match="SBD fencing"):
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
    envelope = {"value": [{"code": "ComponentStatus/StdOut/succeeded", "message": "x" * 4097}]}

    with pytest.raises(WorkspaceConfigError, match="exceeds 4096"):
        generator._parse_run_command(json.dumps(envelope), "scs01")


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
