# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Azure infrastructure deployer for E2E validation.
"""

from __future__ import annotations
import json
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from e2e.src.config import Distro, E2EConfig
from e2e.src.remote_executor import (
    RemoteExecutor,
)

logger = logging.getLogger(__name__)

_RUN_TIMEOUT = 300
_BICEP_DIR = Path(__file__).resolve().parents[1] / "deploy"


@dataclass
class DeployedVM:
    """Tracks a provisioned management VM.

    :param distro: Linux distribution.
    :param vm_name: Azure VM resource name.
    :param resource_group: Azure resource group.
    :param private_ip: Private IP address (no public IP).
    :param admin_username: SSH admin user.
    :param admin_password: Admin password for SSH.
    """

    distro: Distro
    vm_name: str = ""
    resource_group: str = ""
    private_ip: str = ""
    admin_username: str = "azureuser"
    admin_password: str = ""


def _az(
    args: list[str],
    *,
    timeout: int = _RUN_TIMEOUT,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run an ``az`` CLI command.

    :param args: CLI arguments after ``az``.
    :param timeout: Command timeout in seconds.
    :param check: Raise on non-zero exit.
    :returns: Completed process.
    :rtype: subprocess.CompletedProcess
    :raises subprocess.CalledProcessError: On failure if *check*.
    """
    cmd = ["az"] + args
    logger.info("az %s", " ".join(args[:4]))
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=check,
    )


