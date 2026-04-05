# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Knowledge model types matching the JSONL schemas in Section 7."""

from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field
from src.core.models.system import Applicability
from src.core.models.validators import ValidatorType


class ValidatorSpec(BaseModel):
    """Validator specification embedded in a rule definition.

    :param type: Validation strategy to apply.
    :param source: Where to find the value (sysctl, global_ini, cib, etc.).
    :param parameter: Parameter name to check.
    :param expected: Expected value for exact_match/min_value.
    :param expected_by_storage: Storage-dependent expected values.
    :param pattern: Regex pattern (for regex validator type).
    :param min_value: Minimum value (for range validator type).
    :param max_value: Maximum value (for range validator type).
    :param custom_function: Python function name (for custom validator type).
    """

    model_config = ConfigDict(use_enum_values=True)

    type: ValidatorType
    source: str = ""
    parameter: str = ""
    expected: Any = None
    expected_by_storage: Optional[dict[str, Any]] = None
    pattern: Optional[str] = None
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    custom_function: Optional[str] = None


class Rule(BaseModel):
    """A knowledge rule: one thing that should be true.

    :param id: Unique rule identifier (e.g. ``DB-HANA-0001``).
    :param name: Short descriptive name.
    :param description: What this rule checks.
    :param category: Rule category (ha_check, os_config, etc.).
    :param severity: How critical a violation is.
    :param applicability: Filter criteria for which systems this applies to.
    :param validator: How to validate the rule.
    :param references: SAP Notes, Azure docs, etc.
    :param tags: Searchable tags.
    """

    model_config = ConfigDict(use_enum_values=True)

    id: str
    name: str
    description: str = ""
    category: str = ""
    severity: str = "MEDIUM"
    applicability: Optional[Applicability] = None
    validator: Optional[ValidatorSpec] = None
    references: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class Playbook(BaseModel):
    """Investigation procedure for a specific failure type.

    :param id: Unique playbook identifier (e.g. ``PB-HANA-HSR-0001``).
    :param name: Short descriptive name.
    :param description: What failure this playbook addresses.
    :param category: Playbook category (ha_failure, config_drift, etc.).
    :param symptoms: Observable symptoms that trigger this playbook.
    :param investigation: Ordered investigation steps.
    :param root_cause: Expected root cause description.
    :param fixes: Remediation steps.
    :param related_patterns: IDs of related rules or playbooks.
    :param tags: Searchable tags.
    :param source: Origin of this playbook (seed or learned).
    """

    id: str
    name: str
    description: str = ""
    category: str = ""
    symptoms: list[str] = Field(default_factory=list)
    investigation: list[str] = Field(default_factory=list)
    root_cause: str = ""
    fixes: list[str] = Field(default_factory=list)
    related_patterns: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    source: str = "seed"


class Reference(BaseModel):
    """Curated external reference (SAP Note, Azure doc, etc.).

    :param id: Unique reference identifier.
    :param title: Human-readable title.
    :param url: Link to the external resource.
    :param category: Reference category.
    :param failure_classes: Failure classes this reference is relevant to.
    :param summary: Brief summary of the resource.
    :param tags: Searchable tags.
    """

    id: str
    title: str
    url: str = ""
    category: str = ""
    failure_classes: list[str] = Field(default_factory=list)
    summary: str = ""
    tags: list[str] = Field(default_factory=list)


class LearnedPattern(BaseModel):
    """A pattern extracted from a completed triage session.

    :param id: Unique pattern identifier.
    :param name: Short descriptive name.
    :param description: What this pattern represents.
    :param category: Pattern category.
    :param symptoms: Observed symptoms.
    :param investigation: Ordered investigation steps.
    :param root_cause: Identified root cause.
    :param fixes: Remediation steps that worked.
    :param related_patterns: IDs of related rules or playbooks.
    :param tags: Searchable tags.
    :param source: Always ``learned`` for this type.
    :param confidence: Confidence score (0.0–1.0).
    :param occurrence_count: How many times this pattern was observed.
    :param first_seen: When this pattern was first observed.
    :param last_seen: When this pattern was last observed.
    :param source_sessions: Triage sessions that contributed to this pattern.
    """

    id: str
    name: str
    description: str = ""
    category: str = ""
    symptoms: list[str] = Field(default_factory=list)
    investigation: list[str] = Field(default_factory=list)
    root_cause: str = ""
    fixes: list[str] = Field(default_factory=list)
    related_patterns: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    source: str = "learned"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    occurrence_count: int = Field(default=1, ge=1)
    first_seen: datetime = Field(default_factory=datetime.utcnow)
    last_seen: datetime = Field(default_factory=datetime.utcnow)
    source_sessions: list[str] = Field(default_factory=list)


