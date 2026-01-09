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
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Annotated, Optional, Tuple

from semantic_kernel.functions import kernel_function

from src.agents.constants import (
    SSH_SAFE_COMMANDS,
    SSH_SAFE_COMMAND_PREFIXES,
    SSH_BLOCKED_PATTERNS,
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
        ssh_timeout: int = DEFAULT_SSH_TIMEOUT,
        ssh_options: Optional[list[str]] = None,
    ) -> None:
        """Initialize SSHPlugin.

        :param ssh_timeout: Connection timeout in seconds
        :type ssh_timeout: int
        :param ssh_options: Additional SSH options
        :type ssh_options: Optional[list[str]]
        """
        self.ssh_timeout = ssh_timeout
        self.ssh_options = ssh_options or list(DEFAULT_SSH_OPTIONS)
        self._converted_keys: dict[str, str] = {}  # Cache: ppk_path -> openssh_path
        logger.info(f"SSHPlugin initialized with timeout: {ssh_timeout}s")

    def _validate_command(self, command: str) -> Tuple[bool, str]:
        """Validate command against safety rules.

        :param command: Command to validate
        :type command: str
        :returns: Tuple of (is_valid, reason)
        :rtype: Tuple[bool, str]
        """
        command_lower = command.lower().strip()

        for pattern in SSH_BLOCKED_PATTERNS:
            pattern_lower = pattern.lower().strip()
            if not pattern_lower:
                continue

            is_regex_like = bool(re.search(r"[\\\\\[\]().?*+^$|]", pattern_lower))
            if is_regex_like:
                regex_pattern = pattern_lower
            else:
                if pattern_lower[0].isalnum():
                    regex_pattern = r"(?:^|\\s)" + re.escape(pattern_lower)
                else:
                    regex_pattern = re.escape(pattern_lower)

            if re.search(regex_pattern, command_lower):
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
        user: str,
        port: int = 22,
    ) -> list[str]:
        """Build SSH command array.

        :param host: Target hostname or IP
        :type host: str
        :param command: Remote command to execute
        :type command: str
        :param key_path: Path to SSH private key
        :type key_path: str
        :param user: SSH username (from hosts.yaml)
        :type user: str
        :param port: SSH port
        :type port: int
        :returns: SSH command as list of arguments
        :rtype: list[str]
        """
        ssh_cmd = [
            "ssh",
            "-i",
            key_path,
            "-p",
            str(port),
            f"-o ConnectTimeout={self.ssh_timeout}",
        ]
        ssh_cmd.extend(self.ssh_options)
        ssh_cmd.append(f"{user}@{host}")
        ssh_cmd.append(command)
        return ssh_cmd

    @kernel_function(
        name="execute_remote_command",
        description="Execute a read-only diagnostic command on a remote SAP VM via SSH. "
        + "Commands are validated against a safety whitelist. Use this for system diagnostics,"
        "troubleshooting, log viewing, and cluster status checks, finding relevant information "
        + "that may be necessary for other operations. ",
    )
    def execute_remote_command(
        self,
        host: Annotated[str, "Target hostname or IP address of the SAP VM"],
        command: Annotated[str, "The diagnostic command to execute (must be read-only/safe)"],
        key_path: Annotated[str, "Path to the SSH private key file"],
        user: Annotated[str, "SSH username from hosts.yaml (ansible_user field)"],
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
        ssh_cmd = self._build_ssh_command(host, command, key_path, user, port)

        try:
            logger.info(f"SSH command: {' '.join(ssh_cmd)}")
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
                logger.warning(f"SSH stderr: {result.stderr}")
                return json.dumps(
                    {
                        "host": host,
                        "command": command,
                        "stdout": result.stdout,
                        "stderr": result.stderr,
                        "exit_code": result.returncode,
                        "success": False,
                        "ssh_command_used": " ".join(ssh_cmd),  # Help debug
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
        description="Check if a remote host is reachable via SSH using the provided key.",
    )
    def check_host_connectivity(
        self,
        host: Annotated[str, "Target hostname or IP address"],
        key_path: Annotated[str, "Path to the SSH private key file"],
        user: Annotated[str, "SSH username from hosts.yaml (ansible_user field)"],
        port: Annotated[int, "SSH port (default: 22)"] = 22,
    ) -> Annotated[str, "JSON string with connectivity status"]:
        """Check SSH connectivity."""
        return self.execute_remote_command(host, "exit", key_path, user, port)
