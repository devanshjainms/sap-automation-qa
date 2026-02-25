# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
SSH remote executor for E2E validation.
"""

from __future__ import annotations

import logging
import subprocess
import time
from dataclasses import dataclass
from typing import Optional

from e2e.src.azure_deployer import DeployedVM

logger = logging.getLogger(__name__)

_SSH_OPTIONS = [
    "-o",
    "StrictHostKeyChecking=no",
    "-o",
    "UserKnownHostsFile=/dev/null",
    "-o",
    "ConnectTimeout=30",
    "-o",
    "ServerAliveInterval=15",
    "-o",
    "ServerAliveCountMax=3",
    "-o",
    "LogLevel=ERROR",
]

_MAX_OUTPUT_CHARS = 500_000

@dataclass
class RemoteResult:
    """Result of a remote SSH command.

    :param return_code: Process exit code.
    :param stdout: Captured stdout (may be truncated).
    :param stderr: Captured stderr (may be truncated).
    :param duration_seconds: Wall-clock execution time.
    :param timed_out: Whether the command was killed by timeout.
    """

    return_code: int = -1
    stdout: str = ""
    stderr: str = ""
    duration_seconds: float = 0.0
    timed_out: bool = False


class RemoteExecutor:
    """Execute commands on a deployed VM over SSH.

    :param vm: Deployed VM connection details.
    """

    def __init__(self, vm: DeployedVM) -> None:
        self._vm = vm

    def wait_for_ssh(
        self,
        retries: int = 30,
        delay: int = 10,
    ) -> bool:
        """Block until SSH is reachable.

        :param retries: Max connection attempts.
        :param delay: Seconds between attempts.
        :returns: True if SSH became reachable.
        :rtype: bool
        """
        for attempt in range(1, retries + 1):
            result = self.run("echo ok", timeout=15)
            if result.return_code == 0:
                logger.info(
                    "SSH ready on %s (attempt %d)",
                    self._vm.private_ip,
                    attempt,
                )
                return True
            logger.debug(
                "SSH not ready on %s (attempt %d/%d)",
                self._vm.private_ip,
                attempt,
                retries,
            )
            time.sleep(delay)

        logger.error(
            "SSH never became ready on %s after %d " "attempts",
            self._vm.private_ip,
            retries,
        )
        return False

    def run(
        self,
        command: str,
        *,
        timeout: int = 600,
        cwd: Optional[str] = None,
    ) -> RemoteResult:
        """Execute a command over SSH on the remote VM.

        :param command: Shell command string to execute.
        :param timeout: Max seconds before killing the process.
        :param cwd: Optional working directory (prepended as ``cd``).
        :returns: Execution result.
        :rtype: RemoteResult
        """
        if cwd:
            command = f"cd {cwd} && {command}"

        ssh_cmd = [
            "sshpass",
            "-p",
            self._vm.admin_password,
            "ssh",
            *_SSH_OPTIONS,
            f"{self._vm.admin_username}@" f"{self._vm.private_ip}",
            command,
        ]

        logger.debug(
            "SSH [%s] %s",
            self._vm.private_ip,
            command[:120],
        )

        start = time.monotonic()
        timed_out = False

        try:
            proc = subprocess.run(
                ssh_cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return_code = proc.returncode
            stdout = proc.stdout[:_MAX_OUTPUT_CHARS]
            stderr = proc.stderr[:_MAX_OUTPUT_CHARS]
        except subprocess.TimeoutExpired:
            timed_out = True
            return_code = -1
            stdout = ""
            stderr = f"Command timed out after {timeout}s"
            logger.warning(
                "SSH command timed out on %s: %s",
                self._vm.private_ip,
                command[:80],
            )

        duration = time.monotonic() - start

        return RemoteResult(
            return_code=return_code,
            stdout=stdout,
            stderr=stderr,
            duration_seconds=duration,
            timed_out=timed_out,
        )
