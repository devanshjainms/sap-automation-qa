# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Generate an initially empty HA workspace from verified Azure VM facts."""

from __future__ import annotations

import hashlib
import json
import os
import time
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import urlparse

import yaml

from src.core.exceptions import WorkspaceConfigError
from src.core.workspace_collector import COMPACT_COLLECTOR
from src.core.storage.workspace.validation import (
    MAX_CONFIG_FILE_SIZE,
    parse_hosts_yaml,
    parse_sap_parameters,
    validate_workspace_id,
)

COLLECTOR_SCHEMA_VERSION = 2
MAX_RUN_COMMAND_OUTPUT = 4096
TRANSACTION_MARKER = ".workspace-config-generation.json"
ACTIVE_MARKER_SECONDS = 1800
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


class WorkspaceConfigGenerator:
    """Discover, validate, render, and atomically publish a new HA workspace."""

    def __init__(
        self,
        repository_root: Path,
        run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ) -> None:
        """Initialize the generator.

        :param repository_root: Repository root containing the unchanged workspace validator.
        :param run: Injectable subprocess runner for Azure CLI and validator calls.
        """
        self._repository_root = repository_root
        self._run = run

    def generate(self, request: GenerateRequest) -> GeneratedWorkspace:
        """Discover the requested topology and publish it unless this is a dry run.

        :param request: Validated generation request.
        :returns: Generated workspace documents and preview metadata.
        :raises WorkspaceConfigError: If discovery, validation, or publication is unsafe.
        """
        workspace = self._workspace_path(request)
        if not request.dry_run:
            self._recover_interrupted_publication(workspace)
        self._assert_initial_workspace(workspace)

        vm_inventory = self._list_vms(request.resource_group)
        seed_facts = {
            "scs": self._collect_vm(request.resource_group, request.scs_seed_vm),
            "db": self._collect_vm(request.resource_group, request.db_seed_vm),
        }
        all_facts = self._collect_cluster_facts(request.resource_group, vm_inventory, seed_facts)
        generated = self._render(workspace, all_facts, request)

        if not request.dry_run:
            self._validate_staged(workspace, generated, request)
            self._publish(workspace, generated, request.credential)

        return generated

    def publish(
        self, generated: GeneratedWorkspace, request: GenerateRequest
    ) -> GeneratedWorkspace:
        """Validate and publish documents that were already discovered and reviewed.

        Publishing the exact object returned by a dry run guarantees the operator
        approved the topology that reaches disk, and avoids a second discovery.

        :param generated: Documents produced by an earlier discovery pass.
        :param request: The request that produced ``generated``.
        :returns: The same generated workspace, now published.
        :raises WorkspaceConfigError: If validation or publication is unsafe.
        """
        workspace = self._workspace_path(request)
        if workspace != generated.workspace_path:
            raise WorkspaceConfigError("Generated workspace does not match the requested workspace")
        self._recover_interrupted_publication(workspace)
        self._assert_initial_workspace(workspace)
        self._validate_staged(workspace, generated, request)
        self._publish(workspace, generated, request.credential)
        return generated

    def _workspace_path(self, request: GenerateRequest) -> Path:
        """Resolve the requested workspace without allowing path traversal."""
        root = request.workspace_root.resolve()
        root.mkdir(parents=True, exist_ok=True)
        workspace = root / request.workspace_id
        try:
            workspace.resolve().relative_to(root)
        except ValueError as exc:
            raise WorkspaceConfigError("Workspace path escapes workspace root") from exc
        return workspace

    def _assert_initial_workspace(self, workspace: Path) -> None:
        """Reject existing or partially configured workspaces without changing them."""
        if not workspace.exists():
            return
        if not workspace.is_dir():
            raise WorkspaceConfigError(f"Workspace path is not a directory: {workspace}")
        configured = [
            path
            for path in (
                workspace / "sap-parameters.yaml",
                workspace / "hosts.yaml",
                *workspace.glob("*_hosts.yaml"),
            )
            if path.exists()
        ]
        if configured:
            names = ", ".join(sorted(path.name for path in configured if path.exists()))
            raise WorkspaceConfigError(
                f"Workspace {workspace.name} already contains configuration ({names}); "
                "initial generation does not overwrite or repair existing files"
            )

    def _list_vms(self, resource_group: str) -> list[dict[str, Any]]:
        """List Azure VM discovery candidates in the selected resource group."""
        completed = self._az(
            "vm",
            "list",
            "--resource-group",
            resource_group,
            "--show-details",
            "--output",
            "json",
        )
        try:
            inventory = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise WorkspaceConfigError("Azure VM inventory was not valid JSON") from exc
        if not isinstance(inventory, list):
            raise WorkspaceConfigError("Azure VM inventory was not a list")
        return [item for item in inventory if isinstance(item, dict)]

    def _collect_cluster_facts(
        self,
        resource_group: str,
        inventory: Sequence[dict[str, Any]],
        seed_facts: Mapping[str, dict[str, Any]],
    ) -> dict[str, list[dict[str, Any]]]:
        """Collect each cluster member once after verified candidate resolution."""
        collected: dict[str, list[dict[str, Any]]] = {}
        for tier, seed in seed_facts.items():
            member_names = self._required_string_list(seed, "cluster", "members")
            expected_members = {name.lower() for name in member_names}
            facts = [seed]
            seed_resource_id = self._identity_resource_id(seed)
            for member_name in member_names:
                candidate = self._find_vm_candidate(inventory, member_name)
                if candidate["id"].lower() == seed_resource_id.lower():
                    continue
                member_facts = self._collect_vm(resource_group, candidate["name"])
                if self._identity_resource_id(member_facts).lower() != candidate["id"].lower():
                    raise WorkspaceConfigError(
                        f"Guest IMDS identity for {candidate['name']} does not match "
                        "Azure VM identity"
                    )
                peer_members = {
                    name.lower()
                    for name in self._required_string_list(member_facts, "cluster", "members")
                }
                if peer_members != expected_members:
                    raise WorkspaceConfigError(
                        f"Cluster member {candidate['name']} reports a different "
                        f"{tier} membership than the seed node; resolve the split "
                        "cluster view before generating a workspace"
                    )
                facts.append(member_facts)
            collected[tier] = facts
        return collected

    def _find_vm_candidate(
        self, inventory: Sequence[dict[str, Any]], cluster_hostname: str
    ) -> dict[str, str]:
        """Resolve one Azure VM candidate by computer name before IMDS verification."""
        matches: list[dict[str, str]] = []
        for vm in inventory:
            profile = vm.get("osProfile")
            if not isinstance(profile, dict):
                continue
            computer_name = profile.get("computerName")
            vm_id, vm_name = vm.get("id"), vm.get("name")
            if (
                isinstance(computer_name, str)
                and computer_name.lower() == cluster_hostname.lower()
                and isinstance(vm_id, str)
                and isinstance(vm_name, str)
            ):
                matches.append({"id": vm_id, "name": vm_name})
        if len(matches) != 1:
            raise WorkspaceConfigError(
                f"Expected one Azure VM candidate for cluster member {cluster_hostname!r}, "
                f"found {len(matches)}"
            )
        return matches[0]

    def _collect_vm(self, resource_group: str, vm_name: str) -> dict[str, Any]:
        """Run the fixed compact collector and validate its Azure CLI response."""
        completed = self._az(
            "vm",
            "run-command",
            "invoke",
            "--resource-group",
            resource_group,
            "--name",
            vm_name,
            "--command-id",
            "RunShellScript",
            "--scripts",
            *COMPACT_COLLECTOR.splitlines(),
            "--output",
            "json",
        )
        facts = self._parse_run_command(completed.stdout, vm_name)
        vm = self._show_vm(resource_group, vm_name)
        identity = facts["identity"]
        assert isinstance(identity, dict)
        vm_id = vm.get("id")
        profile = vm.get("osProfile")
        admin_user = profile.get("adminUsername") if isinstance(profile, dict) else None
        if not isinstance(vm_id, str) or not isinstance(admin_user, str) or not admin_user:
            raise WorkspaceConfigError(f"Azure VM metadata for {vm_name} is incomplete")
        if vm_id.lower() != self._identity_resource_id(facts).lower():
            raise WorkspaceConfigError(
                f"Guest IMDS identity for {vm_name} does not match Azure VM identity"
            )
        identity["vm_name"] = vm_name
        identity["admin_user"] = admin_user
        return facts

    def _show_vm(self, resource_group: str, vm_name: str) -> dict[str, Any]:
        """Read exact Azure VM metadata used to enrich self-reported IMDS facts."""
        completed = self._az(
            "vm",
            "show",
            "--resource-group",
            resource_group,
            "--name",
            vm_name,
            "--output",
            "json",
        )
        try:
            vm = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise WorkspaceConfigError(f"Azure VM metadata for {vm_name} was not JSON") from exc
        if not isinstance(vm, dict):
            raise WorkspaceConfigError(f"Azure VM metadata for {vm_name} was not an object")
        return vm

    def _az(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        """Run Azure CLI with a bounded execution contract.

        :param arguments: Azure CLI arguments excluding the executable name.
        :returns: Completed CLI process.
        :raises WorkspaceConfigError: If Azure CLI fails or is unavailable.
        """
        try:
            completed = self._run(
                ["az", *arguments],
                check=False,
                capture_output=True,
                text=True,
                timeout=180,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise WorkspaceConfigError(f"Azure CLI invocation failed: {exc}") from exc
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip() or "no Azure CLI detail"
            raise WorkspaceConfigError(f"Azure CLI invocation failed: {detail}")
        return completed

    def _parse_run_command(self, output: str, vm_name: str) -> dict[str, Any]:
        """Parse Azure's Run Command envelope and a compact collector fact document."""
        try:
            envelope = json.loads(output)
        except json.JSONDecodeError as exc:
            raise WorkspaceConfigError(f"Run Command response for {vm_name} was not JSON") from exc
        value = envelope.get("value") if isinstance(envelope, dict) else None
        if not isinstance(value, list):
            raise WorkspaceConfigError(f"Run Command response for {vm_name} had no result entries")
        messages: list[str] = []
        for entry in value:
            if not isinstance(entry, dict):
                continue
            code = entry.get("code", "")
            message = entry.get("message", "")
            if not isinstance(code, str) or not isinstance(message, str):
                continue
            if "error" in code.lower() or "failed" in code.lower():
                raise WorkspaceConfigError(f"Run Command failed for {vm_name}: {message}")
            if "stderr" in code.lower():
                continue
            messages.append(message)
        if len(messages) != 1:
            raise WorkspaceConfigError(
                f"Run Command for {vm_name} must return exactly one result message"
            )
        document = self._collector_document(messages[0], vm_name)
        encoded = document.encode("utf-8")
        if len(encoded) > MAX_RUN_COMMAND_OUTPUT:
            raise WorkspaceConfigError(f"Run Command output for {vm_name} exceeds 4096 bytes")
        try:
            facts = json.loads(document)
        except json.JSONDecodeError as exc:
            raise WorkspaceConfigError(f"Collector output for {vm_name} was not JSON") from exc
        if not isinstance(facts, dict) or facts.get("schema_version") != COLLECTOR_SCHEMA_VERSION:
            raise WorkspaceConfigError(f"Collector output for {vm_name} has an unsupported schema")
        self._identity_resource_id(facts)
        return facts

    @staticmethod
    def _collector_document(message: str, vm_name: str) -> str:
        """Extract the compact fact document from an Azure Run Command result message.

        Azure wraps shell output as ``Enable succeeded: \\n[stdout]\\n...\\n[stderr]\\n...``.
        Guest diagnostics on stderr are surfaced only when no fact document was produced.

        :param message: Raw Run Command result message.
        :param vm_name: Azure VM name used for diagnostics.
        :returns: The compact JSON fact document emitted by the collector.
        :raises WorkspaceConfigError: When the message carries no fact document.
        """
        stdout, stderr = message, ""
        if "[stdout]" in message:
            _, _, remainder = message.partition("[stdout]")
            stdout, _, stderr = remainder.partition("[stderr]")
        document = next(
            (
                line.strip()
                for line in reversed(stdout.splitlines())
                if line.lstrip().startswith("{")
            ),
            "",
        )
        if not document:
            detail = stderr.strip() or stdout.strip() or "no collector output"
            raise WorkspaceConfigError(f"Collector produced no facts on {vm_name}: {detail[:400]}")
        return document

    @staticmethod
    def _identity_resource_id(facts: Mapping[str, Any]) -> str:
        """Return an exact guest IMDS resource ID from normalized facts."""
        identity = facts.get("identity")
        resource_id = identity.get("resource_id") if isinstance(identity, dict) else None
        if not isinstance(resource_id, str) or not resource_id.startswith("/subscriptions/"):
            raise WorkspaceConfigError("Collector facts are missing an IMDS resource_id")
        return resource_id

    @staticmethod
    def _required_string_list(facts: Mapping[str, Any], parent: str, field: str) -> list[str]:
        """Read a bounded non-empty list of strings from collector facts."""
        container = facts.get(parent)
        values = container.get(field) if isinstance(container, dict) else None
        if (
            not isinstance(values, list)
            or not values
            or not all(isinstance(value, str) and value for value in values)
        ):
            raise WorkspaceConfigError(f"Collector facts are missing {parent}.{field}")
        if len(values) > 16:
            raise WorkspaceConfigError(f"Collector facts exceed the {parent}.{field} limit")
        return values

    def _render(
        self,
        workspace: Path,
        clusters: Mapping[str, list[dict[str, Any]]],
        request: GenerateRequest,
    ) -> GeneratedWorkspace:
        """Render validator-compatible YAML only from explicit AFA collector facts."""
        scs_facts = clusters.get("scs", [])
        db_facts = clusters.get("db", [])
        if len(scs_facts) != 2 or len(db_facts) < 2:
            raise WorkspaceConfigError(
                "Only two-node SCS and HA HANA clusters are supported initially"
            )
        scs_cluster_type = self._cluster_type(scs_facts, "SCS")
        database_cluster_type = self._cluster_type(db_facts, "database")
        scs = self._scs_details(scs_facts)
        db = self._db_details(db_facts)
        nfs_provider = self._nfs_provider(scs_facts + db_facts, request.resource_group)

        parameters: dict[str, Any] = {
            "sap_sid": scs["sid"],
            "scs_high_availability": True,
            "scs_cluster_type": scs_cluster_type,
            "scs_instance_number": scs["ascs"]["instance_number"],
            "ers_instance_number": scs["ers"]["instance_number"],
            "db_sid": db["sid"],
            "db_instance_number": db["instance_number"],
            "platform": "HANA",
            "database_high_availability": True,
            "database_cluster_type": database_cluster_type,
            "database_scale_out": db["scale_out"],
            "NFS_provider": nfs_provider,
            "authentication_type": request.authentication_type,
        }
        if request.key_vault_id:
            parameters["key_vault_id"] = request.key_vault_id
            parameters["secret_id"] = request.secret_id

        hosts = self._hosts(scs, db, request.credential is not None)
        return GeneratedWorkspace(workspace, parameters, hosts)

    @staticmethod
    def _cluster_type(facts: Sequence[Mapping[str, Any]], tier: str) -> str:
        """Classify a cluster's fencing mechanism from unambiguous Pacemaker evidence.

        ``fence_azure_arm`` is AFA. SBD is classified by its backing block devices:
        Azure Shared Disk paths are ASD and any other device is an iSCSI target.

        :param facts: Normalized facts from every discovered member of one tier.
        :param tier: Tier name used for diagnostics.
        :returns: ``AFA``, ``ASD``, or ``ISCSI``.
        :raises WorkspaceConfigError: When fencing evidence is missing or ambiguous.
        """
        agent_set: set[str] = set()
        devices: set[str] = set()
        for fact in facts:
            cluster = fact.get("cluster")
            agents = cluster.get("fencing_agents") if isinstance(cluster, dict) else None
            if not isinstance(agents, list) or not all(isinstance(agent, str) for agent in agents):
                raise WorkspaceConfigError(f"{tier} fencing evidence is missing")
            agent_set.update(agents)
            found = cluster.get("fencing_devices") if isinstance(cluster, dict) else None
            if isinstance(found, list):
                devices.update(device for device in found if isinstance(device, str) and device)
        if agent_set == {"fence_azure_arm"}:
            return "AFA"
        if agent_set and agent_set <= {"external/sbd", "fence_sbd"}:
            if not devices:
                raise WorkspaceConfigError(
                    f"{tier} SBD fencing exposes no backing devices to classify"
                )
            azure_disks = {device for device in devices if device.startswith("/dev/disk/azure/")}
            if len(azure_disks) == len(devices):
                return "ASD"
            if not azure_disks:
                return "ISCSI"
            raise WorkspaceConfigError(
                f"{tier} SBD mixes Azure Shared Disk and iSCSI devices: {sorted(devices)}"
            )
        raise WorkspaceConfigError(f"{tier} fencing is ambiguous: {sorted(agent_set)}")

    @staticmethod
    def _scs_details(facts: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        """Extract exactly one ASCS and ERS semantic resource from SCS collector facts."""
        instances: list[dict[str, Any]] = []
        for fact in facts:
            cluster = fact.get("cluster")
            values = cluster.get("sap_instances") if isinstance(cluster, dict) else None
            if isinstance(values, list):
                instances.extend(value for value in values if isinstance(value, dict))
        ascs = _unique_instances(instances, "ASCS")
        ers = _unique_instances(instances, "ERS")
        if len(ascs) != 1 or len(ers) != 1:
            raise WorkspaceConfigError("Expected exactly one semantic ASCS and ERS resource")
        sid = ascs[0].get("sid")
        if not isinstance(sid, str) or sid != ers[0].get("sid"):
            raise WorkspaceConfigError("ASCS and ERS facts disagree on SAP SID")
        for item in (ascs[0], ers[0]):
            if not all(
                isinstance(item.get(field), str) and item[field]
                for field in ("instance_number", "virtual_host", "vip")
            ):
                raise WorkspaceConfigError(
                    "SCS facts are missing an instance number or virtual host"
                )
        return {
            "sid": sid,
            "ascs": ascs[0],
            "ers": ers[0],
            "facts": sorted(facts, key=lambda fact: str(fact["identity"]["hostname"])),
        }

    @staticmethod
    def _db_details(facts: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        """Validate one complete HANA topology from each database member."""
        hana = [fact.get("hana") for fact in facts]
        normalized_hana = [item for item in hana if isinstance(item, dict)]
        if len(normalized_hana) != len(facts):
            raise WorkspaceConfigError("Database facts are missing HANA replication data")
        first = normalized_hana[0]
        sid, instance = first.get("sid"), first.get("instance_number")
        scale_out = first.get("scale_out")
        if (
            not isinstance(sid, str)
            or not isinstance(instance, str)
            or not isinstance(scale_out, bool)
        ):
            raise WorkspaceConfigError("Database HANA facts are incomplete")
        if any(
            item.get("sid") != sid or item.get("instance_number") != instance
            for item in normalized_hana[1:]
        ):
            raise WorkspaceConfigError("Database members disagree on HANA SID or instance number")
        if any(item.get("scale_out") != scale_out for item in normalized_hana[1:]):
            raise WorkspaceConfigError("Database members disagree on the HANA scale-out topology")
        if not all(
            isinstance(item.get("virtual_host"), str) and item["virtual_host"]
            for item in normalized_hana
        ):
            raise WorkspaceConfigError("Database HANA facts are missing a virtual host")
        return {"sid": sid, "instance_number": instance, "scale_out": scale_out, "facts": facts}

    def _nfs_provider(self, facts: Sequence[Mapping[str, Any]], resource_group: str) -> str:
        """Resolve the shared SAP mount to exact Azure resource metadata.

        Azure Files NFS mounts always carry the storage account as the first path
        segment, so the account is resolved from the path rather than from the
        mount host, which SDAF deployments may front with a local proxy address.

        :param facts: Normalized facts from all discovered HA members.
        :param resource_group: Resource group used to resolve Azure Files metadata.
        :returns: Verified storage provider.
        :raises WorkspaceConfigError: If storage cannot be classified without inference.
        """
        sources = {
            storage["sapmnt_source"]
            for fact in facts
            if isinstance((storage := fact.get("storage")), dict)
            and isinstance(storage.get("sapmnt_source"), str)
            and storage["sapmnt_source"]
        }
        if not sources:
            raise WorkspaceConfigError("No shared SAP mount was discovered on any HA member")
        accounts = {source.partition(":")[2].strip("/").split("/")[0].lower() for source in sources}
        if len(accounts) != 1 or not next(iter(accounts)):
            raise WorkspaceConfigError(
                f"HA members disagree on the shared SAP mount: {sorted(sources)}"
            )
        account_name = next(iter(accounts))
        account = self._storage_account(account_name, resource_group)
        endpoint = (
            account.get("primaryEndpoints", {}).get("file")
            if isinstance(account.get("primaryEndpoints"), dict)
            else None
        )
        host = urlparse(endpoint).hostname if isinstance(endpoint, str) else None
        if not host or not host.lower().startswith(f"{account_name}.file."):
            raise WorkspaceConfigError(
                "Shared SAP mount does not resolve to the expected Azure Files account"
            )
        return "AFS"

    def _storage_account(self, account_name: str, resource_group: str) -> dict[str, Any]:
        """Read Azure Files account metadata, tolerating a shared-storage resource group.

        :param account_name: Storage account hosting the shared SAP mount.
        :param resource_group: Resource group containing the seed VMs.
        :returns: Azure storage account metadata.
        :raises WorkspaceConfigError: When the account metadata is not a JSON object.
        """
        try:
            completed = self._az(
                "storage",
                "account",
                "show",
                "--resource-group",
                resource_group,
                "--name",
                account_name,
                "--output",
                "json",
            )
        except WorkspaceConfigError:
            completed = self._az(
                "storage", "account", "show", "--name", account_name, "--output", "json"
            )
        try:
            account = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise WorkspaceConfigError("Azure Files metadata was not valid JSON") from exc
        if not isinstance(account, dict):
            raise WorkspaceConfigError("Azure Files metadata was not an object")
        return account

    @staticmethod
    def _hosts(
        scs: Mapping[str, Any], db: Mapping[str, Any], use_local_credential: bool
    ) -> dict[str, Any]:
        """Render exactly the DB, SCS, and ERS groups required for HA validation.

        :returns: Validator-compatible inventory mapping.
        """
        sid = scs["sid"]

        def host_variables(fact: Mapping[str, Any], virtual_host: str) -> dict[str, str]:
            """Render required host variables from one verified member.

            :param fact: Normalized fact document for the cluster member.
            :param virtual_host: Semantic virtual host for the member's SAP role.
            :returns: Host variable mapping.
            """
            identity = fact.get("identity")
            if not isinstance(identity, dict):
                raise WorkspaceConfigError("Host identity facts are missing")
            hostname, address, vm_name, user = (
                identity.get("hostname"),
                identity.get("private_ip"),
                identity.get("vm_name"),
                identity.get("admin_user"),
            )
            if (
                not isinstance(hostname, str)
                or not hostname
                or not isinstance(address, str)
                or not address
                or not isinstance(vm_name, str)
                or not vm_name
                or not isinstance(user, str)
                or not user
            ):
                raise WorkspaceConfigError("Host identity facts are incomplete")
            return {
                "ansible_host": address,
                "ansible_user": user,
                "ansible_connection": "ssh",
                "connection_type": "key" if use_local_credential else "keyvault",
                "virtual_host": virtual_host,
                "become_user": "root",
                "os_type": "linux",
                "vm_name": vm_name,
            }

        scs_facts = scs["facts"]
        db_facts = db["facts"]
        return {
            f"{sid}_DB": {
                "hosts": {
                    str(fact["identity"]["hostname"]): host_variables(
                        fact, str(fact["hana"]["virtual_host"])
                    )
                    for fact in db_facts
                },
                "vars": {"node_tier": "hana", "supported_tiers": ["hana"]},
            },
            f"{sid}_SCS": {
                "hosts": {
                    str(scs_facts[0]["identity"]["hostname"]): host_variables(
                        scs_facts[0], str(scs["ascs"]["virtual_host"])
                    )
                },
                "vars": {"node_tier": "scs", "supported_tiers": ["scs"]},
            },
            f"{sid}_ERS": {
                "hosts": {
                    str(scs_facts[1]["identity"]["hostname"]): host_variables(
                        scs_facts[1], str(scs["ers"]["virtual_host"])
                    )
                },
                "vars": {"node_tier": "ers", "supported_tiers": ["ers"]},
            },
        }

    def _validate_staged(
        self, workspace: Path, generated: GeneratedWorkspace, request: GenerateRequest
    ) -> None:
        """Run the unchanged validator against a complete temporary workspace."""
        with tempfile.TemporaryDirectory(dir=workspace.parent, prefix=".workspace-config-") as temp:
            staged = Path(temp) / workspace.name
            staged.mkdir()
            self._write_documents(staged, generated)
            self._stage_credential(staged, request.credential)
            validator = (
                self._repository_root
                / ".github"
                / "skills"
                / "workspace-validator"
                / "scripts"
                / "validate_workspace.py"
            )
            environment = os.environ.copy()
            environment["STAF_SKIP_SSH"] = "1"
            environment["PYTHONIOENCODING"] = "utf-8"
            try:
                completed = self._run(
                    [sys.executable, str(validator), str(staged)],
                    check=False,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    env=environment,
                    timeout=60,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise WorkspaceConfigError(
                    f"Generated workspace could not be validated: {exc}"
                ) from exc
            if completed.returncode != 0:
                detail = completed.stdout.strip() or completed.stderr.strip() or "validator failed"
                raise WorkspaceConfigError(f"Generated workspace failed validation: {detail}")

    def _publish(
        self, workspace: Path, generated: GeneratedWorkspace, credential: CredentialMaterial | None
    ) -> None:
        """Atomically publish only previously absent configuration files."""
        workspace.mkdir(parents=True, exist_ok=True)
        self._assert_initial_workspace(workspace)
        with tempfile.TemporaryDirectory(dir=workspace.parent, prefix=".workspace-config-") as temp:
            staged = Path(temp)
            self._write_documents(staged, generated)
            self._stage_credential(staged, credential)
            files = ["sap-parameters.yaml", "hosts.yaml"]
            if credential is not None:
                files.insert(0, credential.destination_name)
            hashes = {name: self._sha256(staged / name) for name in files}
            marker = workspace / TRANSACTION_MARKER
            try:
                with marker.open("x", encoding="utf-8") as handle:
                    json.dump(
                        {
                            "files": hashes,
                            "pid": os.getpid(),
                            "started": time.time(),
                        },
                        handle,
                        sort_keys=True,
                    )
                for name in files:
                    destination = workspace / name
                    try:
                        os.link(staged / name, destination)
                    except FileExistsError as exc:
                        raise WorkspaceConfigError(f"Refusing to replace existing {name}") from exc
                    (staged / name).unlink()
            finally:
                if marker.exists() and all(
                    (workspace / name).exists() and self._sha256(workspace / name) == digest
                    for name, digest in hashes.items()
                ):
                    marker.unlink()

    @staticmethod
    def _write_documents(directory: Path, generated: GeneratedWorkspace) -> None:
        """Serialize bounded YAML documents and parse them through shared validators."""
        documents = {
            "sap-parameters.yaml": generated.sap_parameters,
            "hosts.yaml": generated.hosts,
        }
        for name, content in documents.items():
            encoded = yaml.safe_dump(dict(content), sort_keys=False).encode("utf-8")
            if len(encoded) > MAX_CONFIG_FILE_SIZE:
                raise WorkspaceConfigError(f"Generated {name} exceeds the workspace size limit")
            (directory / name).write_bytes(encoded)
            if name == "hosts.yaml":
                parse_hosts_yaml(encoded)
            else:
                parse_sap_parameters(encoded)

    @staticmethod
    def _stage_credential(directory: Path, credential: CredentialMaterial | None) -> None:
        """Stage explicit local credentials without printing or parsing secret content."""
        if credential is None:
            return
        if not credential.source.is_file():
            raise WorkspaceConfigError(f"Credential source does not exist: {credential.source}")
        destination = directory / credential.destination_name
        shutil.copyfile(credential.source, destination)
        os.chmod(destination, 0o600)

    def _recover_interrupted_publication(self, workspace: Path) -> None:
        """Finish or roll back a publication that a previous run left marked.

        A publication that completed every ``os.replace`` but crashed before the
        marker was removed leaves a workspace that is whole. That state is
        completed by dropping the marker, never by deleting the files.
        """
        marker = workspace / TRANSACTION_MARKER
        if not marker.exists():
            return
        try:
            marker_data = json.loads(marker.read_text(encoding="utf-8"))
            files = marker_data["files"]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise WorkspaceConfigError(
                "Workspace has an unreadable generation transaction marker"
            ) from exc
        if not isinstance(files, dict) or not all(
            isinstance(name, str) and isinstance(digest, str) for name, digest in files.items()
        ):
            raise WorkspaceConfigError("Workspace has an invalid generation transaction marker")
        started = marker_data.get("started")
        if isinstance(started, (int, float)) and 0 <= time.time() - started < ACTIVE_MARKER_SECONDS:
            raise WorkspaceConfigError(
                "Another workspace generation appears to be in progress; wait for it "
                "to finish or remove the transaction marker if it is stale"
            )
        for name, digest in files.items():
            if Path(name).name != name or name not in {
                "sap-parameters.yaml",
                "hosts.yaml",
                "ssh_key",
                "password",
            }:
                raise WorkspaceConfigError(
                    "Workspace transaction marker contains an unsafe file name"
                )
            path = workspace / name
            if path.exists() and self._sha256(path) != digest:
                raise WorkspaceConfigError(
                    "Workspace has an interrupted generation with non-matching files; "
                    "repair manually"
                )
        if all(
            (workspace / name).exists() and self._sha256(workspace / name) == digest
            for name, digest in files.items()
        ):
            marker.unlink()
            return
        for name in files:
            (workspace / name).unlink(missing_ok=True)
        marker.unlink()

    @staticmethod
    def _sha256(path: Path) -> str:
        """Return a file's SHA-256 digest."""
        return hashlib.sha256(path.read_bytes()).hexdigest()


def _unique_instances(instances: Sequence[dict[str, Any]], role: str) -> list[dict[str, Any]]:
    """Return one matching semantic resource, tolerating identical peer observations."""
    matching = [item for item in instances if item.get("role") == role]
    if not matching:
        return []
    canonical = {
        key: value
        for key, value in matching[0].items()
        if key in {"sid", "role", "instance_number", "vip"}
    }
    if any(
        {
            key: value
            for key, value in item.items()
            if key in {"sid", "role", "instance_number", "vip"}
        }
        != canonical
        for item in matching[1:]
    ):
        raise WorkspaceConfigError(f"Cluster members disagree on semantic {role} resource facts")
    return [matching[0]]
