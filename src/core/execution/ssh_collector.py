# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""SSH-based evidence collector strategy.

Uses ``subprocess`` to execute commands on remote hosts via SSH.
Credentials (key path, auth type) are passed through
``EvidenceDefinition.metadata`` — provisioned upstream by
``SshCredentialProvider``.
"""

import logging
import subprocess
from datetime import datetime, timezone

from src.core.execution.evidence_collector import (
    EvidenceDefinition,
)
from src.core.models.evidence import (
    CollectionStatus,
    CollectorType,
    EvidenceArtifact,
)

logger = logging.getLogger(__name__)

# SSH options to avoid interactive prompts and host-key issues.
_SSH_OPTS = [
    "-o",
    "StrictHostKeyChecking=no",
    "-o",
    "UserKnownHostsFile=/dev/null",
    "-o",
    "BatchMode=yes",
    "-o",
    "ConnectTimeout=10",
    "-o",
    "LogLevel=ERROR",
]


class SshCollectorStrategy:
    """Collect evidence by executing commands over SSH.

    Reads ``private_key_path`` and ``auth_type`` from
    ``definition.metadata``.  Falls back to the default SSH
    agent when no key is provided.

    Implements :class:`CollectorStrategy` protocol.
    """

    def collect(self, definition: EvidenceDefinition) -> EvidenceArtifact:
        """Execute a command on a remote host via SSH.

        :param definition: What to collect (host, command, metadata).
        :returns: Artifact with stdout/stderr or failure status.
        """
        host = definition.host
        command = definition.command
        timeout = definition.timeout_seconds
        key_path = definition.metadata.get("private_key_path", "")
        ssh_user = definition.metadata.get("ssh_user", "")
        become_user = definition.metadata.get("become_user", "")

        if not host or not command:
            return self._fail(
                definition,
                "Missing host or command in evidence definition.",
            )

        remote_cmd = f"sudo -n {command}" if become_user else command
        ssh_cmd = self._build_ssh_command(host, remote_cmd, key_path, ssh_user)

        logger.info(
            "SSH evidence collection: host=%s cmd=%s timeout=%ds",
            host,
            command[:80],
            timeout,
        )

        try:
            result = subprocess.run(
                ssh_cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            status = CollectionStatus.SUCCESS if result.returncode == 0 else CollectionStatus.FAILED
            return EvidenceArtifact(
                evidence_id=definition.definition_id,
                evidence_type=definition.evidence_type,
                collector_type=CollectorType.SSH,
                status=status,
                host=host,
                command=command,
                collected_at=datetime.now(timezone.utc),
                content=result.stdout,
                error=result.stderr if result.returncode != 0 else None,
                metadata={
                    **definition.metadata,
                    "return_code": result.returncode,
                },
            )
        except subprocess.TimeoutExpired:
            logger.warning(
                "SSH command timed out after %ds: %s on %s",
                timeout,
                command[:80],
                host,
            )
            return self._fail(
                definition,
                f"SSH command timed out after {timeout}s",
                CollectionStatus.TIMEOUT,
            )
        except OSError as exc:
            logger.error("SSH execution failed: %s", exc)
            return self._fail(definition, f"SSH execution error: {exc}")

    @staticmethod
    def _build_ssh_command(
        host: str,
        command: str,
        key_path: str,
        ssh_user: str = "",
    ) -> list[str]:
        """Build the subprocess command list for SSH.

        :param host: Target hostname or IP.
        :param command: Remote command to execute.
        :param key_path: Path to private key (empty for agent auth).
        :param ssh_user: Remote user (empty to use system default).
        :returns: Command list for ``subprocess.run``.
        """
        cmd = ["ssh"] + _SSH_OPTS
        if key_path:
            cmd.extend(["-i", key_path])
        target = f"{ssh_user}@{host}" if ssh_user else host
        cmd.extend([target, command])
        return cmd

    @staticmethod
    def _fail(
        definition: EvidenceDefinition,
        error: str,
        status: CollectionStatus = CollectionStatus.FAILED,
    ) -> EvidenceArtifact:
        """Create a failed artifact.

        :param definition: The original evidence definition.
        :param error: Error message.
        :param status: Failure status.
        :returns: Failed artifact.
        """
        return EvidenceArtifact(
            evidence_id=definition.definition_id,
            evidence_type=definition.evidence_type,
            collector_type=CollectorType.SSH,
            status=status,
            host=definition.host,
            command=definition.command,
            collected_at=datetime.now(timezone.utc),
            content="",
            error=error,
            metadata=definition.metadata,
        )
