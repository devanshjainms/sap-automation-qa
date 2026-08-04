# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Immutable request and result types for workspace configuration generation.

These types are the contract between discovery and publication. Publication
compares the request that produced a preview against the request presented at
publish time, so every field here that can change rendered or staged output
must participate in dataclass equality.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from src.core.exceptions import WorkspaceConfigError
from src.core.storage.workspace.validation import validate_workspace_id

AUTHENTICATION_TYPES = {"ssh_key": "SSHKEY", "password": "VMPASSWORD"}


@dataclass(frozen=True)
class CredentialMaterial:
    """Explicit local SSH credential material to publish with a new workspace."""

    source: Path
    destination_name: str

    def __post_init__(self) -> None:
        """Validate the supported credential artifact names."""
        if self.destination_name not in {"ssh_key", "password"}:
            raise WorkspaceConfigError("Credential destination must be ssh_key or password")


@dataclass(frozen=True)
class GenerateRequest:
    """Immutable request for an initial workspace configuration generation."""

    workspace_root: Path
    workspace_id: str
    resource_group: str
    scs_seed_vm: str
    db_seed_vm: str
    credential: CredentialMaterial | None = None
    key_vault_id: str = ""
    secret_id: str = ""
    authentication_type: str = ""
    dry_run: bool = False

    def __post_init__(self) -> None:
        """Validate mutually exclusive and required request fields."""
        validate_workspace_id(self.workspace_id)
        if not all((self.resource_group, self.scs_seed_vm, self.db_seed_vm)):
            raise WorkspaceConfigError("Resource group, SCS VM, and DB VM are required")
        if bool(self.key_vault_id) != bool(self.secret_id):
            raise WorkspaceConfigError("key_vault_id and secret_id must be supplied together")
        if self.credential is not None and self.key_vault_id:
            raise WorkspaceConfigError(
                "Select either a local credential artifact or Key Vault authentication"
            )
        if self.credential is None and not self.key_vault_id:
            raise WorkspaceConfigError("An explicit SSH credential source is required")
        self._resolve_authentication_type()

    def _resolve_authentication_type(self) -> None:
        """Derive or validate the authentication type the workspace must serve.

        :raises WorkspaceConfigError: If the declared type is unknown, conflicts
            with the chosen credential artifact, or is missing for Key Vault.
        """
        if self.authentication_type and self.authentication_type not in set(
            AUTHENTICATION_TYPES.values()
        ):
            raise WorkspaceConfigError(
                f"authentication_type must be one of {sorted(set(AUTHENTICATION_TYPES.values()))}"
            )
        if self.credential is not None:
            derived = AUTHENTICATION_TYPES[self.credential.destination_name]
            if self.authentication_type and self.authentication_type != derived:
                raise WorkspaceConfigError(
                    f"authentication_type {self.authentication_type} conflicts with the "
                    f"{self.credential.destination_name} credential artifact"
                )
            object.__setattr__(self, "authentication_type", derived)
        elif not self.authentication_type:
            raise WorkspaceConfigError(
                "authentication_type is required when authenticating through Key Vault"
            )


@dataclass(frozen=True)
class GeneratedWorkspace:
    """Sanitized preview and rendered documents for a generated workspace."""

    workspace_path: Path
    sap_parameters: Mapping[str, Any]
    hosts: Mapping[str, Any]
    request: GenerateRequest

    def preview(self) -> str:
        """Return a secret-free summary of the generated topology.

        :returns: Human-readable topology summary that excludes credential values.
        """
        return (
            f"Workspace: {self.workspace_path.name}\n"
            f"SAP SID: {self.sap_parameters['sap_sid']}\n"
            f"DB SID: {self.sap_parameters['db_sid']}\n"
            f"SCS fencing: {self.sap_parameters['scs_cluster_type']}\n"
            f"DB fencing: {self.sap_parameters['database_cluster_type']}\n"
            f"DB scale-out: {self.sap_parameters['database_scale_out']}"
        )