class AzureDeployer:
    """Manages the lifecycle of E2E management VMs via Bicep.

    :param config: E2E configuration.
    """

    def __init__(self, config: E2EConfig) -> None:
        self._cfg = config
        self._vms: list[DeployedVM] = []

    def provision_all(self) -> list[DeployedVM]:
        """Deploy VMs via Bicep with user-assigned identity.

        :returns: List of deployed VMs with connection details.
        :rtype: list[DeployedVM]
        :raises RuntimeError: If provisioning fails completely.
        """
        self._ensure_resource_group()
        self._deploy_bicep()

        if not self._vms:
            raise RuntimeError("No deployer VMs were provisioned " "successfully.")

        return self._vms

    def unmount_all(
        self,
        executor_factory=None,
    ) -> dict[str, bool]:
        """Unmount /mnt/workspaces on every deployed VM.


        :param executor_factory: Callable(vm) -> executor.
            Injected to avoid circular imports.  When *None*
            the default ``RemoteExecutor`` is used.
        :returns: Map of vm_name -> success boolean.
        :rtype: dict[str, bool]
        """
        if executor_factory is None:

            executor_factory = RemoteExecutor

        results: dict[str, bool] = {}
        for vm in self._vms:
            executor = executor_factory(vm)
            logger.info(
                "Unmounting /mnt/workspaces on %s",
                vm.vm_name,
            )
            unmount_cmd = (
                "sudo sed -i "
                "'\\|/mnt/workspaces|d' /etc/fstab; "
                "sudo umount /mnt/workspaces 2>/dev/null "
                "|| true"
            )
            r = executor.run(unmount_cmd, timeout=60)
            ok = r.return_code == 0
            results[vm.vm_name] = ok
            if ok:
                logger.info(
                    "Unmounted /mnt/workspaces on %s",
                    vm.vm_name,
                )
            else:
                logger.warning(
                    "Unmount on %s rc=%d: %s",
                    vm.vm_name,
                    r.return_code,
                    r.stderr[:200],
                )
        return results

    def delete_vms(self) -> None:
        """Delete all deployed VMs and associated resources.

        Deletes VM, NIC, and OS disk for each provisioned VM.
        Idempotent — ignores 404s.
        """
        for vm in self._vms:
            logger.info(
                "Deleting VM %s in %s",
                vm.vm_name,
                vm.resource_group,
            )
            _az(
                [
                    "vm",
                    "delete",
                    "--resource-group",
                    vm.resource_group,
                    "--name",
                    vm.vm_name,
                    "--yes",
                    "--force-deletion",
                    "true",
                ],
                check=False,
                timeout=300,
            )
            _az(
                [
                    "network",
                    "nic",
                    "delete",
                    "--resource-group",
                    vm.resource_group,
                    "--name",
                    f"{vm.vm_name}-nic",
                ],
                check=False,
                timeout=120,
            )
            disk_result = _az(
                [
                    "disk",
                    "list",
                    "--resource-group",
                    vm.resource_group,
                    "--query",
                    (f"[?starts_with(name, " f"'{vm.vm_name}')].name"),
                    "-o",
                    "tsv",
                ],
                check=False,
                timeout=60,
            )
            for disk_name in disk_result.stdout.strip().splitlines():
                if disk_name:
                    _az(
                        [
                            "disk",
                            "delete",
                            "--resource-group",
                            vm.resource_group,
                            "--name",
                            disk_name,
                            "--yes",
                        ],
                        check=False,
                        timeout=120,
                    )
            logger.info("Deleted VM %s", vm.vm_name)

    def teardown(self) -> None:
        """
        Delete the entire resource group (idempotent).
        """
        if self._cfg.skip_teardown:
            logger.warning(
                "skip_teardown=True — leaving RG %s intact",
                self._cfg.azure_resource_group,
            )
            return

        logger.info(
            "Tearing down resource group %s",
            self._cfg.azure_resource_group,
        )
        _az(
            [
                "group",
                "delete",
                "--name",
                self._cfg.azure_resource_group,
                "--yes",
                "--no-wait",
            ],
            check=False,
            timeout=120,
        )

    @property
    def deployed_vms(self) -> list[DeployedVM]:
        """Return list of deployed VMs.

        :returns: Currently tracked VMs.
        :rtype: list[DeployedVM]
        """
        return list(self._vms)

    def _ensure_resource_group(self) -> None:
        """Create the resource group if it does not exist."""
        _az(
            [
                "group",
                "create",
                "--name",
                self._cfg.azure_resource_group,
                "--location",
                self._cfg.azure_location,
                "--tags",
                "purpose=e2e-validation",
                f"ref={self._cfg.github_ref}",
            ]
        )

    def _deploy_bicep(self) -> None:
        """
        Run ``az deployment group create`` with main.bicep.
        """
        template = _BICEP_DIR / "main.bicep"
        enabled = self._cfg.enabled_distros()

        params: dict[str, Any] = {
            "adminUsername": {"value": self._cfg.vm_admin_username},
            "adminPassword": {"value": self._cfg.vm_admin_password},
            "vmSize": {"value": self._cfg.vm_size},
            "subnetId": {"value": self._cfg.vnet_subnet_id},
            "userAssignedIdentityId": {"value": (self._cfg.user_assigned_identity_id)},
            "deployRhel": {"value": Distro.RHEL in enabled},
            "deploySles": {"value": Distro.SLES in enabled},
            "deployUbuntu": {"value": Distro.UBUNTU in enabled},
        }

        if self._cfg.storage_account_name:
            params["storageAccountName"] = {"value": self._cfg.storage_account_name}
            params["fileShareName"] = {"value": self._cfg.file_share_name}

        params_json = json.dumps(params)

        result = _az(
            [
                "deployment",
                "group",
                "create",
                "--resource-group",
                self._cfg.azure_resource_group,
                "--template-file",
                str(template),
                "--parameters",
                params_json,
                "--output",
                "json",
            ],
            timeout=self._cfg.deploy_timeout_seconds,
        )

        deployment = json.loads(result.stdout)
        outputs = deployment.get("properties", {}).get("outputs", {})

        distro_prefix_map: dict[str, Distro] = {
            "rhel": Distro.RHEL,
            "sles": Distro.SLES,
            "ubuntu": Distro.UBUNTU,
        }

        for prefix, distro in distro_prefix_map.items():
            if distro not in enabled:
                continue

            vm_name = outputs.get(f"{prefix}VmName", {}).get("value", "")
            private_ip = outputs.get(f"{prefix}PrivateIp", {}).get("value", "")

            if not private_ip:
                logger.error(
                    "No private IP for %s VM",
                    distro.value,
                )
                continue

            vm = DeployedVM(
                distro=distro,
                vm_name=vm_name,
                resource_group=(self._cfg.azure_resource_group),
                private_ip=private_ip,
                admin_username=(self._cfg.vm_admin_username),
                admin_password=(self._cfg.vm_admin_password),
            )
            self._vms.append(vm)
            logger.info(
                "Deployed %s VM: %s @ %s",
                distro.value,
                vm.vm_name,
                vm.private_ip,
            )
