# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Collectors for data collection in SAP Automation QA
"""
import json
from abc import ABC, abstractmethod
import logging
import re
import shlex
import ipaddress
from typing import Any

try:
    from ansible.module_utils.sap_automation_qa import SapAutomationQA
    from ansible.module_utils.commands import DANGEROUS_COMMANDS
except ImportError:
    from src.module_utils.sap_automation_qa import SapAutomationQA
    from src.module_utils.commands import DANGEROUS_COMMANDS


class Collector(ABC):
    """
    Base class for data collection
    """

    def __init__(self, parent: SapAutomationQA):
        """
        Initialize with parent module for logging

        :param parent: Parent module with logging capability
        :type parent: SapAutomationQA
        """
        self.parent = parent

    @abstractmethod
    def collect(self, check, context) -> Any:
        """
        Collect data for validation

        :param check: Check object
        :type check: Check
        :param context: Context object
        :type context: Context
        """
        raise NotImplementedError("Subclasses must implement this method.")

    def sanitize_command(self, command: str) -> str:
        """
        Sanitize command to prevent injection attacks

        :param command: Raw command string
        :type command: str
        :return: Sanitized command or None if dangerous
        :rtype: str
        :raises ValueError: If command contains dangerous patterns
        """

        for pattern in DANGEROUS_COMMANDS:
            if re.search(pattern, command, re.IGNORECASE):
                self.parent.log(logging.ERROR, f"Dangerous command pattern detected: {pattern}")
                raise ValueError(f"Command contains potentially dangerous pattern: {pattern}")
        if len(command) > 1000:
            self.parent.log(logging.ERROR, f"Command too long: {len(command)} chars")
            raise ValueError("Command exceeds maximum length of 1000 characters")

        return command

    def substitute_context_vars(self, command: str, context: dict) -> str:
        """
        Substitute context variables in the command string.

        :param command: Command string with placeholders
        :type command: str
        :param context: Context variables to substitute
        :type context: dict
        :return: Command string with substituted values
        :rtype: str
        """
        self.parent.log(logging.INFO, f"Substituting context variables in command {command}")
        for key, value in context.items():
            placeholder = "{{ CONTEXT." + key + " }}"
            if placeholder in command:
                self.parent.log(
                    logging.INFO,
                    f"Substituting {placeholder} with {value} in command: {command}",
                )
                command = command.replace(placeholder, str(value))
        return command


class CommandCollector(Collector):
    """Collects data by executing shell commands"""

    def collect(self, check, context) -> str:
        """
        Execute a command and return the output.

        :param check: _Description of the check to be performed_
        :type check: Check
        :param context: Context variables to substitute in the command
        :type context: Dict[str, Any]
        :return: The output of the command
        :rtype: str
        """
        try:
            command = check.collector_args.get("command", "")
            user = check.collector_args.get("user", "")
            if not command:
                return "ERROR: No command specified"
            try:
                command = self.sanitize_command(command)
            except ValueError as e:
                self.parent.log(logging.ERROR, f"Command sanitization failed: {e}")
                return f"ERROR: Command sanitization failed: {e}"
            command = self.substitute_context_vars(command, context)
            try:
                command = self.sanitize_command(command)
            except ValueError as e:
                self.parent.log(
                    logging.ERROR, f"Command sanitization failed after substitution: {e}"
                )
                return f"ERROR: Command sanitization failed after substitution: {e}"

            check.command = command
            if user and user != "root":
                if not re.match(r"^[a-zA-Z0-9_-]+$", user):
                    self.parent.log(logging.ERROR, f"Invalid user parameter: {user}")
                    return f"ERROR: Invalid user parameter: {user}"
                command = f"sudo -u {shlex.quote(user)} {command}"

            return self.parent.execute_command_subprocess(
                command, shell_command=check.collector_args.get("shell", True)
            ).strip()
        except Exception as ex:
            self.parent.handle_error(ex)
            return f"ERROR: Command execution failed: {str(ex)}"


class AzureDataParser(Collector):
    """
    Parses data from Azure resources
    """

    def __init__(self, parent: SapAutomationQA):
        super().__init__(parent)

    def parse_context_vars(self, context: dict) -> dict:
        """
        Parse context variables to extract Azure-specific parameters.

        :param context: Context object containing variables
        :type context: Dict[str, Any]
        :return: Parsed context with Azure parameters
        :rtype: Dict[str, Any]
        """
        return {}

    def collect(self, check, context) -> Any:
        """
        Collect and parse Azure resource data

        This method delegates to azure_resource_collector module to get raw data,
        then parses it according to the check requirements.
        """
        try:
            resource_type = check.collector_args.get("resource_type", "")
            filesystem_data = context.get("filesystems", [])
            disks_metadata = context.get("azure_disks_metadata", {})

            if resource_type == "disks":
                mount_point = check.collector_args.get("mount_point", "")
                property = check.collector_args.get("property", "")

            return "ERROR: Unsupported resource type"

        except Exception as ex:
            self.parent.handle_error(ex)
            return f"ERROR: Azure data collection failed: {str(ex)}"


class FileSystemCollector(Collector):
    """
    Collects filesystem information - mimics PowerShell CollectFileSystems function
    """

    def __init__(self, parent: SapAutomationQA):
        super().__init__(parent)

    def _parse_filesystem_data(
        self,
        findmnt_output,
        df_output,
        lvm_volume,
        lvm_group,
        azure_disk_data,
        anf_storage_data,
        afs_storage_data,
    ):
        """Parse filesystem data like PowerShell script does"""
        filesystems = []
        findmnt_data = {}
        df_data = {}
        df_lines = [line.strip() for line in df_output.split("\n") if line.strip()]
        for line in df_lines[1:]:
            parts = line.split()
            if len(parts) >= 6:
                mountpoint = parts[5]
                df_data[mountpoint] = {
                    "filesystem": parts[0],
                    "size": parts[1],
                    "used": parts[2],
                    "free": parts[3],
                    "used_percent": parts[4],
                }

        for line in [line.strip() for line in findmnt_output.split("\n") if line.strip()]:
            parts = line.split()
            if len(parts) >= 4:
                target = parts[0]
                findmnt_data[target] = {"source": parts[1], "fstype": parts[2], "options": parts[3]}
        for mountpoint, df_info in df_data.items():
            findmnt_info = findmnt_data.get(mountpoint, {})
            vg_name, stripe_size = "", ""
            for vgname, prop in lvm_volume.items():
                if prop.get("dm_path") == df_info["filesystem"]:
                    vg_name = vgname
                    stripe_size = prop.get("stripe_size", "")
                    break
            filesystem_entry = {
                "target": mountpoint,
                "source": df_info["filesystem"],
                "fstype": findmnt_info.get("fstype", ""),
                "options": findmnt_info.get("options", ""),
                "size": df_info["size"],
                "free": df_info["free"],
                "used": df_info["used"],
                "used_percent": df_info["used_percent"],
                "vg": vg_name,
                "stripe_size": stripe_size,
                "max_mbps": "",
                "max_iops": "",
            }

            if filesystem_entry["fstype"] == "nfs" or filesystem_entry["fstype"] == "nfs4":
                nfs_address = filesystem_entry["source"].split(":")[0]
                for nfs_share in anf_storage_data + afs_storage_data:
                    if nfs_share.get("NFSAddress", "") == nfs_address:
                        filesystem_entry["max_mbps"] = nfs_share.get("throughput_mibps", 0)
                        filesystem_entry["max_iops"] = nfs_share.get("iops", 0)
                        break
            else:
                if df_info.get("filesystem", "").startswith("/dev/sed") or df_info.get(
                    "filesystem", ""
                ).startswith("/dev/nvme0n"):
                    for disk_data in azure_disk_data:
                        if disk_data.get("name", "") == filesystem_entry["source"]:
                            filesystem_entry["max_mbps"] = disk_data.get("mbps", 0)
                            filesystem_entry["max_iops"] = disk_data.get("iops", 0)
                    filesystem_entry["max_iops"] = 4
                else:
                    for name, prop in lvm_group.items():
                        if name == filesystem_entry["vg"]:
                            filesystem_entry["max_mbps"] = prop.get("total_mbps", 0)
                            filesystem_entry["max_iops"] = prop.get("total_iops", 0)
                            break

            filesystems.append(filesystem_entry)

        return filesystems

    def collect_lvm_volumes(self):
        """
        Collect LVM volume information.
        """
        log_volume_result = {}
        lvm_group_result = {}
        try:
            lvm_volumes = json.loads(
                self.parent.execute_command_subprocess(
                    "/sbin/lvm fullreport --reportformat json",
                    shell_command=True,
                ).strip()
            )
            for i in lvm_volumes.get("report", []):
                vol_group = i.get("vg", {})

                # Update lvm group
                lvm_group_result[vol_group.get("vg_name")] = {
                    "name": vol_group.get("vg_name"),
                    "disks": vol_group.get("pv_count", []),
                    "logical_volumes": vol_group.get("lv_count", []),
                    "total_size": vol_group.get("vg_size"),
                    "total_iops": 0,
                    "total_mbps": 0,
                }

                # Update lvm volume
                if vol_group.get("vg_name") != "rootvg":
                    for lv in i.get("lv", []):
                        log_volume_result[vol_group.get("vg_name")] = {
                            "name": lv.get("lv_name"),
                            "vg_name": vol_group.get("vg_name"),
                            "path": lv.get("lv_path"),
                            "dm_path": lv.get("lv_dm_path"),
                            "layout": lv.get("lv_layout"),
                            "size": lv.get("lv_size"),
                            "stripe_size": vol_group.get("seg").get("stripesize"),
                            "stripes": vol_group.get("seg").get("stripes"),
                        }

        except Exception as ex:
            return f"ERROR: LVM volume collection failed: {str(ex)}"
        return log_volume_result, lvm_group_result

    def collect(self, check, context) -> Any:
        """
        Collect filesystem information exactly like PowerShell CollectFileSystems

        :param check: Check object
        :type check: Check
        :param context: Context object
        :type context: Dict[str, Any]
        :return: Filesystem information
        :rtype: Dict[str, Any]
        """
        try:
            lvm_volumes, lvm_groups = self.collect_lvm_volumes()
            findmnt_output = self.parent.execute_command_subprocess(
                "findmnt -r -n -o TARGET,SOURCE,FSTYPE,OPTIONS", shell_command=True
            ).strip()
            df_output = self.parent.execute_command_subprocess("df -BG", shell_command=True).strip()

            filesystems = self._parse_filesystem_data(
                findmnt_output,
                df_output,
                lvm_volumes,
                lvm_groups,
                azure_disk_data=context.get("azure_disks_metadata", {}),
                anf_storage_data=context.get("anf_storage_metadata", {}),
                afs_storage_data=context.get("afs_storage_metadata", {}),
            )
            azure_disk_data = context.get("azure_disks_metadata", {})

            return {
                "filesystems": filesystems,
                "lvm_volumes": lvm_volumes,
                "lvm_groups": lvm_groups,
            }

        except Exception as ex:
            self.parent.handle_error(ex)
            return {"ERROR: Filesystem data collection failed": str(ex)}
