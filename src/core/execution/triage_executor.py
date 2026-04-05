# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Triage executor: SSH-based evidence collection orchestrator.

Manages the lifecycle of a ``TriageSession`` — validates commands against
the allow-list, delegates collection to ``EvidenceCollector``, writes
artifacts to the session's artifact directory, and advances the session
state machine.

Does NOT reuse ``ExecutorProtocol`` (which is Ansible-shaped). Defines
its own ``TriageExecutorProtocol`` as specified in the design doc.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Protocol, runtime_checkable

from src.core.execution.command_allow_list import CommandAllowList
from src.core.execution.evidence_collector import (
    EvidenceCollector,
    EvidenceDefinition,
)
from src.core.models.evidence import EvidenceArtifact
from src.core.models.triage import TriageSession

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class TriageExecutorProtocol(Protocol):
    """Interface for triage evidence collection.

    Separate from ``ExecutorProtocol`` which is Ansible-shaped.
    """

    def collect(
        self,
        session: TriageSession,
        evidence_defs: list[EvidenceDefinition],
    ) -> list[EvidenceArtifact]:
        """Collect evidence for a triage session.

        :param session: The active triage session.
        :param evidence_defs: What evidence to collect.
        :returns: List of collected artifacts.
        """
        ...


# ---------------------------------------------------------------------------
# Artifact persistence
# ---------------------------------------------------------------------------


class ArtifactWriter:
    """Writes ``EvidenceArtifact`` objects to a directory as JSON files.

    :param base_dir: Root directory for artifact storage.
    """

    def __init__(self, base_dir: Path) -> None:
        self._base_dir = base_dir

    def write(self, session_id: str, artifact: EvidenceArtifact) -> Path:
        """Write a single artifact to disk.

        :param session_id: Session that owns this artifact.
        :param artifact: The artifact to persist.
        :returns: Path to the written file.
        """
        session_dir = self._base_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        file_path = session_dir / f"{artifact.evidence_id}.json"
        file_path.write_text(
            json.dumps(artifact.to_dict(), indent=2, default=str),
            encoding="utf-8",
        )
        return file_path

    def write_all(self, session_id: str, artifacts: list[EvidenceArtifact]) -> list[Path]:
        """Write multiple artifacts to disk.

        :param session_id: Session that owns these artifacts.
        :param artifacts: Artifacts to persist.
        :returns: Paths to all written files.
        """
        return [self.write(session_id, a) for a in artifacts]

    def read(self, session_id: str, evidence_id: str) -> Optional[dict]:
        """Read an artifact from disk.

        :param session_id: Session the artifact belongs to.
        :param evidence_id: Artifact identifier.
        :returns: Parsed artifact dict, or None if not found.
        """
        file_path = self._base_dir / session_id / f"{evidence_id}.json"
        if not file_path.exists():
            return None
        return json.loads(file_path.read_text(encoding="utf-8"))

    def list_artifacts(self, session_id: str) -> list[str]:
        """List all artifact IDs for a session.

        :param session_id: Session to list artifacts for.
        :returns: List of evidence IDs.
        """
        session_dir = self._base_dir / session_id
        if not session_dir.exists():
            return []
        return [p.stem for p in session_dir.glob("*.json")]


# ---------------------------------------------------------------------------
# TriageExecutor
# ---------------------------------------------------------------------------


class TriageExecutor:
    """SSH-based triage evidence collection executor.

    Orchestrates evidence collection for a ``TriageSession``:
    1. Validates the session state (must be PENDING).
    2. Transitions session to COLLECTING.
    3. Delegates to ``EvidenceCollector`` for actual collection.
    4. Writes artifacts to disk via ``ArtifactWriter``.
    5. Transitions session to ANALYZING.

    Handles partial failures gracefully — individual collection failures
    do not abort the session.

    :param collector: The evidence collector with registered strategies.
    :param artifact_writer: Writes artifacts to disk.
    """

    def __init__(
        self,
        collector: EvidenceCollector,
        artifact_writer: ArtifactWriter,
    ) -> None:
        self._collector = collector
        self._artifact_writer = artifact_writer

    @property
    def collector(self) -> EvidenceCollector:
        """The underlying evidence collector."""
        return self._collector

    @property
    def artifact_writer(self) -> ArtifactWriter:
        """The artifact persistence writer."""
        return self._artifact_writer

    def collect(
        self,
        session: TriageSession,
        evidence_defs: list[EvidenceDefinition],
    ) -> list[EvidenceArtifact]:
        """Collect evidence for a triage session.

        Advances the session state machine through COLLECTING → ANALYZING.
        Failed individual collections are captured as FAILED artifacts,
        not raised as exceptions.

        :param session: The triage session (must be in PENDING state).
        :param evidence_defs: Evidence definitions to collect.
        :returns: All collected artifacts (including failures).
        :raises ValueError: If no evidence definitions provided.
        """
        if not evidence_defs:
            raise ValueError("No evidence definitions provided")

        session_id = str(session.id)

        session.start_collection()
        logger.info(
            "Triage session %s: collecting %d evidence items",
            session_id,
            len(evidence_defs),
        )

        artifacts = self._collector.collect_all(evidence_defs)

        self._artifact_writer.write_all(session_id, artifacts)

        session.complete_collection(artifacts)

        successful = sum(1 for a in artifacts if a.is_usable)
        failed = len(artifacts) - successful
        logger.info(
            "Triage session %s: collected %d/%d (%d failed)",
            session_id,
            successful,
            len(artifacts),
            failed,
        )

        return artifacts
