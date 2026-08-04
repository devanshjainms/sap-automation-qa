# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for the workspace configuration command adapter."""

import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence, cast

import pytest

from src.core.generate_workspace_config import main
from src.core.workspace_config import (
    GeneratedWorkspace,
    GenerateRequest,
    WorkspaceConfigGenerator,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPOSITORY_ROOT / "src" / "core" / "generate_workspace_config.py"
BASE_ARGUMENTS = [
    "--workspace-id",
    "DEV-EUS2-SAP01-SH7",
    "--resource-group",
    "rg",
    "--scs-vm",
    "scs01",
    "--db-vm",
    "db01",
]


class _RecordingGenerator:
    """Generator double that records requests instead of contacting Azure."""

    def __init__(self, _repository_root: Path) -> None:
        """Record the requests issued by the adapter.

        :param _repository_root: Unused repository root supplied by the adapter.
        """
        self.requests: list[GenerateRequest] = []
        self.published: list[tuple[GeneratedWorkspace, GenerateRequest]] = []
        self.previewed: list[GeneratedWorkspace] = []

    def generate(self, request: GenerateRequest) -> GeneratedWorkspace:
        """Return a fixed workspace for the recorded request.

        :param request: Request issued by the adapter.
        :returns: A generated workspace with a deterministic preview.
        """
        self.requests.append(request)
        generated = GeneratedWorkspace(
            workspace_path=request.workspace_root / request.workspace_id,
            sap_parameters={
                "sap_sid": "SH7",
                "db_sid": "HD7",
                "scs_cluster_type": "AFA",
                "database_cluster_type": "AFA",
                "database_scale_out": False,
            },
            hosts={},
            request=request,
        )
        self.previewed.append(generated)
        return generated

    def publish(
        self, generated: GeneratedWorkspace, request: GenerateRequest
    ) -> GeneratedWorkspace:
        """Record a publication of an already-discovered workspace.

        :param generated: Documents produced by the earlier discovery pass.
        :param request: Request that produced ``generated``.
        :returns: The generated workspace unchanged.
        """
        self.published.append((generated, request))
        return generated


def _run(
    arguments: Sequence[str], responses: Sequence[str] | None = None
) -> tuple[int, _RecordingGenerator]:
    """Run the adapter with a recording generator and scripted operator input.

    :param arguments: Command-line arguments excluding the executable name.
    :param responses: Ordered replies returned to interactive prompts.
    :returns: The adapter exit status and the generator double it used.
    """
    replies = list(responses or [])
    generator = _RecordingGenerator(REPOSITORY_ROOT)

    def _input(_prompt: str) -> str:
        """Return the next scripted operator reply.

        :param _prompt: Ignored prompt text.
        :returns: The next scripted reply.
        """
        return replies.pop(0)

    status = main(
        list(arguments),
        input_func=_input,
        generator_factory=lambda _root: cast(WorkspaceConfigGenerator, generator),
    )
    return status, generator


def test_key_vault_arguments_produce_a_request_without_local_credentials() -> None:
    """Accept an explicit Key Vault pair as the noninteractive credential source."""
    status, generator = _run(
        BASE_ARGUMENTS
        + ["--key-vault-id", "kv", "--secret-id", "secret", "--auth-type", "VMPASSWORD", "--yes"]
    )

    assert status == 0
    request = generator.requests[0]
    assert request.credential is None
    assert (request.key_vault_id, request.secret_id) == ("kv", "secret")
    assert request.authentication_type == "VMPASSWORD"
    assert request.dry_run is True
    assert len(generator.requests) == 1
    assert generator.published[0][1].dry_run is False


def test_key_vault_without_an_auth_type_is_rejected_noninteractively() -> None:
    """Refuse a Key Vault workspace whose credential kind cannot be inferred."""
    status, generator = _run(
        BASE_ARGUMENTS + ["--key-vault-id", "kv", "--secret-id", "secret", "--yes"]
    )

    assert status == 1
    assert generator.requests == []


def test_dry_run_previews_without_requesting_confirmation() -> None:
    """Skip the confirmation prompt when the operator only asks for a preview."""
    status, generator = _run(BASE_ARGUMENTS + ["--ssh-key", "key", "--dry-run"])

    assert status == 0
    assert [request.dry_run for request in generator.requests] == [True]


def test_declined_confirmation_leaves_the_workspace_untouched() -> None:
    """Preview first and abandon generation when the operator declines."""
    status, generator = _run(BASE_ARGUMENTS + ["--ssh-key", "key"], responses=["n"])

    assert status == 0
    assert [request.dry_run for request in generator.requests] == [True]


def test_accepted_confirmation_generates_after_the_preview() -> None:
    """Publish the reviewed discovery result rather than rediscovering it."""
    status, generator = _run(BASE_ARGUMENTS + ["--ssh-key", "key"], responses=["y"])

    assert status == 0
    assert [request.dry_run for request in generator.requests] == [True]
    published_workspace, published_request = generator.published[0]
    assert published_workspace is generator.previewed[0]
    assert published_request.dry_run is False


def test_interactive_prompts_collect_every_missing_value() -> None:
    """Prompt for the resource group, both seed VMs, and the credential source."""
    status, generator = _run(
        ["--workspace-id", "DEV-EUS2-SAP01-SH7", "--dry-run"],
        responses=["rg", "scs01", "db01", "v", "kv", "secret", "p"],
    )

    assert status == 0
    request = generator.requests[0]
    assert (request.resource_group, request.scs_seed_vm, request.db_seed_vm) == (
        "rg",
        "scs01",
        "db01",
    )
    assert (request.key_vault_id, request.secret_id) == ("kv", "secret")
    assert request.authentication_type == "VMPASSWORD"


@pytest.mark.parametrize(
    "extra_arguments",
    [
        ["--ssh-key", "key", "--key-vault-id", "kv"],
        ["--ssh-key", "key", "--password-file", "password"],
    ],
    ids=["local-and-key-vault", "two-local-artifacts"],
)
def test_conflicting_credential_selections_are_rejected(extra_arguments: list[str]) -> None:
    """Reject ambiguous credential selections before any Azure discovery.

    :param extra_arguments: Conflicting credential options under test.
    """
    status, generator = _run(BASE_ARGUMENTS + extra_arguments + ["--yes"])

    assert status == 1
    assert not generator.requests


def test_unknown_interactive_credential_choice_is_rejected() -> None:
    """Reject a credential source that is not a key, password file, or key vault."""
    status, generator = _run(BASE_ARGUMENTS + ["--dry-run"], responses=["x"])

    assert status == 1
    assert not generator.requests


def test_noninteractive_mode_requires_a_credential_source() -> None:
    """Fail fast instead of prompting when generation is approved noninteractively."""
    status, generator = _run(BASE_ARGUMENTS + ["--yes"])

    assert status == 1
    assert not generator.requests


def test_noninteractive_mode_requires_every_seed_value(capsys: Any) -> None:
    """Report the first missing seed value rather than prompting for it."""
    status, generator = _run(["--workspace-id", "DEV-EUS2-SAP01-SH7", "--ssh-key", "key", "--yes"])

    assert status == 1
    assert not generator.requests
    assert "Azure resource group is required" in capsys.readouterr().err


def test_generator_help_is_available_as_a_standalone_script() -> None:
    """Expose the supported command adapter without activating the test runner."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 0
    assert "--workspace-id" in result.stdout
    assert "--yes" in result.stdout


def test_generator_noninteractive_mode_requires_explicit_credential_source() -> None:
    """Fail before Azure discovery when a noninteractive credential is omitted."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT), *BASE_ARGUMENTS, "--yes"],
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 1
    assert "Choose --ssh-key" in result.stderr


def test_auth_type_rejects_a_mismatched_local_credential_artifact() -> None:
    """Reject an SSHKEY run that nominates a password file as its credential."""
    status, generator = _run(
        BASE_ARGUMENTS + ["--auth-type", "SSHKEY", "--password-file", "pw", "--yes"]
    )

    assert status == 1
    assert generator.requests == []


def test_auth_type_accepts_the_matching_local_credential_artifact() -> None:
    """Accept a VMPASSWORD run that nominates a password file as its credential."""
    status, generator = _run(
        BASE_ARGUMENTS + ["--auth-type", "VMPASSWORD", "--password-file", "pw", "--yes"]
    )

    assert status == 0
    credential = generator.requests[0].credential
    assert credential is not None
    assert credential.destination_name == "password"


def test_auth_type_prompt_skips_the_artifact_question_for_a_password_run() -> None:
    """Route an interactive VMPASSWORD run straight to the password artifact."""
    status, generator = _run(
        BASE_ARGUMENTS + ["--auth-type", "VMPASSWORD", "--dry-run"],
        responses=["f", "pw"],
    )

    assert status == 0
    credential = generator.requests[0].credential
    assert credential is not None
    assert credential.destination_name == "password"


def test_auth_type_prompt_still_allows_key_vault_selection() -> None:
    """Allow an SSHKEY run to choose Key Vault instead of a local artifact."""
    status, generator = _run(
        BASE_ARGUMENTS + ["--auth-type", "SSHKEY", "--dry-run"],
        responses=["v", "kv", "secret"],
    )

    assert status == 0
    request = generator.requests[0]
    assert request.credential is None
    assert (request.key_vault_id, request.secret_id) == ("kv", "secret")


def test_auth_type_prompt_rejects_an_unknown_credential_source() -> None:
    """Reject an unusable credential-source reply when the auth type is known."""
    status, generator = _run(
        BASE_ARGUMENTS + ["--auth-type", "SSHKEY", "--dry-run"], responses=["x"]
    )

    assert status == 1
    assert generator.requests == []