class KnowledgeGap(BaseModel):
    """A gap identified when no rule or playbook matched a finding.

    :param id: Unique gap identifier.
    :param description: What evidence or symptom had no matching knowledge.
    :param session_id: Triage session where the gap was found.
    :param created_at: When the gap was recorded.
    :param resolved: Whether the gap has been filled by a new rule/playbook.
    """

    id: str
    description: str
    session_id: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    resolved: bool = False


class ExperienceEntry(BaseModel):
    """Record of a triage session outcome for the self-learning pipeline.

    :param session_id: Triage session identifier.
    :param timestamp: When the session completed.
    :param system_id: Target system identifier (e.g. PRD-HANA-01).
    :param trigger: What triggered the triage (e.g. ha_failover_test).
    :param duration_seconds: Total triage duration in seconds.
    :param patterns_matched: IDs of matched rules and playbooks.
    :param rules_fired: Total number of rules evaluated.
    :param rules_failed: Number of rules that failed validation.
    :param root_cause_found: Whether a root cause was identified.
    :param resolution_applied: Whether a fix was applied.
    :param operator_feedback: Operator feedback on accuracy.
    :param knowledge_gaps: IDs of knowledge gaps found.
    """

    session_id: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    system_id: str = ""
    trigger: str = ""
    duration_seconds: float = 0.0
    patterns_matched: list[str] = Field(default_factory=list)
    rules_fired: int = 0
    rules_failed: int = 0
    root_cause_found: bool = False
    resolution_applied: bool = False
    operator_feedback: Optional[str] = None
    knowledge_gaps: list[str] = Field(default_factory=list)


class EvidenceCollectorDef(BaseModel):
    """Evidence collection definition — describes how to get data from a system.

    Loaded from ``seed/evidence/*.jsonl``. Separate from rules: one definition
    can serve many rules. Matches STAF.md Section 7.6 schema.

    :param id: Unique definition identifier (e.g. ``EC-SYSCTL-0001``).
    :param type: Collector type (``command``, ``azure``, ``module``).
    :param name: Short name for this definition.
    :param command: Default command string to execute (for ``command``-type).
    :param description: Human-readable purpose.
    :param os_family: Which OS families this applies to.
    :param parser: Parser name for output processing.
    :param source: Analyzer source name this evidence maps to.
        Must match a key in ``NormalizerRegistry`` (e.g. ``cib_resource``,
        ``sysctl``, ``command``). Defaults to ``command``.
    :param evidence_type: Evidence type for the artifact
        (e.g. ``command_output``, ``cib_xml``, ``log_output``).
    :param cache_ttl_seconds: How long to cache results.
    :param max_timeout_seconds: Maximum execution time.
    :param tags: Searchable tags.
    :param requires_ha: True if this definition should only run on HA systems.
    :param metadata: Structured execution metadata. For log sources this
        includes ``access_method`` (``file``, ``journalctl``, ``grep_filter``,
        ``dmesg``), ``path_template``, ``timestamp_format`` (``iso``,
        ``syslog``, ``hana``), ``run_as`` (e.g. ``<sid>adm``),
        ``service_units`` (journalctl -u args), ``base_filter`` (grep
        pattern for syslog-based sources), and ``key_patterns`` (useful
        grep patterns for the LLM).
    """

    id: str
    type: str = "command"
    name: str = ""
    command: str = ""
    description: str = ""
    os_family: list[str] = Field(default_factory=lambda: ["SUSE", "REDHAT"])
    parser: str = ""
    source: str = "command"
    evidence_type: str = "command_output"
    cache_ttl_seconds: int = 300
    max_timeout_seconds: int = 30
    tags: list[str] = Field(default_factory=list)
    requires_ha: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)
