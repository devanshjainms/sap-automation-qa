# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Generic Azure Resource Collector Module for SAP Automation QA

This module provides a generic interface for collecting Azure resource data
that can be used by configuration checks. It supports multiple resource types
and can run delegated to localhost where Azure CLI/SDK is available.
"""

from typing import Dict, Any
from ansible.module_utils.basic import AnsibleModule
from azure.identity import ManagedIdentityCredential
from azure.mgmt.compute import ComputeManagementClient
from azure.mgmt.network import NetworkManagementClient

try:
    from ansible.module_utils.collector import AzureDataCollector
except ImportError:
    from src.module_utils.collector import AzureDataCollector


class AzureResourceCollector(AzureDataCollector):
    """Generic Azure resource data collector"""

    def __init__(self, module_params: Dict[str, Any]):
        """
        Initialize Azure resource collector

        :param subscription_id: Azure subscription ID
        :param resource_group_name: Azure resource group name
        :param resource_name: Azure resource name
        :param msi_client_id: Azure Managed Identity client ID (optional)
        """
        self.subscription_id = module_params["subscription_id"]
        self.resource_group = module_params["resource_group"]
        self.resource_name = module_params.get("resource_name")
        self.resource_type = module_params["resource_type"]
        self.credential = (
            ManagedIdentityCredential()
            if module_params["msi_client_id"] is None
            else ManagedIdentityCredential(client_id=module_params["msi_client_id"])
        )
        self._clients = {
            "compute": ComputeManagementClient(self.credential, self.subscription_id),
            "network": NetworkManagementClient(self.credential, self.subscription_id),
        }

    def _extract_disk_properties(self, disk) -> Dict[str, Any]:
        """Extract relevant properties from Azure disk object"""
        return {
            "name": disk.name,
            "disk_size_gb": disk.disk_size_gb,
            "disk_state": disk.disk_state.value if disk.disk_state else None,
            "sku_name": disk.sku.name if disk.sku else None,
            "sku_tier": disk.sku.tier if disk.sku else None,
            "disk_iops_read_write": disk.disk_iops_read_write,
            "disk_mbps_read_write": disk.disk_m_bps_read_write,
            "disk_iops_read_only": getattr(disk, "disk_iops_read_only", None),
            "disk_mbps_read_only": getattr(disk, "disk_m_bps_read_only", None),
            "tier": getattr(disk, "tier", None),
            "creation_time": disk.time_created.isoformat() if disk.time_created else None,
            "zones": disk.zones,
            "location": disk.location,
            "tags": disk.tags or {},
        }

    def _collect_disk_info(self) -> Dict[str, Any]:
        """
        Collect disk performance and configuration information

        :param resource_group: Name of the resource group
        :param resource_name: Name of the virtual machine
        :return: Dictionary with disk information
        """
        try:
            vm = self._clients["compute"].virtual_machines.get(
                self.resource_group, self.resource_name
            )
            disks = {}
            if vm.storage_profile.os_disk.managed_disk:
                os_disk_name = vm.storage_profile.os_disk.name
                if os_disk_name:
                    disk = self._clients["compute"].disks.get(self.resource_group, os_disk_name)
                    disks[os_disk_name] = self._extract_disk_properties(disk)
            for data_disk in vm.storage_profile.data_disks:
                if data_disk.managed_disk:
                    disk_name = data_disk.name
                    if disk_name:
                        disk = self._clients["compute"].disks.get(self.resource_group, disk_name)
                        disks[disk_name] = self._extract_disk_properties(disk)

            return disks

        except Exception as ex:
            self.parent.handle_error(ex)
            return {}

    def _collect_network_info(self) -> Dict[str, Any]:
        """Collect network-related information"""
        return {}


def run_module():
    """Main module execution function"""
    module_args = dict(
        subscription_id=dict(type="str", required=True),
        resource_group=dict(type="str", required=True),
        resource_name=dict(type="str", required=False),
        resource_type=dict(
            type="str",
            required=False,
            default=["disks"],
            choices=["disks", "network"],
        ),
        msi_client_id=dict(type="str", required=False, default=""),
    )
    module = AnsibleModule(argument_spec=module_args, supports_check_mode=True)
    resource_name = module.params.get("resource_name")
    resource_type = module.params["resource_type"]
    try:
        collector = AzureResourceCollector(module.params)
        result = {}

        if resource_name and resource_type in ["disks", "network"]:
            method_name = "collect_" + resource_type + "_info"
            if hasattr(collector, method_name):
                method = getattr(collector, method_name)
                result = method()
        else:
            result = {"message": "VM name required for resource collection"}

        module.exit_json(changed=False, azure_resources=result)

    except Exception as e:
        module.fail_json(msg=f"Azure resource collection failed: {str(e)}")


if __name__ == "__main__":
    run_module()
