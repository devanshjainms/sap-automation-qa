# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for validator type definitions and result models."""

import pytest
from src.core.models.validators import ValidatorResult, ValidatorType


class TestValidatorType:
    """Unit tests for ValidatorType enum."""

    def test_known_members(self) -> None:
        """Verify expected validator types exist."""
        expected = {
            "exact_match",
            "min_value",
            "range",
            "regex",
            "presence",
            "custom",
        }
        actual = {m.value for m in ValidatorType}
        assert actual == expected

    def test_from_string(self) -> None:
        """Verify ValidatorType can be constructed from string."""
        assert ValidatorType("regex") == ValidatorType.REGEX


class TestValidatorResult:
    """Unit tests for ValidatorResult frozen dataclass."""

    def test_create_passed(self) -> None:
        """Verify a passing result."""
        result = ValidatorResult(
            passed=True,
            rule_id="DB-HANA-0001",
            expected="true",
            actual="true",
            validator_type=ValidatorType.EXACT_MATCH,
        )
        assert result.passed is True
        assert result.rule_id == "DB-HANA-0001"

    def test_create_failed(self) -> None:
        """Verify a failing result with message."""
        result = ValidatorResult(
            passed=False,
            rule_id="CONFIG-NET-0012",
            expected=16777216,
            actual=2500000,
            validator_type=ValidatorType.MIN_VALUE,
            message="net.core.rmem_max below ANF threshold",
        )
        assert result.passed is False
        assert result.message == "net.core.rmem_max below ANF threshold"

    def test_frozen(self) -> None:
        """Verify result is immutable."""
        result = ValidatorResult(passed=True, rule_id="R-001")
        with pytest.raises(AttributeError):
            result.passed = False  # type: ignore[misc]

    def test_to_dict(self) -> None:
        """Verify to_dict produces a complete dictionary."""
        result = ValidatorResult(
            passed=False,
            rule_id="DB-HANA-0002",
            expected="true",
            actual="false",
            validator_type=ValidatorType.EXACT_MATCH,
            message="PREFER_SITE_TAKEOVER mismatch",
        )
        d = result.to_dict()
        assert d["passed"] is False
        assert d["rule_id"] == "DB-HANA-0002"
        assert d["expected"] == "true"
        assert d["actual"] == "false"
        assert d["validator_type"] == "exact_match"
        assert d["message"] == "PREFER_SITE_TAKEOVER mismatch"

    def test_defaults(self) -> None:
        """Verify default values."""
        result = ValidatorResult(passed=True, rule_id="R-001")
        assert result.expected is None
        assert result.actual is None
        assert result.validator_type == ValidatorType.EXACT_MATCH
        assert result.message == ""
