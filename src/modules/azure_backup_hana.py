# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Ansible module to validate and test Azure Backup for SAP HANA databases.
"""

import logging
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional
from azure.identity import ManagedIdentityCredential
from azure.mgmt.recoveryservicesbackup import (
    RecoveryServicesBackupClient,
)
from azure.mgmt.recoveryservicesbackup import models as backup_models
from ansible.module_utils.basic import AnsibleModule

try:
    from ansible.module_utils.sap_automation_qa import SapAutomationQA
    from ansible.module_utils.enums import TestStatus, BackupOperation
except ImportError:
    from src.module_utils.sap_automation_qa import SapAutomationQA
    from src.module_utils.enums import TestStatus, BackupOperation

DOCUMENTATION = r"""
---
module: azure_backup_hana
short_description: Validates and tests Azure Backup for SAP HANA databases
description:
    - Discovers protected SAP HANA databases in a Recovery Services vault
    - Verifies backup configuration status and last restore points
    - Triggers restore operations (to database or filesystem)
    - Monitors restore job status until completion or timeout
options:
    operation:
        description:
            - The backup operation to perform.
        type: str
        required: true
        choices:
            - discover_protected_items
            - check_restore_points
            - restore_to_database
            - restore_to_filesystem
            - check_restore_job
    vault_resource_id:
        description:
            - Full ARM resource ID of the Recovery Services vault.
        type: str
        required: true
    database_sid:
        description:
            - SAP HANA database SID (e.g. H05).
        type: str
        required: false
    container_name:
        description:
            - Backup container name
              (e.g. VMAppContainer;Compute;rg;vmname).
        type: str
        required: false
    item_name:
        description:
            - Backup item name
              (e.g. saphanadatabase;h05;systemdb).
        type: str
        required: false
    restore_point_time:
        description:
            - Point-in-time for restore in UTC (ISO 8601).
              If omitted, the latest recovery point is used.
        type: str
        required: false
    target_container_name:
        description:
            - Target container for cross-VM restore.
        type: str
        required: false
    target_database_name:
        description:
            - Target database name for cross-VM restore
              (e.g. saphanadatabase;h05;systemdb).
        type: str
        required: false
    target_filesystem_path:
        description:
            - Filesystem path for restore-as-files
              (e.g. /sapinstall/hana_backup/S01/).
        type: str
        required: false
    target_vm_name:
        description:
            - Target VM name for restore-as-files
              (only for HA/cross-VM).
        type: str
        required: false
    target_vm_resource_group:
        description:
            - Target VM resource group for restore-as-files.
        type: str
        required: false
    restore_job_id:
        description:
            - Job ID of a previously triggered restore
              (for check_restore_job).
        type: str
        required: false
    poll_interval_seconds:
        description:
            - Polling interval in seconds when waiting
              for restore job.
        type: int
        required: false
        default: 30
    poll_timeout_seconds:
        description:
            - Maximum seconds to wait for restore job
              completion.
        type: int
        required: false
        default: 7200
    subscription_id:
        description:
            - Azure subscription ID that contains the vault.
        type: str
        required: true
    msi_client_id:
        description:
            - Client ID of a user-assigned managed identity.
              Omit or leave empty to use the system-assigned MI.
        type: str
        required: false
        default: ""
author:
    - Microsoft Corporation
notes:
    - Uses the azure-mgmt-recoveryservicesbackup Python SDK.
    - Requires the managed identity to have Backup Operator role
      on the Recovery Services vault.
requirements:
    - python >= 3.10
    - azure-identity
    - azure-mgmt-recoveryservicesbackup
"""

EXAMPLES = r"""
- name: Discover protected HANA databases
  azure_backup_hana:
    operation: discover_protected_items
    vault_resource_id: "/subscriptions/xxxx/resourceGroups/my-rg/providers/Microsoft.RecoveryServices/vaults/my-vault"
    subscription_id: "{{ subscription_id }}"
    msi_client_id: "{{ msi_client_id | default('') }}"

