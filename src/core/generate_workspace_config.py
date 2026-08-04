#!/usr/bin/env python3

# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Generate an initial SAP HA workspace from Azure VM Run Command facts."""

from __future__ import annotations
import argparse
import sys
from dataclasses import replace
from pathlib import Path
from typing import Callable, Sequence

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

# pylint: disable=wrong-import-position
from src.core.exceptions import WorkspaceConfigError
from src.core.workspace_config import (
    CredentialMaterial,
    GenerateRequest,
    WorkspaceConfigGenerator,
)


def _prompt(
    value: str | None, label: str, input_func: Callable[[str], str], allow_prompt: bool
) -> str:
    """Return an explicit value or prompt the interactive operator for one.

    :param value: Existing command-line value, if any.
    :param label: Prompt label for a required value.
    :param input_func: Input function used for interactive prompts.
    :param allow_prompt: Whether this invocation may request missing values.
    :returns: A non-empty operator-provided value.
    :raises WorkspaceConfigError: If a required value is unavailable.
    """
    if value:
        return value
    if not allow_prompt:
        raise WorkspaceConfigError(f"{label} is required outside an interactive terminal")
    try:
        prompted = input_func(f"{label}: ").strip()
    except EOFError as exc:
        raise WorkspaceConfigError(f"{label} is required outside an interactive terminal") from exc
    if not prompted:
        raise WorkspaceConfigError(f"{label} is required")
    return prompted


_AUTH_DESTINATIONS = {"SSHKEY": "ssh_key", "VMPASSWORD": "password"}


def _prompt_known_auth(
    destination: str,
    auth_type: str,
    input_func: Callable[[str], str],
    allow_prompt: bool,
) -> tuple[CredentialMaterial | None, str, str]:
    """Prompt for a credential source when the authentication type is already known.

    :param destination: Required workspace credential artifact name.
    :param auth_type: Authentication type driving the artifact selection.
    :param input_func: Input function used for interactive prompts.
    :param allow_prompt: Whether this invocation may request missing values.
    :returns: Local credential material or a Key Vault reference pair.
    :raises WorkspaceConfigError: If the operator selection is unusable.
    """
    label = "SSH key path" if destination == "ssh_key" else "Password file path"
    try:
        choice = (
            input_func(f"{auth_type} credential source [f]ile or key [v]ault: ").strip().lower()
        )
    except EOFError as exc:
        raise WorkspaceConfigError(
            "Choose --ssh-key, --password-file, or --key-vault-id with --secret-id"
        ) from exc
    if choice == "f":
        return (
            CredentialMaterial(Path(_prompt(None, label, input_func, allow_prompt)), destination),
            "",
            "",
        )
    if choice == "v":
        return (
            None,
            _prompt(None, "Key Vault resource ID", input_func, allow_prompt),
            _prompt(None, "Key Vault secret ID", input_func, allow_prompt),
        )
    raise WorkspaceConfigError("Credential source must be file or key vault")


def _prompt_any_auth(
    input_func: Callable[[str], str], allow_prompt: bool
) -> tuple[CredentialMaterial | None, str, str]:
    """Prompt for a credential source when no authentication type was supplied.

    :param input_func: Input function used for interactive prompts.
    :param allow_prompt: Whether this invocation may request missing values.
    :returns: Local credential material or a Key Vault reference pair.
    :raises WorkspaceConfigError: If the operator selection is unusable.
    """
    try:
        choice = (
            input_func("Credential source [k]ey, [p]assword file, or key [v]ault: ").strip().lower()
        )
    except EOFError as exc:
        raise WorkspaceConfigError(
            "Choose --ssh-key, --password-file, or --key-vault-id with --secret-id"
        ) from exc
    if choice == "k":
        return (
            CredentialMaterial(
                Path(_prompt(None, "SSH key path", input_func, allow_prompt)), "ssh_key"
            ),
            "",
            "",
        )
    if choice == "p":
        return (
            CredentialMaterial(
                Path(_prompt(None, "Password file path", input_func, allow_prompt)), "password"
            ),
            "",
            "",
        )
    if choice == "v":
        return (
            None,
            _prompt(None, "Key Vault resource ID", input_func, allow_prompt),
            _prompt(None, "Key Vault secret ID", input_func, allow_prompt),
        )
    raise WorkspaceConfigError("Credential source must be key, password file, or key vault")


def _prompt_authentication_type(input_func: Callable[[str], str], allow_prompt: bool) -> str:
    """Ask which authentication type a Key Vault workspace must serve.

    The secret alone does not reveal whether it holds an SSH key or a password,
    so the runtime cannot infer this from the published workspace.

    :param input_func: Input function used for interactive prompts.
    :param allow_prompt: Whether this invocation may request missing values.
    :returns: The selected authentication type.
    :raises WorkspaceConfigError: If no usable selection is available.
    """
    if not allow_prompt:
        raise WorkspaceConfigError("--auth-type is required with --key-vault-id and --secret-id")
    try:
        choice = input_func("Key Vault secret holds an SSH [k]ey or a [p]assword: ").strip().lower()
    except EOFError as exc:
        raise WorkspaceConfigError(
            "--auth-type is required with --key-vault-id and --secret-id"
        ) from exc
    if choice == "k":
        return "SSHKEY"
    if choice == "p":
        return "VMPASSWORD"
    raise WorkspaceConfigError("Key Vault secret type must be key or password")


