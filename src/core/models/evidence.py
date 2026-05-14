# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Evidence artifact models for triage evidence collection."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Optional


class EvidenceType(StrEnum):
    """Type of evidence artifact collected during triage."""

    COMMAND_OUTPUT = "command_output"
    AZURE_METADATA = "azure_metadata"
    CIB_XML = "cib_xml"
    LOG_EXCERPT = "log_excerpt"
    LOG_OUTPUT = "log_output"
    SAP_PROCESS_LIST = "sap_process_list"


class CollectorType(StrEnum):
    """Source that produced the evidence artifact."""

    SSH = "ssh"
    AZURE_API = "azure_api"
    AZURE_MCP = "azure_mcp"
    LOCAL_FILE = "local_file"
    IMDS = "imds"


class CollectionStatus(StrEnum):
    """Outcome of an individual evidence collection attempt.
    Every artifact carries its collection status so the analyzer
    knows which evidence is trustworthy vs degraded.
    """

    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    UNREACHABLE = "unreachable"


@dataclass(frozen=True)
class EvidenceArtifact:
    """A single piece of evidence collected during triage.
    Immutable value object. Once created, an artifact is never modified.

    :param evidence_id: Unique identifier for this artifact.
    :param evidence_type: Category of evidence.
    :param collector_type: How this evidence was collected.
    :param status: Outcome of the collection attempt.
    :param host: Target host the evidence was collected from.
    :param command: Command or API call used to collect evidence.
    :param content: Raw output content (empty string on failure).
    :param collected_at: Timestamp of collection.
    :param duration_ms: Wall-clock time of collection in milliseconds.
    :param error: Error message if status is not SUCCESS.
    :param metadata: Additional context (rule_id, definition_id, etc.).
    """

    evidence_id: str
    evidence_type: EvidenceType
    collector_type: CollectorType
    status: CollectionStatus
    host: str
    command: str = ""
    content: str = ""
    collected_at: datetime = field(default_factory=datetime.utcnow)
    duration_ms: int = 0
    error: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_usable(self) -> bool:
        """Whether the analyzer should trust this artifact's content."""
        return self.status == CollectionStatus.SUCCESS

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dictionary for JSON storage.

        :returns: Dictionary representation of the artifact.
        :rtype: dict[str, Any]
        """
        return {
            "evidence_id": self.evidence_id,
            "evidence_type": self.evidence_type.value,
            "collector_type": self.collector_type.value,
            "status": self.status.value,
            "host": self.host,
            "command": self.command,
            "content": self.content,
            "collected_at": self.collected_at.isoformat(),
            "duration_ms": self.duration_ms,
            "error": self.error,
            "metadata": self.metadata,
        }
