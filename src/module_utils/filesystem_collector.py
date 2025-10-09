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
    from ansible.module_utils.collector import Collector
except ImportError:
    from src.module_utils.sap_automation_qa import SapAutomationQA
    from src.module_utils.collector import Collector


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
        vg_to_disk_names=None,
    ):
        """
        Parse filesystem data like PowerShell script does.

        :param vg_to_disk_names: Pre-computed mapping of VG names to Azure disk names
        :type vg_to_disk_names: Dict[str, List[str]]
        """
        if vg_to_disk_names is None:
            vg_to_disk_names = {}
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
                    disk_names = vg_to_disk_names.get(vg_name, [])

                    if disk_names:
                        filesystem_entry["azure_disk_names"] = disk_names
                        self.parent.log(
                            logging.INFO,
                            f"Mapped VG {vg_name} to {len(disk_names)} Azure disks: {disk_names}",
                        )
                    else:
                        self.parent.log(
                            logging.WARNING,
                            f"No disk mapping found for VG {vg_name}. Ensure device-to-lun mapping is available.",
                        )

            filesystems.append(filesystem_entry)

        return filesystems

    def _map_vg_to_disk_names(self, lvm_fullreport, imds_metadata, device_lun_map):
        """
        Map LVM volume groups to Azure disk names using direct device→lun→diskname correlation.

        Chain: PV device (/dev/sdc) → LUN (0) → disk name (via IMDS) → Azure disk

        :param lvm_fullreport: LVM fullreport JSON with PV information
        :param imds_metadata: IMDS metadata with lun-to-diskname mappings
        :param device_lun_map: Mapping of device names to LUN numbers (e.g., {"sdc": "0"})
        :return: Dict mapping VG names to lists of Azure disk names
        :rtype: Dict[str, List[str]]
        """
        vg_to_disk_names = {}

        try:
            lun_to_diskname = {}
            for disk_info in imds_metadata:
                lun = disk_info.get("lun")
                name = disk_info.get("name")
                if lun is not None and name:
                    lun_to_diskname[str(lun)] = name

            reports = lvm_fullreport.get("report", [])
            self.parent.log(
                logging.INFO,
                f"Found {len(reports)} LVM reports",
            )

            for report in reports:
                pvs = report.get("pv", [])
                vgs = report.get("vg", [])

                vg_names = [vg.get("vg_name") for vg in vgs if vg.get("vg_name")]
                if not vg_names:
                    self.parent.log(
                        logging.WARNING,
                        f"Report has PVs but no VG names found, skipping",
                    )
                    continue
                vg_name = vg_names[0]

                for pv in pvs:
                    pv_name = pv.get("pv_name")

                    if not pv_name:
                        self.parent.log(
                            logging.INFO,
                            f"Skipping PV with missing pv_name",
                        )
                        continue
                    device_name = pv_name.split("/")[-1] if "/" in pv_name else pv_name
                    lun = device_lun_map.get(device_name)
                    if lun is None:
                        self.parent.log(
                            logging.WARNING,
                            f"No LUN mapping found for device {device_name} (PV: {pv_name})",
                        )
                        continue
                    disk_name = lun_to_diskname.get(str(lun))
                    if not disk_name:
                        self.parent.log(
                            logging.WARNING,
                            f"No IMDS entry for LUN {lun} (device: {device_name})",
                        )
                        continue
                    if vg_name not in vg_to_disk_names:
                        vg_to_disk_names[vg_name] = []
                    vg_to_disk_names[vg_name].append(disk_name)

        except Exception as ex:
            self.parent.log(
                logging.ERROR,
                f"Failed to map VG to disk names: {ex}",
            )

        return vg_to_disk_names

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
                    pv_count = vol_group.get("pv_count", 0)
                    try:
                        pv_count = int(pv_count) if pv_count else 0
                    except (ValueError, TypeError):
                        pv_count = 0

                    lvm_group_result[vg_name] = {
                        "name": vg_name,
                        "disks": pv_count,
                        "logical_volumes": vol_group.get("lv_count", 0),
                        "total_size": vol_group.get("vg_size"),
                        "total_iops": 0,
                        "total_mbps": 0,
                    }

                logical_volumes = lvm_volume.get("lv", [])
                segments = lvm_volume.get("seg", [])

                for lv in logical_volumes:
                    lv_name = lv.get("lv_name")
                    vg_name = ""
                    if lv.get("lv_full_name") and "/" in lv.get("lv_full_name", ""):
                        vg_name = lv.get("lv_full_name", "").split("/")[0]
                    elif lv.get("vg_name"):
                        vg_name = lv.get("vg_name")

                    stripe_size, stripes = "", ""
                    lv_uuid = lv.get("lv_uuid")
                    for segment in segments:
                        if segment.get("lv_uuid") == lv_uuid:
                            stripes = segment.get("stripes", "")
                            stripe_size = segment.get("stripe_size", "")
                            break

                    if vg_name and vg_name != "rootvg":
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
            lvm_fullreport = context.get("lvm_fullreport", "")
            if not lvm_fullreport or lvm_fullreport == {} or not lvm_fullreport.get("report"):
                self.parent.log(
                    logging.ERROR,
                    f"lvm_fullreport is empty or invalid: {lvm_fullreport}. "
                    f"LVM data collection may have failed. VG-to-disk mapping will not work.",
                )

            lvm_volumes, lvm_groups = self.collect_lvm_volumes(lvm_fullreport)

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
            imds_metadata = self._parse_metadata(
                context.get("imds_disks_metadata", []), "IMDS disk"
            )

            device_lun_map = context.get("device_lun_map", {})
            vg_to_disk_names = {}
            if device_lun_map and imds_metadata:
                vg_to_disk_names = self._map_vg_to_disk_names(
                    lvm_fullreport, imds_metadata, device_lun_map
                )
            elif imds_metadata:
                self.parent.log(
                    logging.WARNING,
                    "device_lun_map not found in context. LVM disk mapping may be incomplete.",
                )

            self.parent.log(
                logging.INFO,
                f"findmnt_output: {findmnt_output}\n"
                f"df_output: {df_output}\n"
                f"Azure disk data type: {type(azure_disk_data)}, Count: {len(azure_disk_data)}\n"
                f"IMDS metadata type: {type(imds_metadata)}, Count: {len(imds_metadata)}\n"
                f"ANF storage data type: {type(anf_storage_data)}, Count: {len(anf_storage_data)}\n"
                f"AFS storage data type: {type(afs_storage_data)}, Count: {len(afs_storage_data)}\n"
                f"VG→disk_names mapping: {vg_to_disk_names}",
            )

            filesystems = self._parse_filesystem_data(
                findmnt_output,
                df_output,
                lvm_volumes,
                lvm_groups,
                azure_disk_data=azure_disk_data,
                anf_storage_data=anf_storage_data,
                afs_storage_data=afs_storage_data,
                vg_to_disk_names=vg_to_disk_names,
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
