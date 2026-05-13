# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for knowledge model types."""

import pytest
from src.core.models.knowledge import (
    LearnedPattern,
    Playbook,
    Reference,
    Rule,
    ValidatorSpec,
)
from src.core.models.system import Applicability
from src.core.models.validators import ValidatorType


class TestValidatorSpec:
    """Unit tests for ValidatorSpec model."""

    def test_create_exact_match(self) -> None:
        """Verify exact_match validator spec creation."""
        spec = ValidatorSpec(
            type=ValidatorType.EXACT_MATCH,
            source="global_ini",
            parameter="PREFER_SITE_TAKEOVER",
            expected="true",
        )
        assert spec.type == ValidatorType.EXACT_MATCH.value
        assert spec.expected == "true"

    def test_create_min_value(self) -> None:
        """Verify min_value validator spec creation."""
        spec = ValidatorSpec(
            type=ValidatorType.MIN_VALUE,
            source="sysctl",
            parameter="net.core.rmem_max",
            expected=16777216,
        )
        assert spec.parameter == "net.core.rmem_max"

    def test_create_range(self) -> None:
        """Verify range validator spec with min/max."""
        spec = ValidatorSpec(
            type=ValidatorType.RANGE,
            source="sysctl",
            parameter="vm.dirty_ratio",
            min_value=10.0,
            max_value=40.0,
        )
        assert spec.min_value == 10.0
        assert spec.max_value == 40.0

    def test_create_regex(self) -> None:
        """Verify regex validator spec."""
        spec = ValidatorSpec(
            type=ValidatorType.REGEX,
            source="cib",
            parameter="resource_id",
            pattern=r"rsc_SAPHana_\w+_HDB\d+",
        )
        assert spec.pattern is not None

    def test_create_with_storage_overrides(self) -> None:
        """Verify expected_by_storage field."""
        spec = ValidatorSpec(
            type=ValidatorType.MIN_VALUE,
            source="sysctl",
            parameter="net.core.rmem_max",
            expected_by_storage={
                "premium_ssd": 2500000,
                "anf": 16777216,
            },
        )
        assert spec.expected_by_storage is not None
        assert spec.expected_by_storage["anf"] == 16777216

    def test_create_custom(self) -> None:
        """Verify custom validator spec."""
        spec = ValidatorSpec(
            type=ValidatorType.CUSTOM,
            custom_function="check_hana_indexserver",
        )
        assert spec.custom_function == "check_hana_indexserver"


class TestRule:
    """Unit tests for Rule model."""

    def test_create_minimal(self) -> None:
        """Verify minimal rule creation."""
        rule = Rule(id="DB-HANA-0001", name="PREFER_SITE_TAKEOVER")
        assert rule.id == "DB-HANA-0001"
        assert rule.tags == []
        assert rule.references == []

    def test_create_full(self) -> None:
        """Verify full rule creation with all fields."""
        rule = Rule(
            id="DB-HANA-0001",
            name="PREFER_SITE_TAKEOVER",
            description="Should be true for automatic site takeover",
            category="ha_check",
            severity="HIGH",
            applicability=Applicability(
                database_type="HANA",
                ha_enabled=True,
                hana_topology=["scale_up", "scale_out_hsr"],
            ),
            validator=ValidatorSpec(
                type=ValidatorType.EXACT_MATCH,
                source="global_ini",
                parameter="PREFER_SITE_TAKEOVER",
                expected="true",
            ),
            references=["SAP Note 2407186"],
            tags=["hana", "hsr"],
        )
        assert rule.severity == "HIGH"
        assert rule.applicability is not None
        assert rule.validator is not None
        assert len(rule.references) == 1

    def test_json_roundtrip(self) -> None:
        """Verify Rule serializes and deserializes via JSON."""
        rule = Rule(
            id="R-001",
            name="test",
            tags=["a", "b"],
        )
        data = rule.model_dump()
        restored = Rule(**data)
        assert restored.id == rule.id
        assert restored.tags == ["a", "b"]


class TestPlaybook:
    """Unit tests for Playbook model."""

    def test_create_minimal(self) -> None:
        """Verify minimal playbook creation."""
        pb = Playbook(id="PB-001", name="HSR takeover failure")
        assert pb.id == "PB-001"
        assert pb.source == "seed"

    def test_create_full(self) -> None:
        """Verify full playbook creation."""
        pb = Playbook(
            id="PB-HANA-HSR-0001",
            name="HANA HSR takeover failure",
            description="Primary failed but secondary did not take over",
            category="ha_failure",
            symptoms=["Secondary remains in SOK status"],
            investigation=["Check SAPHanaSR sync_state"],
            root_cause="PREFER_SITE_TAKEOVER disabled",
            fixes=["Set PREFER_SITE_TAKEOVER = true"],
            related_patterns=["DB-HANA-0001"],
            tags=["hana", "hsr"],
        )
        assert len(pb.symptoms) == 1
        assert len(pb.fixes) == 1
        assert pb.related_patterns == ["DB-HANA-0001"]

    def test_json_roundtrip(self) -> None:
        """Verify Playbook serializes and deserializes via JSON."""
        pb = Playbook(id="PB-001", name="test", symptoms=["s1"])
        data = pb.model_dump()
        restored = Playbook(**data)
        assert restored.symptoms == ["s1"]


class TestReference:
    """Unit tests for Reference model."""

    def test_create(self) -> None:
        """Verify reference creation."""
        ref = Reference(
            id="REF-001",
            title="SAP HANA System Replication",
            url="https://help.sap.com/docs/...",
            category="hana_hsr",
            failure_classes=["hsr_takeover_failure"],
            summary="HSR setup and troubleshooting",
            tags=["hana"],
        )
        assert ref.url.startswith("https://")
        assert len(ref.failure_classes) == 1


class TestLearnedPattern:
    """Unit tests for LearnedPattern model."""

    def test_create(self) -> None:
        """Verify learned pattern creation."""
        pattern = LearnedPattern(
            id="LP-001",
            name="Recurring fencing delay",
            description="SBD takes >60s on Azure ultra disk",
            confidence=0.85,
            occurrence_count=3,
            investigation=["Check SBD timeout", "Check disk latency"],
            related_patterns=["DB-HANA-0001"],
            source_sessions=["sess-1", "sess-2", "sess-3"],
        )
        assert pattern.confidence == 0.85
        assert pattern.source == "learned"
        assert len(pattern.source_sessions) == 3
        assert len(pattern.investigation) == 2
        assert pattern.related_patterns == ["DB-HANA-0001"]

    def test_confidence_bounds(self) -> None:
        """Verify confidence rejects out-of-range values."""
        with pytest.raises(Exception):
            LearnedPattern(id="LP-X", name="bad", confidence=1.5)

    def test_occurrence_count_min(self) -> None:
        """Verify occurrence_count rejects zero."""
        with pytest.raises(Exception):
            LearnedPattern(id="LP-X", name="bad", occurrence_count=0)
