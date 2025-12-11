# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Semantic Kernel plugin for SSH connectivity to SAP VMs.

This plugin provides secure SSH access to SAP VMs for:
- Running diagnostic commands
- Tailing log files
- Checking service status
- Gathering system information

All commands are validated against a whitelist for safety.
"""

import json
import subprocess
from pathlib import Path
from typing import Annotated, Optional, Tuple

from semantic_kernel.functions import kernel_function

from src.agents.constants import (
    SSH_SAFE_COMMANDS,
    SSH_SAFE_COMMAND_PREFIXES,
    SSH_BLOCKED_PATTERNS,
    DEFAULT_SSH_USER,
    DEFAULT_SSH_TIMEOUT,
    DEFAULT_SSH_OPTIONS,
)
from src.agents.observability import get_logger
from src.agents.plugins.command_validator import validate_command_safe

logger = get_logger(__name__)


class SSHPlugin:
    """Semantic Kernel plugin for secure SSH connectivity to SAP VMs.

    This plugin provides controlled SSH access using keys retrieved
    from Azure Key Vault. All commands are validated for safety.
    """

    def __init__(
        self,
        default_ssh_user: str = DEFAULT_SSH_USER,
        ssh_timeout: int = DEFAULT_SSH_TIMEOUT,
        ssh_options: Optional[list[str]] = None,
    ) -> None:
        """Initialize SSHPlugin.

        :param default_ssh_user: Default SSH username for connections
        :type default_ssh_user: str
        :param ssh_timeout: Connection timeout in seconds
        :type ssh_timeout: int
        :param ssh_options: Additional SSH options
        :type ssh_options: Optional[list[str]]
        """
        self.default_ssh_user = default_ssh_user
        self.ssh_timeout = ssh_timeout
        self.ssh_options = ssh_options or list(DEFAULT_SSH_OPTIONS)
        logger.info(
            f"SSHPlugin initialized with default_user: {default_ssh_user}, "
            f"timeout: {ssh_timeout}s"
        )

    def _validate_command(self, command: str) -> Tuple[bool, str]:
        """Validate command against safety rules.

        :param command: Command to validate
        :type command: str
        :returns: Tuple of (is_valid, reason)
        :rtype: Tuple[bool, str]
        """
        command_lower = command.lower().strip()

        for pattern in SSH_BLOCKED_PATTERNS:
            if pattern.lower() in command_lower:
                return False, f"Command contains blocked pattern: '{pattern}'"
        if command.strip() in SSH_SAFE_COMMANDS:
            return True, "Command in safe list"
        for prefix in SSH_SAFE_COMMAND_PREFIXES:
            if command_lower.startswith(prefix.lower()):
                return True, f"Command starts with safe prefix: '{prefix}'"
        is_valid, reason = validate_command_safe(command)
        if is_valid:
            return True, reason

        return False, f"Command not in whitelist and failed validation: {reason}"

    def _build_ssh_command(
        self,
        host: str,
        command: str,
        key_path: str,
        user: Optional[str] = None,
        port: int = 22,
    ) -> list[str]:
        """Build SSH command array.

        :param host: Target hostname or IP
        :type host: str
        :param command: Remote command to execute
        :type command: str
        :param key_path: Path to SSH private key
        :type key_path: str
        :param user: SSH username (uses default if None)
        :type user: Optional[str]
        :param port: SSH port
        :type port: int
        :returns: SSH command as list of arguments
        :rtype: list[str]
        """
        ssh_user = user or self.default_ssh_user
        ssh_cmd = [
            "ssh",
            "-i",
            key_path,
            "-p",
            str(port),
            f"-o ConnectTimeout={self.ssh_timeout}",
        ]
        ssh_cmd.extend(self.ssh_options)
        ssh_cmd.append(f"{ssh_user}@{host}")
        ssh_cmd.append(command)
        return ssh_cmd

    @kernel_function(
        name="execute_remote_command",
        description="Execute a read-only diagnostic command on a remote SAP VM via SSH. "
        + "Commands are validated against a safety whitelist. Use this for system diagnostics, "
        + "log viewing, and cluster status checks.",
    )
    def execute_remote_command(
        self,
        host: Annotated[str, "Target hostname or IP address of the SAP VM"],
        command: Annotated[str, "The diagnostic command to execute (must be read-only/safe)"],
        key_path: Annotated[str, "Path to the SSH private key file"],
        user: Annotated[str, "SSH username (default: azureadm)"] = "",
        port: Annotated[int, "SSH port (default: 22)"] = 22,
    ) -> Annotated[str, "JSON string with command output or error"]:
        """Execute a validated command on a remote host.

        :param host: Target hostname or IP
        :type host: str
        :param command: Command to execute
        :type command: str
        :param key_path: Path to SSH private key
        :type key_path: str
        :param user: SSH username
        :type user: str
        :param port: SSH port
        :type port: int
        :returns: JSON string with output or error
        :rtype: str
        """
        logger.info(f"SSH command request to {host}: {command[:50]}...")
        is_valid, reason = self._validate_command(command)
        if not is_valid:
            error_msg = f"Command rejected: {reason}"
            logger.warning(error_msg)
            return json.dumps(
                {
                    "error": error_msg,
                    "host": host,
                    "command": command,
                    "allowed": False,
                }
            )
        if not Path(key_path).exists():
            error_msg = f"SSH key file not found: {key_path}"
            logger.error(error_msg)
            return json.dumps({"error": error_msg, "host": host})
        ssh_user = user if user else None
        ssh_cmd = self._build_ssh_command(host, command, key_path, ssh_user, port)

        try:
            result = subprocess.run(
                ssh_cmd,
                capture_output=True,
                text=True,
                timeout=self.ssh_timeout + 10,
            )

            if result.returncode == 0:
                logger.info(f"SSH command succeeded on {host}")
                return json.dumps(
                    {
                        "host": host,
                        "command": command,
                        "stdout": result.stdout,
                        "stderr": result.stderr,
                        "exit_code": result.returncode,
                        "success": True,
                    }
                )
            else:
                logger.warning(f"SSH command failed on {host}: exit code {result.returncode}")
                return json.dumps(
                    {
                        "host": host,
                        "command": command,
                        "stdout": result.stdout,
                        "stderr": result.stderr,
                        "exit_code": result.returncode,
                        "success": False,
                    }
                )

        except subprocess.TimeoutExpired:
            error_msg = f"SSH command timed out after {self.ssh_timeout + 10}s"
            logger.error(error_msg)
            return json.dumps(
                {"error": error_msg, "host": host, "command": command, "timeout": True}
            )

        except Exception as e:
            error_msg = f"SSH execution failed: {str(e)}"
            logger.error(error_msg)
            return json.dumps({"error": error_msg, "host": host, "command": command})

    @kernel_function(
        name="check_host_connectivity",
        description="Test SSH connectivity to a host. Returns success if the host is "
        + "reachable via SSH.",
    )
    def check_host_connectivity(
        self,
        host: Annotated[str, "Target hostname or IP address"],
        key_path: Annotated[str, "Path to the SSH private key file"],
        user: Annotated[str, "SSH username (default: azureadm)"] = "",
        port: Annotated[int, "SSH port (default: 22)"] = 22,
    ) -> Annotated[str, "JSON string with connectivity status"]:
        """Check SSH connectivity to a host.

        :param host: Target hostname or IP
        :type host: str
        :param key_path: Path to SSH private key
        :type key_path: str
        :param user: SSH username
        :type user: str
        :param port: SSH port
        :type port: int
        :returns: JSON string with connectivity status
        :rtype: str
        """
        logger.info(f"Checking SSH connectivity to {host}")

        result = self.execute_remote_command(
            host=host,
            command="echo 'SSH_CONNECTIVITY_OK'",
            key_path=key_path,
            user=user,
            port=port,
        )

        result_dict = json.loads(result)

        if result_dict.get("success") and "SSH_CONNECTIVITY_OK" in result_dict.get("stdout", ""):
            return json.dumps(
                {
                    "host": host,
                    "reachable": True,
                    "message": "SSH connectivity successful",
                }
            )
        else:
            return json.dumps(
                {
                    "host": host,
                    "reachable": False,
                    "error": result_dict.get("error") or result_dict.get("stderr", "Unknown error"),
                }
            )

    @kernel_function(
        name="get_cluster_status",
        description="Get Pacemaker cluster status from a cluster node. Returns the output "
        + "of 'crm status' or 'pcs status' command.",
    )
    def get_cluster_status(
        self,
        host: Annotated[str, "Hostname or IP of a cluster node"],
        key_path: Annotated[str, "Path to the SSH private key file"],
        user: Annotated[str, "SSH username (default: azureadm)"] = "",
    ) -> Annotated[str, "JSON string with cluster status"]:
        """Get Pacemaker cluster status.

        :param host: Cluster node hostname or IP
        :type host: str
        :param key_path: Path to SSH private key
        :type key_path: str
        :param user: SSH username
        :type user: str
        :returns: JSON string with cluster status
        :rtype: str
        """
        logger.info(f"Getting cluster status from {host}")

        result = self.execute_remote_command(
            host=host,
            command="sudo crm status 2>/dev/null || sudo pcs status 2>/dev/null",
            key_path=key_path,
            user=user,
        )

        result_dict = json.loads(result)

        if result_dict.get("success"):
            return json.dumps(
                {
                    "host": host,
                    "cluster_status": result_dict.get("stdout", ""),
                    "success": True,
                }
            )
        else:
            return json.dumps(
                {
                    "host": host,
                    "error": result_dict.get("error") or result_dict.get("stderr", ""),
                    "success": False,
                }
            )

    @kernel_function(
        name="tail_log_file",
        description="Tail a log file on a remote SAP VM. Only allowed for logs in "
        + "/var/log/ or /usr/sap/ directories.",
    )
    def tail_log_file(
        self,
        host: Annotated[str, "Target hostname or IP address"],
        log_path: Annotated[str, "Full path to the log file (must be in /var/log/ or /usr/sap/)"],
        key_path: Annotated[str, "Path to the SSH private key file"],
        lines: Annotated[int, "Number of lines to retrieve (default: 100)"] = 100,
        user: Annotated[str, "SSH username (default: azureadm)"] = "",
    ) -> Annotated[str, "JSON string with log content or error"]:
        """Tail a log file on a remote host.

        :param host: Target hostname or IP
        :type host: str
        :param log_path: Path to log file
        :type log_path: str
        :param key_path: Path to SSH private key
        :type key_path: str
        :param lines: Number of lines
        :type lines: int
        :param user: SSH username
        :type user: str
        :returns: JSON string with log content or error
        :rtype: str
        """
        logger.info(f"Tailing {lines} lines from {log_path} on {host}")
        if not log_path.startswith(("/var/log/", "/usr/sap/")):
            error_msg = "Log path must be in /var/log/ or /usr/sap/ directory"
            logger.warning(error_msg)
            return json.dumps(
                {"error": error_msg, "host": host, "log_path": log_path, "allowed": False}
            )

        safe_lines = min(lines, 1000)

        result = self.execute_remote_command(
            host=host,
            command=f"tail -n {safe_lines} {log_path}",
            key_path=key_path,
            user=user,
        )

        result_dict = json.loads(result)

        if result_dict.get("success"):
            return json.dumps(
                {
                    "host": host,
                    "log_path": log_path,
                    "lines_requested": safe_lines,
                    "content": result_dict.get("stdout", ""),
                    "success": True,
                }
            )
        else:
            return json.dumps(
                {
                    "host": host,
                    "log_path": log_path,
                    "error": result_dict.get("error") or result_dict.get("stderr", ""),
                    "success": False,
                }
            )

    @kernel_function(
        name="get_sap_process_status",
        description="Get SAP process status using sapcontrol. Returns the list of "
        + "SAP processes and their states.",
    )
    def get_sap_process_status(
        self,
        host: Annotated[str, "Hostname or IP of the SAP server"],
        key_path: Annotated[str, "Path to the SSH private key file"],
        instance_number: Annotated[str, "SAP instance number (e.g., '00', '01')"],
        user: Annotated[str, "SSH username (default: azureadm)"] = "",
    ) -> Annotated[str, "JSON string with SAP process status"]:
        """Get SAP process status via sapcontrol.

        :param host: SAP server hostname or IP
        :type host: str
        :param key_path: Path to SSH private key
        :type key_path: str
        :param instance_number: SAP instance number
        :type instance_number: str
        :param user: SSH username
        :type user: str
        :returns: JSON string with process status
        :rtype: str
        """
        logger.info(f"Getting SAP process status from {host} (instance {instance_number})")

        command = f"sapcontrol -nr {instance_number} -function GetProcessList"

        result = self.execute_remote_command(
            host=host,
            command=command,
            key_path=key_path,
            user=user,
        )

        result_dict = json.loads(result)

        if result_dict.get("success"):
            return json.dumps(
                {
                    "host": host,
                    "instance_number": instance_number,
                    "process_list": result_dict.get("stdout", ""),
                    "success": True,
                }
            )
        else:
            return json.dumps(
                {
                    "host": host,
                    "instance_number": instance_number,
                    "error": result_dict.get("error") or result_dict.get("stderr", ""),
                    "success": False,
                }
            )

    @kernel_function(
        name="get_hana_system_replication_status",
        description="Get HANA System Replication status from a HANA node. "
        + "Returns the SR state and mode.",
    )
    def get_hana_system_replication_status(
        self,
        host: Annotated[str, "Hostname or IP of the HANA server"],
        key_path: Annotated[str, "Path to the SSH private key file"],
        sid: Annotated[str, "SAP System ID (e.g., 'HDB', 'S4H')"],
        user: Annotated[str, "SSH username (default: azureadm)"] = "",
    ) -> Annotated[str, "JSON string with HANA SR status"]:
        """Get HANA System Replication status.

        :param host: HANA server hostname or IP
        :type host: str
        :param key_path: Path to SSH private key
        :type key_path: str
        :param sid: SAP System ID
        :type sid: str
        :param user: SSH username
        :type user: str
        :returns: JSON string with SR status
        :rtype: str
        """
        logger.info(f"Getting HANA SR status from {host} (SID: {sid})")

        sid_lower = sid.lower()
        command = f"sudo su - {sid_lower}adm -c 'hdbnsutil -sr_state'"

        result = self.execute_remote_command(
            host=host,
            command=command,
            key_path=key_path,
            user=user,
        )

        result_dict = json.loads(result)

        if result_dict.get("success"):
            return json.dumps(
                {
                    "host": host,
                    "sid": sid,
                    "sr_state": result_dict.get("stdout", ""),
                    "success": True,
                }
            )
        else:
            return json.dumps(
                {
                    "host": host,
                    "sid": sid,
                    "error": result_dict.get("error") or result_dict.get("stderr", ""),
                    "success": False,
                }
            )
