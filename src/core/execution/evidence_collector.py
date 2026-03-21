# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Evidence collector: strategy-based evidence collection for triage.

Delegates to typed collector strategies (SSH, Azure API, local file, IMDS)
based on ``CollectorType``. Each strategy returns an ``EvidenceArtifact``.
Supports TTL-based caching to avoid redundant collection during a session.
"""

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Protocol, runtime_checkable
from uuid import uuid4

from src.core.execution.command_allow_list import CommandAllowList
from src.core.models.evidence import (
    CollectionStatus,
    CollectorType,
    EvidenceArtifact,
    EvidenceType,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Evidence definition — what to collect
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EvidenceDefinition:
    """Describes a single piece of evidence to collect.

    :param definition_id: Unique identifier for this evidence definition.
    :param evidence_type: What kind of evidence this produces.
    :param collector_type: Which collection strategy to use.
    :param host: Target host (hostname or IP).
    :param command: Command to execute (for SSH/local collectors).
    :param description: Human-readable purpose of this evidence.
    :param timeout_seconds: Max seconds for collection.
    :param metadata: Extra context passed through to the artifact.
    """

    definition_id: str
    evidence_type: EvidenceType
    collector_type: CollectorType
    host: str = ""
    command: str = ""
    description: str = ""
    timeout_seconds: int = 30
    metadata: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Collector protocol — strategy interface
# ---------------------------------------------------------------------------


@runtime_checkable
class CollectorStrategy(Protocol):
    """Protocol for a single evidence collection strategy.

    Each implementation handles one ``CollectorType`` (SSH, Azure API, etc.).
    """

    def collect(self, definition: EvidenceDefinition) -> EvidenceArtifact:
        """Collect a single piece of evidence.

        :param definition: What to collect.
        :returns: The collected artifact (may have FAILED/TIMEOUT status).
        """
        ...


# ---------------------------------------------------------------------------
# Cache entry
# ---------------------------------------------------------------------------


@dataclass
class _CacheEntry:
    """Cached evidence artifact with expiry timestamp."""

    artifact: EvidenceArtifact
    expires_at: float


# ---------------------------------------------------------------------------
# EvidenceCollector — orchestrates collection across strategies
# ---------------------------------------------------------------------------


class EvidenceCollector:
    """Orchestrates evidence collection across multiple strategies.

    Uses the **Strategy pattern** — each ``CollectorType`` maps to a
    ``CollectorStrategy`` implementation. Continues collecting remaining
    evidence after individual failures (partial-failure tolerance).

    :param allow_list: Command allow-list for security validation.
    :param cache_ttl_seconds: TTL for cached artifacts (0 to disable).
    """

    def __init__(
        self,
        allow_list: CommandAllowList,
        cache_ttl_seconds: int = 300,
    ) -> None:
        self._allow_list = allow_list
        self._strategies: dict[CollectorType, CollectorStrategy] = {}
        self._cache: dict[str, _CacheEntry] = {}
        self._cache_ttl = cache_ttl_seconds

    @property
    def allow_list(self) -> CommandAllowList:
        """The command allow-list used for validation."""
        return self._allow_list

    def register_strategy(self, collector_type: CollectorType, strategy: CollectorStrategy) -> None:
        """Register a collection strategy for a given collector type.

        :param collector_type: The type this strategy handles.
        :param strategy: The strategy implementation.
        """
        self._strategies[collector_type] = strategy

    def collect_all(self, definitions: list[EvidenceDefinition]) -> list[EvidenceArtifact]:
        """Collect evidence for all definitions, tolerating partial failures.

        :param definitions: List of evidence to collect.
        :returns: List of artifacts (one per definition, FAILED on error).
        """
        artifacts: list[EvidenceArtifact] = []
        for definition in definitions:
            artifact = self.collect_one(definition)
            artifacts.append(artifact)
        return artifacts

    def collect_one(self, definition: EvidenceDefinition) -> EvidenceArtifact:
        """Collect a single piece of evidence with caching and validation.

        :param definition: What to collect.
        :returns: The evidence artifact.
        """
        # Check cache first
        cached = self._get_cached(definition.definition_id)
        if cached is not None:
            return cached

        # Validate command against allow-list for command-based collectors
        if self._requires_command_validation(definition):
            if not self._allow_list.is_allowed(definition.command):
                return self._make_rejected_artifact(definition)

        # Delegate to registered strategy
        artifact = self._execute_strategy(definition)

        # Cache successful results
        if artifact.is_usable:
            self._set_cached(definition.definition_id, artifact)

        return artifact

    def clear_cache(self) -> None:
        """Clear all cached evidence artifacts."""
        self._cache.clear()

    # -----------------------------------------------------------------------
    # Private helpers
    # -----------------------------------------------------------------------

    def _requires_command_validation(self, definition: EvidenceDefinition) -> bool:
        """Whether this definition needs command allow-list validation."""
        return definition.collector_type in (
            CollectorType.SSH,
            CollectorType.LOCAL_FILE,
        ) and bool(definition.command)

    def _execute_strategy(self, definition: EvidenceDefinition) -> EvidenceArtifact:
        """Delegate to the registered strategy, handling missing strategies."""
        strategy = self._strategies.get(definition.collector_type)
        if strategy is None:
            logger.warning(
                "No strategy registered for collector type: %s",
                definition.collector_type,
            )
            return self._make_error_artifact(
                definition,
                CollectionStatus.FAILED,
                f"No collector strategy for {definition.collector_type}",
            )

        try:
            return strategy.collect(definition)
        except TimeoutError:
            logger.warning(
                "Timeout collecting evidence %s on %s",
                definition.definition_id,
                definition.host,
            )
            return self._make_error_artifact(
                definition, CollectionStatus.TIMEOUT, "Collection timed out"
            )
        except ConnectionError:
            logger.warning(
                "Host unreachable for evidence %s: %s",
                definition.definition_id,
                definition.host,
            )
            return self._make_error_artifact(
                definition, CollectionStatus.UNREACHABLE, f"Host unreachable: {definition.host}"
            )
        except Exception as exc:
            logger.error(
                "Failed to collect evidence %s: %s",
                definition.definition_id,
                exc,
            )
            return self._make_error_artifact(definition, CollectionStatus.FAILED, str(exc))

    def _make_rejected_artifact(self, definition: EvidenceDefinition) -> EvidenceArtifact:
        """Create an artifact for a command that was rejected by the allow-list."""
        return EvidenceArtifact(
            evidence_id=f"evi-{uuid4().hex[:12]}",
            evidence_type=definition.evidence_type,
            collector_type=definition.collector_type,
            status=CollectionStatus.FAILED,
            host=definition.host,
            command=definition.command,
            content="",
            error=f"Command rejected by allow-list: {definition.command}",
            metadata={"definition_id": definition.definition_id, "rejected": True},
        )

    def _make_error_artifact(
        self,
        definition: EvidenceDefinition,
        status: CollectionStatus,
        error: str,
    ) -> EvidenceArtifact:
        """Create an artifact representing a failed collection attempt."""
        return EvidenceArtifact(
            evidence_id=f"evi-{uuid4().hex[:12]}",
            evidence_type=definition.evidence_type,
            collector_type=definition.collector_type,
            status=status,
            host=definition.host,
            command=definition.command,
            content="",
            error=error,
            metadata={"definition_id": definition.definition_id},
        )

    def _get_cached(self, definition_id: str) -> Optional[EvidenceArtifact]:
        """Return cached artifact if still valid, else None."""
        entry = self._cache.get(definition_id)
        if entry is None:
            return None
        if time.monotonic() > entry.expires_at:
            del self._cache[definition_id]
            return None
        return entry.artifact

    def _set_cached(self, definition_id: str, artifact: EvidenceArtifact) -> None:
        """Store an artifact in the cache with TTL."""
        if self._cache_ttl <= 0:
            return
        self._cache[definition_id] = _CacheEntry(
            artifact=artifact,
            expires_at=time.monotonic() + self._cache_ttl,
        )