def _credential(
    args: argparse.Namespace, input_func: Callable[[str], str], allow_prompt: bool
) -> tuple[CredentialMaterial | None, str, str]:
    """Create the explicit credential selection required by the generator.

    :param args: Parsed command-line options.
    :param input_func: Input function used for interactive prompts.
    :param allow_prompt: Whether this invocation may request missing values.
    :returns: Local credential material or a Key Vault reference pair.
    :raises WorkspaceConfigError: If credential selections conflict or are incomplete.
    """
    expected = _AUTH_DESTINATIONS.get(getattr(args, "auth_type", None) or "")
    local_credentials = [
        (args.ssh_key, "ssh_key"),
        (args.password_file, "password"),
    ]
    configured = [(path, name) for path, name in local_credentials if path]
    if configured and (args.key_vault_id or args.secret_id):
        raise WorkspaceConfigError(
            "Select either --ssh-key/--password-file or --key-vault-id with --secret-id"
        )
    if len(configured) > 1:
        raise WorkspaceConfigError("Select only one local credential artifact")
    if configured:
        path, destination = configured[0]
        if expected is not None and destination != expected:
            raise WorkspaceConfigError(
                f"--auth-type {args.auth_type} requires the {expected} credential artifact"
            )
        return CredentialMaterial(Path(path), destination), "", ""
    if args.key_vault_id or args.secret_id:
        return None, args.key_vault_id or "", args.secret_id or ""
    if not allow_prompt:
        raise WorkspaceConfigError(
            "Choose --ssh-key, --password-file, or --key-vault-id with --secret-id"
        )
    if expected is not None:
        return _prompt_known_auth(expected, args.auth_type, input_func, allow_prompt)
    return _prompt_any_auth(input_func, allow_prompt)


def _parser() -> argparse.ArgumentParser:
    """Build the command-line parser for the shared workspace generator.

    :returns: Parser describing every supported command-line option.
    """
    parser = argparse.ArgumentParser(
        description="Generate an initial AFA HANA HA workspace from nominated Azure VMs."
    )
    parser.add_argument("--workspace-id", required=True, help="Workspace ID to create.")
    parser.add_argument(
        "--workspace-root",
        default=REPOSITORY_ROOT / "WORKSPACES" / "SYSTEM",
        type=Path,
        help="Directory containing workspace directories.",
    )
    parser.add_argument("--resource-group", help="Resource group containing both seed VMs.")
    parser.add_argument("--scs-vm", help="SCS-cluster seed VM name.")
    parser.add_argument("--db-vm", help="Database-cluster seed VM name.")
    parser.add_argument("--ssh-key", help="Local SSH private-key file to copy into the workspace.")
    parser.add_argument("--password-file", help="Local password file to copy into the workspace.")
    parser.add_argument("--key-vault-id", help="Explicit Key Vault resource ID.")
    parser.add_argument("--secret-id", help="Explicit Key Vault secret ID.")
    parser.add_argument(
        "--auth-type",
        choices=("SSHKEY", "VMPASSWORD"),
        help="Authentication type the generated workspace must serve.",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Discover and preview without writing."
    )
    parser.add_argument("--yes", action="store_true", help="Approve generation without a prompt.")
    return parser


def _build_request(
    args: argparse.Namespace, input_func: Callable[[str], str], allow_prompt: bool
) -> GenerateRequest:
    """Resolve every operator-supplied value into a generator request.

    :param args: Parsed command-line options.
    :param input_func: Input function used for interactive prompts.
    :param allow_prompt: Whether this invocation may request missing values.
    :returns: The fully populated generation request.
    :raises WorkspaceConfigError: If a required value is unavailable.
    """
    resource_group = _prompt(args.resource_group, "Azure resource group", input_func, allow_prompt)
    scs_vm = _prompt(args.scs_vm, "SCS seed VM name", input_func, allow_prompt)
    db_vm = _prompt(args.db_vm, "Database seed VM name", input_func, allow_prompt)
    credential, key_vault_id, secret_id = _credential(args, input_func, allow_prompt)
    authentication_type = args.auth_type or ""
    if credential is None and not authentication_type:
        authentication_type = _prompt_authentication_type(input_func, allow_prompt)
    return GenerateRequest(
        workspace_root=args.workspace_root,
        workspace_id=args.workspace_id,
        resource_group=resource_group,
        scs_seed_vm=scs_vm,
        db_seed_vm=db_vm,
        credential=credential,
        key_vault_id=key_vault_id,
        secret_id=secret_id,
        authentication_type=authentication_type,
        dry_run=args.dry_run,
    )


def main(
    argv: Sequence[str] | None = None,
    input_func: Callable[[str], str] = input,
    generator_factory: Callable[[Path], WorkspaceConfigGenerator] = WorkspaceConfigGenerator,
) -> int:
    """Run the interactive or explicitly noninteractive workspace generator.

    :param argv: Optional command-line arguments excluding the executable name.
    :param input_func: Input function used for interactive confirmation.
    :param generator_factory: Factory used to construct the shared generator.
    :returns: Process exit status.
    """
    args = _parser().parse_args(argv)
    try:
        request = _build_request(args, input_func, not args.yes)
        generator = generator_factory(REPOSITORY_ROOT)
        generated = generator.generate(replace(request, dry_run=True))
        if not args.dry_run:
            if not args.yes:
                print(generated.preview())
                if input_func("Generate this workspace? [y/N]: ").strip().lower() not in {
                    "y",
                    "yes",
                }:
                    print("Workspace generation cancelled.")
                    return 0
            generator.publish(generated, request)
        print(generated.preview())
        if args.dry_run:
            print("Dry run completed; no files were written.")
        else:
            print(f"Workspace configuration created: {generated.workspace_path}")
        return 0
    except WorkspaceConfigError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
