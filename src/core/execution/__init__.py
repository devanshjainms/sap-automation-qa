# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Execution layer for running tests and triage evidence collection."""

from src.core.execution.executor import ExecutorProtocol, AnsibleExecutor
from src.core.execution.worker import JobWorker
from src.core.execution.ssh_provider import SshCredentialProvider
from src.core.models.ssh import AuthType, SshCredential
from src.core.execution.exceptions import CredentialProvisionError
from src.core.execution.exceptions import (
    ExecutionError,
    WorkspaceLockError,
    JobNotFoundError,
)
from src.core.execution.command_allow_list import AllowedCommand, CommandAllowList
from src.core.execution.evidence_collector import (
    CollectorStrategy,
    EvidenceCollector,
    EvidenceDefinition,
)
from src.core.execution.triage_executor import (
    ArtifactWriter,
    TriageExecutor,
    TriageExecutorProtocol,
)

__all__ = [
    "ExecutorProtocol",
    "AnsibleExecutor",
    "JobWorker",
    "SshCredentialProvider",
    "SshCredential",
    "CredentialProvisionError",
    "AuthType",
    "ExecutionError",
    "WorkspaceLockError",
    "JobNotFoundError",
    "AllowedCommand",
    "CommandAllowList",
    "CollectorStrategy",
    "EvidenceCollector",
    "EvidenceDefinition",
    "ArtifactWriter",
    "TriageExecutor",
    "TriageExecutorProtocol",
]
