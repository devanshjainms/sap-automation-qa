# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Pydantic models for the STAF platform."""

from src.core.models.job import Job, JobStatus, JobEvent, JobEventType
from src.core.models.schedule import Schedule
from src.core.models.ssh import AuthType, SshCredential
from src.core.models.telemetry import TelemetryConfig
from src.core.models.evidence import (
    EvidenceArtifact,
    EvidenceType,
    CollectorType,
    CollectionStatus,
)
from src.core.models.validators import ValidatorType
from src.core.models.system import SystemProperties, Applicability
from src.core.models.knowledge import (
    Rule,
    Playbook,
    Reference,
    LearnedPattern,
    ValidatorSpec,
)
from src.core.models.triage import (
    TriageRequest,
    TriageSession,
    TriageStatus,
    TriageEvent,
    TriageEventType,
)
from src.core.models.health import ComponentHealth, HealthResponse

__all__ = [
    "Job",
    "JobStatus",
    "JobEvent",
    "JobEventType",
    "Schedule",
    "AuthType",
    "SshCredential",
    "TelemetryConfig",
    "EvidenceArtifact",
    "EvidenceType",
    "CollectorType",
    "CollectionStatus",
    "ValidatorType",
    "SystemProperties",
    "Applicability",
    "Rule",
    "Playbook",
    "Reference",
    "LearnedPattern",
    "ValidatorSpec",
    "TriageRequest",
    "TriageSession",
    "TriageStatus",
    "TriageEvent",
    "TriageEventType",
    "ComponentHealth",
    "HealthResponse",
]