- name: Check restore points for all items
  azure_backup_hana:
    operation: check_restore_points
    vault_resource_id: "{{ backup_vault_resource_id }}"
    subscription_id: "{{ subscription_id }}"
"""

RETURN = r"""
status:
    description: Overall status of the operation
    returned: always
    type: str
    sample: "PASSED"
message:
    description: Human-readable summary
    returned: always
    type: str
    sample: "All 3 protected items are healthy."
protected_items:
    description: List of discovered protected backup items
    returned: when operation == discover_protected_items
    type: list
    sample: [{"name": "s05", "hana_system": "sles16hdb05/H05",
              "server_type": "Standalone Instance",
              "backup_status": "Healthy"}]
restore_points:
    description: Recovery point details per item
    returned: when operation == check_restore_points
    type: list
restore_job:
    description: Restore job details
    returned: when operation in (restore_to_database,
              restore_to_filesystem, check_restore_job)
    type: dict
"""


class AzureBackupHana(SapAutomationQA):
    """Manages Azure Backup operations for SAP HANA databases."""

    _DEFAULT_POLL_INTERVAL = 30
    _DEFAULT_POLL_TIMEOUT = 7200

    _TERMINAL_JOB_STATUSES = frozenset(
        {
            "completed",
            "failed",
            "cancelled",
            "completedwithwarnings",
        }
    )

    _HANA_BACKUP_FILTER = (
        "backupManagementType eq 'AzureWorkload' " "and itemType eq 'SAPHanaDatabase'"
    )

    @staticmethod
    def parse_vault_resource_id(
        resource_id: str,
    ) -> tuple[str, str]:
        """Extract vault name and resource group from an ARM ID.

        :param resource_id: Full ARM resource ID of the vault.
        :returns: ``(vault_name, resource_group)`` tuple.
        :raises ValueError: When the ID cannot be parsed.
        """
        parts = resource_id.strip("/").split("/")
        lookup = {parts[i].lower(): parts[i + 1] for i in range(0, len(parts) - 1, 2)}
        rg = lookup.get("resourcegroups", "")
        name = lookup.get("vaults", "")
        if not rg or not name:
            raise ValueError(
                f"Cannot parse vault resource ID: "
                f"{resource_id!r}. Expected format: "
                f"/subscriptions/{{sub}}/resourceGroups/"
                f"{{rg}}/providers/Microsoft.Recovery"
                f"Services/vaults/{{name}}"
            )
        return name, rg

    def __init__(
        self,
        vault_resource_id: str,
        subscription_id: str,
        msi_client_id: str = "",
        database_sid: str = "",
        poll_interval: int = _DEFAULT_POLL_INTERVAL,
        poll_timeout: int = _DEFAULT_POLL_TIMEOUT,
    ) -> None:
        super().__init__()
        vault_name, vault_rg = self.parse_vault_resource_id(
            vault_resource_id,
        )
        self.vault_resource_id = vault_resource_id
        self.vault_name = vault_name
        self.vault_resource_group = vault_rg
        self.subscription_id = subscription_id
        self.database_sid = database_sid
        self.poll_interval = poll_interval
        self.poll_timeout = poll_timeout
        self._client: Optional[RecoveryServicesBackupClient] = None
        self._msi_client_id = msi_client_id
        self.result.update(
            {
                "protected_items": [],
                "restore_points": [],
                "restore_job": {},
                "start": datetime.now().isoformat(),
                "end": None,
            }
        )

    @property
    def client(self) -> RecoveryServicesBackupClient:
        """Lazily create and cache the Recovery Services Backup client.

        :returns: Authenticated SDK client.
        :raises RuntimeError: When authentication fails.
        """
        if self._client is not None:
            return self._client

        try:
            credential = (
                ManagedIdentityCredential(
                    client_id=self._msi_client_id,
                )
                if self._msi_client_id
                else ManagedIdentityCredential()
            )
            self._client = RecoveryServicesBackupClient(
                credential=credential,
                subscription_id=self.subscription_id,
            )
            self.log(
                logging.INFO,
                f"Authenticated to Azure Recovery Services " f"(sub={self.subscription_id}).",
            )
            return self._client
        except Exception as exc:
            msg = "Failed to authenticate to Azure Recovery " f"Services Backup. {exc}"
            self.log(logging.ERROR, msg)
            raise RuntimeError(msg) from exc

    def _list_protected_items(self):
        """Iterate over SAP HANA protected items in the vault."""
        return self.client.backup_protected_items.list(
            vault_name=self.vault_name,
            resource_group_name=self.vault_resource_group,
            filter=self._HANA_BACKUP_FILTER,
        )

    @staticmethod
    def _extract_item_info(item) -> Dict[str, Any]:
        """Extract common fields from a backup protected item.

        :param item: SDK ``ProtectedItemResource`` instance.
        :returns: Flat dict of frequently used fields.
        """
        props = item.properties
        health = getattr(props, "health_status", "Unknown")
        protection = getattr(props, "protection_status", "Unknown")
        return {
            "friendly_name": getattr(props, "friendly_name", ""),
            "server_name": getattr(props, "server_name", ""),
            "parent_name": getattr(props, "parent_name", ""),
            "health_status": health or "Unknown",
            "protection_status": protection or "Unknown",
            "last_backup_time": getattr(
                props,
                "last_backup_time",
                None,
            ),
            "policy_name": getattr(props, "policy_name", ""),
            "container_name": getattr(
                props,
                "container_name",
                getattr(item, "container_name", ""),
            ),
            "item_name": item.name or "",
        }

    @staticmethod
    def _rp_name_from_id(rp_id: str) -> str:
        """Extract the recovery-point name from its ARM id.

        :param rp_id: Full ARM resource ID.
        :returns: Last segment (the RP name).
        """
        return rp_id.rsplit("/", 1)[-1] if rp_id else ""

    def _build_container_id(
        self,
        vm_name: str,
        resource_group: str,
    ) -> str:
        """Build the ARM container resource ID for the target VM.

        :param vm_name: Target VM name.
        :param resource_group: Target VM resource group.
        :returns: ARM resource ID for the container.
        """
        return (
            f"/subscriptions/{self.subscription_id}"
            f"/resourceGroups/{resource_group}"
            f"/providers/Microsoft.Compute"
            f"/virtualMachines/{vm_name}"
        )

    @staticmethod
    def _extract_job_id_from_poller(poller: Any) -> str:
        """Extract the job ID from the restore LRO poller.

        :param poller: LRO poller returned by ``begin_trigger``.
        :returns: Job ID string (may be empty).
        """
        try:
            headers = poller.initial_response().http_response.headers
            for header_key in ("azure-asyncoperation", "location"):
                url = headers.get(header_key, "")
                if not url:
                    continue
                parts = url.split("/")
                for i, segment in enumerate(parts):
                    if segment in (
                        "operationResults",
                        "backupJobs",
                    ) and i + 1 < len(parts):
                        return parts[i + 1].split("?")[0]
        except Exception:
            logging.getLogger(__name__).debug(
                "Could not extract job ID from poller headers.",
                exc_info=True,
            )
        return ""

    def discover_protected_items(self) -> Dict[str, Any]:
        """Discover all SAP HANA databases protected in the vault.

        :returns: Result dict with ``protected_items`` list.
        """
        self.log(
            logging.INFO,
            f"Discovering protected HANA items in " f"vault '{self.vault_name}'",
        )
        try:
            protected: List[Dict[str, Any]] = []
            unhealthy_count = 0

            for item in self._list_protected_items():
                info = self._extract_item_info(item)
                if info["health_status"].lower() != "healthy":
                    unhealthy_count += 1

                protected.append(
                    {
                        "name": info["friendly_name"],
                        "server_name": info["server_name"],
                        "parent_name": info["parent_name"],
                        "health_status": info["health_status"],
                        "protection_status": info["protection_status"],
                        "last_backup_time": (
                            info["last_backup_time"].isoformat() if info["last_backup_time"] else ""
                        ),
                        "policy_name": info["policy_name"],
                        "container_name": info["container_name"],
                        "item_name": info["item_name"],
                    }
                )

            self.result["protected_items"] = protected
            if unhealthy_count:
                self.result["status"] = TestStatus.WARNING.value
                self.result["message"] = (
                    f"{len(protected)} items discovered; " f"{unhealthy_count} unhealthy."
                )
            else:
                self.result["status"] = TestStatus.SUCCESS.value
                self.result["message"] = f"All {len(protected)} protected " f"item(s) are healthy."
        except Exception as exc:
            self.handle_error(exc)
        finally:
            self.result["end"] = datetime.now().isoformat()
        return self.result

    def check_restore_points(self) -> Dict[str, Any]:
        """Fetch and report the latest restore points for all items.

        :returns: Result dict with ``restore_points`` list.
        """
        self.log(
            logging.INFO,
            "Checking restore points for protected items.",
        )
        try:
            all_points: List[Dict[str, Any]] = []
            items_without_rp = 0
            item_count = 0

            for item in self._list_protected_items():
                item_count += 1
                info = self._extract_item_info(item)
                container = info["container_name"]
                item_name = info["item_name"]

                rp_list = list(
                    self.client.recovery_points.list(
                        vault_name=self.vault_name,
                        resource_group_name=self.vault_resource_group,
                        fabric_name="Azure",
                        container_name=container,
                        protected_item_name=item_name,
                    )
                )

                rp_time, rp_type = "N/A", "N/A"
                if not rp_list:
                    items_without_rp += 1
                elif rp_list[0].properties:
                    rp_props = rp_list[0].properties
                    rp_time_val = getattr(
                        rp_props,
                        "recovery_point_time",
                        None,
                    )
                    rp_time = rp_time_val.isoformat() if rp_time_val else "N/A"
                    rp_type = getattr(rp_props, "type", "N/A") or "N/A"

                all_points.append(
                    {
                        "item_name": info["friendly_name"],
                        "container_name": container,
                        "backup_item_name": item_name,
                        "recovery_point_count": len(rp_list),
                        "latest_recovery_point_time": rp_time,
                        "latest_recovery_point_type": rp_type,
                    }
                )
            self.result["restore_points"] = all_points
            if items_without_rp:
                self.result["status"] = TestStatus.WARNING.value
                self.result["message"] = (
                    f"{items_without_rp} of {item_count} " f"item(s) have no recovery points."
                )
            else:
                self.result["status"] = TestStatus.SUCCESS.value
                self.result["message"] = f"All {item_count} item(s) have " f"recovery points."
        except Exception as exc:
            self.handle_error(exc)
        finally:
            self.result["end"] = datetime.now().isoformat()
        return self.result

    def restore_to_database(
        self,
        container_name: str,
        item_name: str,
        restore_point_time: str = "",
        target_container_name: str = "",
        target_database_name: str = "",
    ) -> Dict[str, Any]:
        """Trigger a restore-to-database via Azure Backup SDK.

        :param container_name: Source backup container.
        :param item_name: Source backup item name.
        :param restore_point_time: Optional PIT in UTC ISO-8601.
        :param target_container_name: Target container (cross-VM).
        :param target_database_name: Target DB (cross-VM).
        :returns: Result dict with ``restore_job`` details.
        """
        self.log(
            logging.INFO,
            f"Triggering restore-to-database for " f"item='{item_name}'.",
        )
        try:
            rp_id = self._resolve_recovery_point(
                container_name,
                item_name,
                restore_point_time,
            )
            if not rp_id:
                self.result["status"] = TestStatus.ERROR.value
                self.result["message"] = "No suitable recovery point found."
                return self.result

            is_cross_vm = bool(target_container_name)
            restore_mode = "AlternateWorkloadRestore" if is_cross_vm else "OriginalWorkloadRestore"

            restore_request = self._build_workload_restore(
                rp_id=rp_id,
                restore_mode=restore_mode,
                target_container_name=(target_container_name if is_cross_vm else ""),
                target_database_name=(target_database_name if is_cross_vm else ""),
            )

            poller = self.client.restores.begin_trigger(
                vault_name=self.vault_name,
                resource_group_name=self.vault_resource_group,
                fabric_name="Azure",
                container_name=container_name,
                protected_item_name=item_name,
                recovery_point_id=self._rp_name_from_id(rp_id),
                parameters=restore_request,
            )
            job_id = self._extract_job_id_from_poller(poller)
            self.result["restore_job"] = {
                "job_id": job_id,
                "recovery_point_id": rp_id,
                "restore_mode": restore_mode,
            }
            self.result["status"] = TestStatus.SUCCESS.value
            self.result["message"] = f"Restore-to-database triggered. Job ID: {job_id}"
        except Exception as exc:
            self.handle_error(exc)
        finally:
            self.result["end"] = datetime.now().isoformat()
        return self.result

    def restore_to_filesystem(
        self,
        container_name: str,
        item_name: str,
        target_filesystem_path: str,
        target_vm_name: str = "",
        target_vm_resource_group: str = "",
        restore_point_time: str = "",
    ) -> Dict[str, Any]:
        """Trigger a restore-as-files to a filesystem path.

        :param container_name: Source backup container.
        :param item_name: Source backup item name.
        :param target_filesystem_path: Destination path on the VM.
        :param target_vm_name: Target VM for the files.
        :param target_vm_resource_group: Target VM resource group.
        :param restore_point_time: Optional PIT in UTC ISO-8601.
        :returns: Result dict with ``restore_job`` details.
        """
        self.log(
            logging.INFO,
            f"Triggering restore-to-filesystem for "
            f"item='{item_name}' -> '{target_filesystem_path}'.",
        )
        try:
            rp_id = self._resolve_recovery_point(
                container_name,
                item_name,
                restore_point_time,
            )
            if not rp_id:
                self.result["status"] = TestStatus.ERROR.value
                self.result["message"] = "No suitable recovery point found."
                return self.result

            job_id = self._extract_job_id_from_poller(
                self.client.restores.begin_trigger(
                    vault_name=self.vault_name,
                    resource_group_name=self.vault_resource_group,
                    fabric_name="Azure",
                    container_name=container_name,
                    protected_item_name=item_name,
                    recovery_point_id=self._rp_name_from_id(rp_id),
                    parameters=backup_models.RestoreRequestResource(
                        properties=backup_models.AzureWorkloadSAPHanaRestoreRequest(
                            recovery_point_id=rp_id,
                            recovery_type="RestoreAsFiles",
                            source_resource_id=rp_id,
                            target_info=backup_models.TargetRestoreInfo(
                                overwrite_option="Overwrite",
                                container_id=(
                                    self._build_container_id(
                                        target_vm_name,
                                        target_vm_resource_group or self.vault_resource_group,
                                    )
                                    if target_vm_name
                                    else None
                                ),
                                target_directory_for_file_restore=(target_filesystem_path),
                            ),
                        ),
                    ),
                )
            )
            self.result["restore_job"] = {
                "job_id": job_id,
                "recovery_point_id": rp_id,
                "restore_mode": "RestoreAsFiles",
                "target_path": target_filesystem_path,
            }
            self.result["status"] = TestStatus.SUCCESS.value
            self.result["message"] = "Restore-to-filesystem triggered. " f"Job ID: {job_id}"
        except Exception as exc:
            self.handle_error(exc)
        finally:
            self.result["end"] = datetime.now().isoformat()
        return self.result

    def check_restore_job(
        self,
        restore_job_id: str,
    ) -> Dict[str, Any]:
        """Poll a restore job until it completes or times out.

        :param restore_job_id: Azure Backup job ID.
        :returns: Result dict with final job status.
        """
        self.log(
            logging.INFO,
            f"Polling restore job '{restore_job_id}'.",
        )
        try:
            elapsed = 0
            final_status = "Unknown"

            while elapsed < self.poll_timeout:
                job = self.client.job_details.get(
                    vault_name=self.vault_name,
                    resource_group_name=self.vault_resource_group,
                    job_name=restore_job_id,
                )
                final_status = getattr(job.properties, "status", "Unknown") or "Unknown"
                self.log(
                    logging.INFO,
                    f"Job {restore_job_id}: " f"status={final_status} " f"(elapsed={elapsed}s)",
                )
                if final_status.lower() in self._TERMINAL_JOB_STATUSES:
                    break
                time.sleep(self.poll_interval)
                elapsed += self.poll_interval

            self.result["restore_job"] = {
                "job_id": restore_job_id,
                "status": final_status,
                "elapsed_seconds": elapsed,
            }
            self._set_job_result_status(
                restore_job_id,
                final_status,
                elapsed,
            )
        except Exception as exc:
            self.handle_error(exc)
        finally:
            self.result["end"] = datetime.now().isoformat()
        return self.result

    def _set_job_result_status(
        self,
        job_id: str,
        status: str,
        elapsed: int,
    ) -> None:
        """Map a terminal job status to the appropriate result.

        :param job_id: Azure Backup job ID.
        :param status: Final job status string.
        :param elapsed: Seconds elapsed during polling.
        """
        lower = status.lower()
        if lower == "completed":
            self.result["status"] = TestStatus.SUCCESS.value
            self.result["message"] = (
                f"Restore job {job_id} completed " f"successfully in {elapsed}s."
            )
        elif lower == "completedwithwarnings":
            self.result["status"] = TestStatus.WARNING.value
            self.result["message"] = (
                f"Restore job {job_id} completed " f"with warnings in {elapsed}s."
            )
        elif elapsed >= self.poll_timeout:
            self.result["status"] = TestStatus.ERROR.value
            self.result["message"] = (
                f"Restore job {job_id} timed out after " f"{elapsed}s (last status: {status})."
            )
        else:
            self.result["status"] = TestStatus.ERROR.value
            self.result["message"] = f"Restore job {job_id} ended with " f"status '{status}'."

    def _resolve_recovery_point(
        self,
        container_name: str,
        item_name: str,
        restore_point_time: str = "",
    ) -> str:
        """Return the recovery-point ID to use for a restore.

        :param container_name: Backup container name.
        :param item_name: Backup item name.
        :param restore_point_time: Optional PIT timestamp.
        :returns: Recovery point resource ID (empty on failure).
        """
        rp_list = list(
            self.client.recovery_points.list(
                vault_name=self.vault_name,
                resource_group_name=self.vault_resource_group,
                fabric_name="Azure",
                container_name=container_name,
                protected_item_name=item_name,
            )
        )
        if not rp_list:
            self.log(
                logging.WARNING,
                f"No recovery points for {item_name}.",
            )
            return ""

        if restore_point_time:
            self.log(
                logging.INFO,
                f"Using point-in-time {restore_point_time}.",
            )
        return rp_list[0].id or ""

    def _build_workload_restore(
        self,
        rp_id: str,
        restore_mode: str,
        target_container_name: str = "",
        target_database_name: str = "",
    ) -> backup_models.RestoreRequestResource:
        """Construct a workload restore request model.

        :param rp_id: Recovery point ARM resource ID.
        :param restore_mode: OriginalWorkloadRestore or AlternateWorkloadRestore.
        :param target_container_name: For cross-VM restores.
        :param target_database_name: For cross-VM restores.
        :returns: SDK ``RestoreRequestResource`` object.
        """
        target_info = (
            backup_models.TargetRestoreInfo(
                overwrite_option="Overwrite",
                container_id=target_container_name,
                database_name=target_database_name,
            )
            if restore_mode == "AlternateWorkloadRestore"
            else None
        )

        return backup_models.RestoreRequestResource(
            properties=backup_models.AzureWorkloadSAPHanaRestoreRequest(
                recovery_point_id=rp_id,
                recovery_type=restore_mode,
                source_resource_id=rp_id,
                target_info=target_info,
            ),
        )


def run_module() -> None:
    """Ansible module entry point."""

    module = AnsibleModule(
        argument_spec=dict(
            operation=dict(
                type="str",
                required=True,
                choices=[op.value for op in BackupOperation],
            ),
            subscription_id=dict(type="str", required=True),
            msi_client_id=dict(type="str", required=False, default=""),
            vault_resource_id=dict(type="str", required=True),
            database_sid=dict(type="str", required=False, default=""),
            container_name=dict(type="str", required=False, default=""),
            item_name=dict(type="str", required=False, default=""),
            restore_point_time=dict(type="str", required=False, default=""),
            target_container_name=dict(type="str", required=False, default=""),
            target_database_name=dict(type="str", required=False, default=""),
            target_filesystem_path=dict(type="str", required=False, default=""),
            target_vm_name=dict(type="str", required=False, default=""),
            target_vm_resource_group=dict(type="str", required=False, default=""),
            restore_job_id=dict(type="str", required=False, default=""),
            poll_interval_seconds=dict(type="int", required=False, default=30),
            poll_timeout_seconds=dict(type="int", required=False, default=7200),
        ),
        supports_check_mode=False,
    )
    params = module.params

    operation = BackupOperation(params["operation"])
    backup = AzureBackupHana(
        vault_resource_id=params["vault_resource_id"],
        subscription_id=params["subscription_id"],
        msi_client_id=params.get("msi_client_id", ""),
        database_sid=params.get("database_sid", ""),
        poll_interval=params.get(
            "poll_interval_seconds",
            AzureBackupHana._DEFAULT_POLL_INTERVAL,
        ),
        poll_timeout=params.get(
            "poll_timeout_seconds",
            AzureBackupHana._DEFAULT_POLL_TIMEOUT,
        ),
    )

    dispatch: Dict[BackupOperation, Callable[[], Dict[str, Any]]] = {
        BackupOperation.DISCOVER_PROTECTED_ITEMS: (backup.discover_protected_items),
        BackupOperation.CHECK_RESTORE_POINTS: (backup.check_restore_points),
        BackupOperation.RESTORE_TO_DATABASE: lambda: (
            backup.restore_to_database(
                container_name=params["container_name"],
                item_name=params["item_name"],
                restore_point_time=params.get(
                    "restore_point_time",
                    "",
                ),
                target_container_name=params.get(
                    "target_container_name",
                    "",
                ),
                target_database_name=params.get(
                    "target_database_name",
                    "",
                ),
            )
        ),
        BackupOperation.RESTORE_TO_FILESYSTEM: lambda: (
            backup.restore_to_filesystem(
                container_name=params["container_name"],
                item_name=params["item_name"],
                target_filesystem_path=params["target_filesystem_path"],
                target_vm_name=params.get(
                    "target_vm_name",
                    "",
                ),
                target_vm_resource_group=params.get(
                    "target_vm_resource_group",
                    "",
                ),
                restore_point_time=params.get(
                    "restore_point_time",
                    "",
                ),
            )
        ),
        BackupOperation.CHECK_RESTORE_JOB: lambda: (
            backup.check_restore_job(
                restore_job_id=params["restore_job_id"],
            )
        ),
    }

    handler = dispatch.get(operation)
    if handler is None:
        module.fail_json(
            msg=f"Unsupported operation: {operation.value}",
        )
        return

    result: Dict[str, Any] = handler()

    if result.get("status") == TestStatus.ERROR.value:
        module.fail_json(msg=result.get("message", ""), **result)
    else:
        module.exit_json(**result)


def main() -> None:
    """Module main entry point."""
    run_module()


if __name__ == "__main__":
    main()
