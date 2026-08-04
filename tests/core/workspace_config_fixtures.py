# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Shared fixtures for the workspace configuration generator test modules."""

# pylint: disable=redefined-outer-name

import json
import subprocess
from pathlib import Path

import pytest

from src.core.workspace_config import (
    CredentialMaterial,
    GenerateRequest,
    WorkspaceConfigGenerator,
)

RESOURCE_ID = "/subscriptions/a/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/{0}"


def make_fact(
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

    return WorkspaceConfigGenerator(Path(__file__).resolve().parents[2], run=run)


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
            make_fact(
                "scs01",
                "/subscriptions/a/resourceGroups/rg/providers/"
                "Microsoft.Compute/virtualMachines/scs01",
                "10.0.0.4",
                instances=instances,
            ),
            make_fact(
                "scs02",
                "/subscriptions/a/resourceGroups/rg/providers/"
                "Microsoft.Compute/virtualMachines/scs02",
                "10.0.0.5",
                instances=instances,
            ),
        ],
        "db": [
            make_fact(
                "db01",
                "/subscriptions/a/resourceGroups/rg/providers/"
                "Microsoft.Compute/virtualMachines/db01",
                "10.0.1.4",
                hana={
                    "sid": "HDB",
                    "instance_number": "00",
                    "installed": True,
                    "sr_online": True,
                    "virtual_host": "vdb01",
                    "hosts": ["db01"],
                },
            ),
            make_fact(
                "db02",
                "/subscriptions/a/resourceGroups/rg/providers/"
                "Microsoft.Compute/virtualMachines/db02",
                "10.0.1.5",
                hana={
                    "sid": "HDB",
                    "instance_number": "00",
                    "installed": True,
                    "sr_online": True,
                    "virtual_host": "vdb02",
                    "hosts": ["db01"],
                },
            ),
        ],
    }


def run_command_envelope(payload: str) -> str:
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


def facts_envelope(facts: dict[str, object]) -> str:
    """Wrap collector facts in the exact Azure Run Command response envelope.

    :param facts: Normalized collector facts.
    :returns: Serialized Run Command response.
    """
    return run_command_envelope(json.dumps(facts, separators=(",", ":")))


def inventory(names: list[str]) -> list[dict[str, object]]:
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
