# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for workspace staging, publication, recovery, and Azure plumbing."""

# pylint: disable=redefined-outer-name,unused-import

import json
import subprocess
import time
from dataclasses import replace
from pathlib import Path

import pytest

from src.core.exceptions import WorkspaceConfigError, WorkspaceValidationError
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
            return result(json.dumps(inventory(sorted(discovered_facts))))
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
            return result(facts_envelope(discovered_facts[name]))
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


def test_publish_writes_the_reviewed_documents(
    azure_generator: WorkspaceConfigGenerator, generate_request: GenerateRequest
) -> None:
    """Publish the exact documents a dry run produced, without rediscovering.

    :param azure_generator: Generator backed by a scripted Azure CLI.
    :param generate_request: Valid generation request.
    """
    previewed = azure_generator.generate(replace(generate_request, dry_run=True))
    assert not previewed.workspace_path.exists()

    published = azure_generator.publish(previewed, generate_request)

    assert published is previewed
    assert (previewed.workspace_path / "sap-parameters.yaml").is_file()
    assert (previewed.workspace_path / "hosts.yaml").is_file()


def test_publish_rejects_a_mismatched_workspace(
    azure_generator: WorkspaceConfigGenerator, generate_request: GenerateRequest
) -> None:
    """Refuse to publish documents discovered for a different workspace.

    :param azure_generator: Generator backed by a scripted Azure CLI.
    :param generate_request: Valid generation request.
    """
    previewed = azure_generator.generate(replace(generate_request, dry_run=True))
    other = replace(generate_request, workspace_id="DEV-EUS2-SAP01-XX9")

    with pytest.raises(WorkspaceConfigError, match="does not match the requested workspace"):
        azure_generator.publish(previewed, other)


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


def test_request_derives_the_authentication_type_from_the_credential(
    generate_request: GenerateRequest,
) -> None:
    """Record the authentication type implied by the chosen local artifact.

    :param generate_request: Valid generation request.
    """
    key_request = replace(
        generate_request,
        credential=CredentialMaterial(Path("id_rsa"), "ssh_key"),
        authentication_type="",
    )
    password_request = replace(
        generate_request,
        credential=CredentialMaterial(Path("pw"), "password"),
        authentication_type="",
    )

    assert key_request.authentication_type == "SSHKEY"
    assert password_request.authentication_type == "VMPASSWORD"


def test_request_rejects_an_authentication_type_conflicting_with_the_artifact(
    generate_request: GenerateRequest,
) -> None:
    """Refuse a declared type that disagrees with the credential artifact.

    :param generate_request: Valid generation request.
    """
    with pytest.raises(WorkspaceConfigError, match="conflicts with the"):
        replace(
            generate_request,
            credential=CredentialMaterial(Path("id_rsa"), "ssh_key"),
            authentication_type="VMPASSWORD",
        )


def test_request_requires_an_authentication_type_for_key_vault(
    generate_request: GenerateRequest,
) -> None:
    """Refuse a Key Vault request whose credential kind cannot be inferred.

    :param generate_request: Valid generation request.
    """
    with pytest.raises(WorkspaceConfigError, match="authentication_type is required"):
        replace(
            generate_request,
            credential=None,
            key_vault_id="kv",
            secret_id="secret",
            authentication_type="",
        )


def test_request_rejects_an_unknown_authentication_type(
    generate_request: GenerateRequest,
) -> None:
    """Refuse an authentication type the runtime cannot serve.

    :param generate_request: Valid generation request.
    """
    with pytest.raises(WorkspaceConfigError, match="authentication_type must be one of"):
        replace(
            generate_request,
            credential=None,
            key_vault_id="kv",
            secret_id="secret",
            authentication_type="KERBEROS",
        )


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
            stdout = json.dumps(inventory(sorted(discovered_facts)))
        elif command[1:3] == ["vm", "show"]:
            name = command[command.index("--name") + 1]
            stdout = json.dumps(
                {"id": RESOURCE_ID.format(name), "osProfile": {"adminUsername": "azureadm"}}
            )
        else:
            name = command[command.index("--name") + 1]
            stdout = facts_envelope(discovered_facts[name])
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
    duplicates = inventory(["scs01"]) + inventory(["scs01"])

    with pytest.raises(WorkspaceConfigError, match="found 2"):
        generator._find_vm_candidate(duplicates, "scs01")


def test_find_vm_candidate_rejects_an_unknown_computer_name(
    generator: WorkspaceConfigGenerator,
) -> None:
    """Reject a cluster member that has no Azure VM in the resource group.

    :param generator: Isolated generator.
    """
    with pytest.raises(WorkspaceConfigError, match="found 0"):
        generator._find_vm_candidate(inventory(["scs01"]), "scs99")


def test_collect_cluster_facts_rejects_a_split_membership_view(
    generator: WorkspaceConfigGenerator, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reject a peer whose reported membership disagrees with the seed node.

    :param generator: Isolated generator.
    :param monkeypatch: Pytest attribute patcher.
    """
    seed = {
        "identity": {"resource_id": RESOURCE_ID.format("scs01"), "hostname": "scs01"},
        "cluster": {"members": ["scs01", "scs02"]},
    }
    peer = {
        "identity": {"resource_id": RESOURCE_ID.format("scs02"), "hostname": "scs02"},
        "cluster": {"members": ["scs02", "scs03"]},
    }
    monkeypatch.setattr(WorkspaceConfigGenerator, "_collect_vm", lambda self, group, name: peer)

    with pytest.raises(WorkspaceConfigError, match="different scs membership"):
        generator._collect_cluster_facts("rg", inventory(["scs01", "scs02"]), {"scs": seed})


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
        json.dumps(
            {
                "files": {
                    "hosts.yaml": generator._sha256(partial),
                    "sap-parameters.yaml": "0" * 64,
                }
            }
        ),
        encoding="utf-8",
    )

    generator._recover_interrupted_publication(workspace)

    assert not partial.exists()
    assert not (workspace / ".workspace-config-generation.json").exists()


def test_recover_interrupted_publication_rejects_an_active_marker(
    generator: WorkspaceConfigGenerator, tmp_path: Path
) -> None:
    """Refuse to roll back a marker that another run appears to still own.

    :param generator: Isolated generator.
    :param tmp_path: Pytest temporary directory.
    """
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    partial = workspace / "hosts.yaml"
    partial.write_text("partial", encoding="utf-8")
    (workspace / ".workspace-config-generation.json").write_text(
        json.dumps(
            {
                "files": {
                    "hosts.yaml": generator._sha256(partial),
                    "sap-parameters.yaml": "0" * 64,
                },
                "started": time.time(),
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(WorkspaceConfigError, match="already in progress|in progress"):
        generator._recover_interrupted_publication(workspace)

    assert partial.exists()


def test_recover_interrupted_publication_keeps_a_completed_workspace(
    generator: WorkspaceConfigGenerator, tmp_path: Path
) -> None:
    """Drop the marker without deleting files when every published file is intact.

    :param generator: Isolated generator.
    :param tmp_path: Pytest temporary directory.
    """
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    published = {"hosts.yaml": "hosts", "sap-parameters.yaml": "parameters"}
    for name, content in published.items():
        (workspace / name).write_text(content, encoding="utf-8")
    (workspace / ".workspace-config-generation.json").write_text(
        json.dumps({"files": {name: generator._sha256(workspace / name) for name in published}}),
        encoding="utf-8",
    )

    generator._recover_interrupted_publication(workspace)

    assert all((workspace / name).exists() for name in published)
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
