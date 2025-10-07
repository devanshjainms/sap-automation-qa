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

    def parse_disks_vars(self, filesystem_data, disks_metadata, mount_point, property) -> str:
        """
        Parse the required property for given mount point from filesystem data and disks metadata.

        For LVM striped volumes, this aggregates metrics across all underlying disks.
        For single disks, returns the metric for that disk.

        :param filesystem_data: Filesystem data collected from the system (enriched by FileSystemCollector)
        :type filesystem_data: List[Dict[str, Any]]
        :param disks_metadata: Metadata about Azure disks (can be list of dicts/list of JSON string)
        :type disks_metadata: Union[List[Dict[str, Any]], List[str]]
        :param mount_point: Mount point to look for
        :type mount_point: str
        :param property: Property to extract (e.g., mbps, iops, size)
        :type property: str
        :return: Aggregated property value or "N/A" if not found
        :rtype: str
        """
        value = "N/A"
        try:
            parsed_disks = []
            for disk in disks_metadata:
                if isinstance(disk, str):
                    try:
                        parsed_disks.append(json.loads(disk))
                    except json.JSONDecodeError:
                        self.parent.log(
                            logging.WARNING,
                            f"Failed to parse disk metadata JSON string: {disk[:100]}",
                        )
                        continue
                elif isinstance(disk, dict):
                    parsed_disks.append(disk)
                else:
                    self.parent.log(logging.WARNING, f"Unexpected disk metadata type: {type(disk)}")

            if not parsed_disks:
                self.parent.log(logging.WARNING, "No valid disk metadata found")
                return value

            fs_entry = None
            for fs in filesystem_data:
                if fs.get("target") == mount_point:
                    fs_entry = fs
                    break

            if not fs_entry:
                self.parent.log(
                    logging.WARNING, f"Mount point {mount_point} not found in filesystem data"
                )
                return value

            if "azure_disk_names" in fs_entry and fs_entry["azure_disk_names"]:
                total_value = 0
                matched_disks = 0

                for disk_name in fs_entry["azure_disk_names"]:
                    disk = next((d for d in parsed_disks if d.get("name") == disk_name), None)
                    if disk and property in disk:
                        disk_value = disk.get(property, 0)
                        try:
                            total_value += float(disk_value) if disk_value else 0
                            matched_disks += 1
                        except (ValueError, TypeError):
                            self.parent.log(
                                logging.WARNING,
                                f"Could not convert {property}={disk_value} to number for disk {disk_name}",
                            )

                if matched_disks > 0:
                    value = str(int(total_value))
                    self.parent.log(
                        logging.INFO,
                        f"Aggregated {property} for {mount_point}: {value} (from {matched_disks} disks)",
                    )
                else:
                    self.parent.log(
                        logging.WARNING,
                        f"No matching disks found for {mount_point} with property {property}",
                    )
            else:
                disk_name = fs_entry.get("source")
                disk = next((d for d in parsed_disks if d.get("name") == disk_name), None)
                if not disk:
                    device_name = disk_name.split("/")[-1] if "/" in disk_name else disk_name
                    disk = next((d for d in parsed_disks if device_name in d.get("name", "")), None)
                if disk and property in disk:
                    value = str(disk.get(property, "N/A"))
                    self.parent.log(
                        logging.INFO,
                        f"Found {property}={value} for {mount_point} from disk {disk.get('name')}",
                    )
                else:
                    self.parent.log(
                        logging.WARNING,
                        f"Property '{property}' not found for mount point '{mount_point}' (source: {disk_name})",
                    )

        except Exception as ex:
            self.parent.handle_error(ex)
            value = f"ERROR: Parsing failed: {str(ex)}"

        return value

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

            self.parent.log(logging.INFO, f"Context in the Azure collector context: {context}\n")

            if resource_type == "disks":
                mount_point = check.collector_args.get("mount_point", "")
                property = check.collector_args.get("property", "")
                return self.parse_disks_vars(filesystem_data, disks_metadata, mount_point, property)
            else:
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
            parts = line.split(maxsplit=3)
            if len(parts) >= 4:
                target = parts[0]
                findmnt_data[target] = {"source": parts[1], "fstype": parts[2], "options": parts[3]}
        for mountpoint, df_info in df_data.items():
            findmnt_info = findmnt_data.get(mountpoint, {})
            vg_name, stripe_size = "", ""
            filesystem_path = df_info["filesystem"]
            for lv_name, lv_prop in lvm_volume.items():
                if lv_prop.get("dm_path") == filesystem_path:
                    vg_name = lv_prop.get("vg_name", "")
                    stripe_size = lv_prop.get("stripe_size", "")
                    break

            filesystem_entry = {
                "target": mountpoint,
                "source": filesystem_path,
                "fstype": findmnt_info.get("fstype", ""),
                "options": findmnt_info.get("options", ""),
                "size": df_info["size"],
                "free": df_info["free"],
                "used": df_info["used"],
                "used_percent": df_info["used_percent"],
                "vg": vg_name,
                "stripe_size": stripe_size,
                "max_mbps": 0,
                "max_iops": 0,
            }

            if filesystem_entry["fstype"] in ["nfs", "nfs4"]:
                nfs_source = filesystem_entry["source"]
                if ":" in nfs_source:
                    nfs_address = nfs_source.split(":")[0]

                    for nfs_share in afs_storage_data:
                        share_address = nfs_share.get("NFSAddress", "")
                        if ":" in share_address and share_address.split(":")[0] == nfs_address:
                            filesystem_entry["max_mbps"] = nfs_share.get("ThroughputMibps", 0)
                            filesystem_entry["max_iops"] = nfs_share.get("IOPS", 0)
                            break
            else:
                if filesystem_path.startswith("/dev/sd") or filesystem_path.startswith("/dev/nvme"):
                    disk_name = (
                        filesystem_path.split("/")[-1]
                        if "/" in filesystem_path
                        else filesystem_path
                    )

                    for disk_data in azure_disk_data:
                        if disk_data.get("name", "").endswith(disk_name):
                            filesystem_entry["max_mbps"] = disk_data.get("mbps", 0)
                            filesystem_entry["max_iops"] = disk_data.get("iops", 0)
                            break
                elif filesystem_path.startswith("/dev/mapper/") and vg_name:
                    vg_info = lvm_group.get(vg_name, {})
                    filesystem_entry["max_mbps"] = vg_info.get("total_mbps", 0)
                    filesystem_entry["max_iops"] = vg_info.get("total_iops", 0)

                    pv_count = vg_info.get("disks", 0)
                    if pv_count > 0:
                        disk_groups = {}
                        for disk in azure_disk_data:
                            disk_size = disk.get("size", 0)
                            if disk_size not in disk_groups:
                                disk_groups[disk_size] = []
                            disk_groups[disk_size].append(disk.get("name"))
                        for size, disk_names in disk_groups.items():
                            if len(disk_names) == pv_count:
                                filesystem_entry["azure_disk_names"] = disk_names
                                self.parent.log(
                                    logging.INFO,
                                    f"Heuristically matched {pv_count} disks of size {size}GB to VG {vg_name}",
                                )
                                break

            filesystems.append(filesystem_entry)

        return filesystems

    def collect_lvm_volumes(self, lvm_fullreport):
        """
        Collect LVM volume information.

        :param lvm_fullreport: Pre-fetched LVM fullreport JSON string
        :return: Tuple of logical volumes and volume groups
        :rtype: Tuple[Dict[str, Any], Dict[str, Any]]
        """
        log_volume_result = {}
        lvm_group_result = {}
        try:
            lvm_volumes = lvm_fullreport
            for lvm_volume in lvm_volumes.get("report", []):
                vol_groups = lvm_volume.get("vg", [])
                for vol_group in vol_groups:
                    vg_name = vol_group.get("vg_name")
                    lvm_group_result[vg_name] = {
                        "name": vg_name,
                        "disks": vol_group.get("pv_count", 0),
                        "logical_volumes": vol_group.get("lv_count", 0),
                        "total_size": vol_group.get("vg_size"),
                        "total_iops": 0,
                        "total_mbps": 0,
                    }

                logical_volumes = lvm_volume.get("lv", [])
                segments = lvm_volume.get("seg", [])

                for lv in logical_volumes:
                    lv_name = lv.get("lv_name")
                    vg_name = (
                        lv.get("lv_full_name", "").split("/")[0]
                        if "/" in lv.get("lv_full_name", "")
                        else ""
                    )
                    stripe_size, stripes = "", ""
                    lv_uuid = lv.get("lv_uuid")
                    for segment in segments:
                        if segment.get("lv_uuid") == lv_uuid:
                            stripes = segment.get("stripes", "")
                            stripe_size = segment.get("stripe_size", "")
                            break

                    if vg_name != "rootvg":
                        log_volume_result[lv_name] = {
                            "name": lv_name,
                            "vg_name": vg_name,
                            "path": lv.get("lv_path"),
                            "dm_path": lv.get("lv_dm_path"),
                            "layout": lv.get("lv_layout"),
                            "size": lv.get("lv_size"),
                            "stripe_size": stripe_size,
                            "stripes": stripes,
                        }

        except Exception as ex:
            return f"ERROR: LVM volume collection failed: {str(ex)}"
        return log_volume_result, lvm_group_result

    def _parse_metadata(self, raw_data, data_type="metadata"):
        """
        Parse metadata that can be in various formats: dict, list, or JSON strings.

        :param raw_data: Raw metadata from context
        :param data_type: Type of data for logging purposes
        :return: List of dictionaries
        """
        parsed_data = []

        if not raw_data:
            return parsed_data

        if isinstance(raw_data, list):
            for item in raw_data:
                if isinstance(item, dict):
                    parsed_data.append(item)
                elif isinstance(item, str):
                    try:
                        parsed_data.append(json.loads(item))
                    except json.JSONDecodeError:
                        self.parent.log(
                            logging.WARNING,
                            f"Failed to parse {data_type} item: {item}",
                        )
        elif isinstance(raw_data, dict):
            parsed_data = [raw_data]
        elif isinstance(raw_data, str):
            try:
                parsed_data = json.loads(raw_data)
                if not isinstance(parsed_data, list):
                    parsed_data = [parsed_data]
            except json.JSONDecodeError:
                for line in raw_data.splitlines():
                    if line.strip():
                        try:
                            parsed_data.append(json.loads(line.strip()))
                        except json.JSONDecodeError:
                            self.parent.log(
                                logging.WARNING,
                                f"Failed to parse {data_type} line: {line.strip()}",
                            )

        return parsed_data

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
            lvm_volumes, lvm_groups = self.collect_lvm_volumes(
                lvm_fullreport=context.get("lvm_fullreport", "")
            )
            findmnt_output = context.get("mount_info", "")
            df_output = context.get("df_info", "")

            azure_disk_data = self._parse_metadata(
                context.get("azure_disks_metadata", []), "Azure disk"
            )
            afs_storage_data = self._parse_metadata(
                context.get("afs_storage_metadata", ""), "AFS storage"
            )
            anf_storage_data = self._parse_metadata(
                context.get("anf_storage_metadata", ""), "ANF storage"
            )

            self.parent.log(
                logging.INFO,
                f"findmnt_output: {findmnt_output}\n"
                f"df_output: {df_output}\n"
                f"Azure disk data type: {type(azure_disk_data)}, Count: {len(azure_disk_data)}\n"
                f"ANF storage data type: {type(anf_storage_data)}, Count: {len(anf_storage_data)}\n"
                f"AFS storage data type: {type(afs_storage_data)}, Count: {len(afs_storage_data)}",
            )

            filesystems = self._parse_filesystem_data(
                findmnt_output,
                df_output,
                lvm_volumes,
                lvm_groups,
                azure_disk_data=azure_disk_data,
                anf_storage_data=anf_storage_data,
                afs_storage_data=afs_storage_data,
            )

            self.parent.log(
                logging.INFO,
                f"Collected filesystems: {filesystems}\n"
                + f"Collected LVM volumes: {lvm_volumes}\n"
                + f"Collected LVM groups: {lvm_groups}",
            )

            return {
                "filesystems": filesystems,
                "lvm_volumes": lvm_volumes,
                "lvm_groups": lvm_groups,
            }

        except Exception as ex:
            self.parent.handle_error(ex)
            return {"ERROR: Filesystem data collection failed": str(ex)}
