# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for RuleValidator — strategy dispatch, value resolution, edge cases."""

import pytest

from src.core.analyzer.normalizers import NormalizedData
from src.core.analyzer.validators import RuleValidator
from src.core.models.knowledge import Rule, ValidatorSpec
from src.core.models.validators import ValidatorResult, ValidatorType

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _rule(
    rule_id: str = "R-001",
    source: str = "crm_config",
    parameter: str = "stonith-enabled",
    expected: str = "true",
    vtype: ValidatorType = ValidatorType.EXACT_MATCH,
    **kwargs,
) -> Rule:
    """Create a minimal Rule with a validator spec."""
    return Rule(
        id=rule_id,
        name=f"Test {rule_id}",
        validator=ValidatorSpec(
            type=vtype,
            source=source,
            parameter=parameter,
            expected=expected,
            **kwargs,
        ),
    )


def _data(source: str, values: dict) -> NormalizedData:
    """Create minimal NormalizedData."""
    return NormalizedData(source=source, values=values)


# ---------------------------------------------------------------------------
# Exact match
# ---------------------------------------------------------------------------


class TestExactMatch:
    """Tests for exact_match validation strategy."""

    def test_pass_string(self) -> None:
        rule = _rule(expected="true")
        data = _data("crm_config", {"stonith-enabled": "true"})
        result = RuleValidator().validate(rule, data)
        assert result.passed is True
        assert result.rule_id == "R-001"
        assert result.validator_type == ValidatorType.EXACT_MATCH

    def test_fail_string(self) -> None:
        rule = _rule(expected="true")
        data = _data("crm_config", {"stonith-enabled": "false"})
        result = RuleValidator().validate(rule, data)
        assert result.passed is False

    def test_case_insensitive(self) -> None:
        rule = _rule(expected="True")
        data = _data("crm_config", {"stonith-enabled": "TRUE"})
        result = RuleValidator().validate(rule, data)
        assert result.passed is True

    def test_list_of_expected(self) -> None:
        rule = _rule(expected=["true", "yes"])
        data = _data("crm_config", {"stonith-enabled": "yes"})
        result = RuleValidator().validate(rule, data)
        assert result.passed is True

    def test_list_of_expected_fail(self) -> None:
        rule = _rule(expected=["true", "yes"])
        data = _data("crm_config", {"stonith-enabled": "no"})
        result = RuleValidator().validate(rule, data)
        assert result.passed is False

    def test_none_actual(self) -> None:
        rule = _rule(expected="true")
        data = _data("crm_config", {})
        result = RuleValidator().validate(rule, data)
        assert result.passed is False

    def test_direct_key_lookup(self) -> None:
        rule = _rule(source="sysctl", parameter="vm.swappiness", expected="10")
        data = _data("sysctl", {"vm.swappiness": "10"})
        result = RuleValidator().validate(rule, data)
        assert result.passed is True


# ---------------------------------------------------------------------------
# Min value
# ---------------------------------------------------------------------------


class TestMinValue:
    """Tests for min_value validation strategy."""

    def test_pass(self) -> None:
        rule = _rule(vtype="min_value", expected="100")
        data = _data("crm_config", {"stonith-enabled": "150"})
        result = RuleValidator().validate(rule, data)
        assert result.passed is True

    def test_fail(self) -> None:
        rule = _rule(vtype="min_value", expected="200")
        data = _data("crm_config", {"stonith-enabled": "100"})
        result = RuleValidator().validate(rule, data)
        assert result.passed is False

    def test_exact_boundary(self) -> None:
        rule = _rule(vtype="min_value", expected="100")
        data = _data("crm_config", {"stonith-enabled": "100"})
        result = RuleValidator().validate(rule, data)
        assert result.passed is True

    def test_non_numeric_actual(self) -> None:
        rule = _rule(vtype="min_value", expected="10")
        data = _data("crm_config", {"stonith-enabled": "abc"})
        result = RuleValidator().validate(rule, data)
        assert result.passed is False
        assert "cannot convert" in result.message

    def test_none_actual_is_zero(self) -> None:
        rule = _rule(vtype="min_value", expected="1")
        data = _data("crm_config", {})
        result = RuleValidator().validate(rule, data)
        assert result.passed is False


# ---------------------------------------------------------------------------
# Range
# ---------------------------------------------------------------------------


class TestRange:
    """Tests for range validation strategy."""

    def test_in_range(self) -> None:
        rule = _rule(vtype="range", min_value=10, max_value=20)
        data = _data("crm_config", {"stonith-enabled": "15"})
        result = RuleValidator().validate(rule, data)
        assert result.passed is True

    def test_at_lower_bound(self) -> None:
        rule = _rule(vtype="range", min_value=10, max_value=20)
        data = _data("crm_config", {"stonith-enabled": "10"})
        result = RuleValidator().validate(rule, data)
        assert result.passed is True

    def test_at_upper_bound(self) -> None:
        rule = _rule(vtype="range", min_value=10, max_value=20)
        data = _data("crm_config", {"stonith-enabled": "20"})
        result = RuleValidator().validate(rule, data)
        assert result.passed is True

    def test_below_range(self) -> None:
        rule = _rule(vtype="range", min_value=10, max_value=20)
        data = _data("crm_config", {"stonith-enabled": "5"})
        result = RuleValidator().validate(rule, data)
        assert result.passed is False

    def test_above_range(self) -> None:
        rule = _rule(vtype="range", min_value=10, max_value=20)
        data = _data("crm_config", {"stonith-enabled": "25"})
        result = RuleValidator().validate(rule, data)
        assert result.passed is False

    def test_non_numeric(self) -> None:
        rule = _rule(vtype="range", min_value=0, max_value=100)
        data = _data("crm_config", {"stonith-enabled": "abc"})
        result = RuleValidator().validate(rule, data)
        assert result.passed is False

    def test_none_min_is_negative_inf(self) -> None:
        rule = _rule(vtype="range", max_value=100)
        data = _data("crm_config", {"stonith-enabled": "-999"})
        result = RuleValidator().validate(rule, data)
        assert result.passed is True

    def test_none_max_is_positive_inf(self) -> None:
        rule = _rule(vtype="range", min_value=0)
        data = _data("crm_config", {"stonith-enabled": "99999"})
        result = RuleValidator().validate(rule, data)
        assert result.passed is True


# ---------------------------------------------------------------------------
# Regex
# ---------------------------------------------------------------------------


class TestRegex:
    """Tests for regex validation strategy."""

    def test_match(self) -> None:
        rule = _rule(vtype="regex", pattern=r"node\d+")
        data = _data("crm_config", {"stonith-enabled": "node01"})
        result = RuleValidator().validate(rule, data)
        assert result.passed is True

    def test_no_match(self) -> None:
        rule = _rule(vtype="regex", pattern=r"^PASS$")
        data = _data("crm_config", {"stonith-enabled": "FAIL"})
        result = RuleValidator().validate(rule, data)
        assert result.passed is False

    def test_case_insensitive(self) -> None:
        rule = _rule(vtype="regex", pattern=r"pass")
        data = _data("crm_config", {"stonith-enabled": "PASSED"})
        result = RuleValidator().validate(rule, data)
        assert result.passed is True

    def test_invalid_regex(self) -> None:
        rule = _rule(vtype="regex", pattern=r"[invalid")
        data = _data("crm_config", {"stonith-enabled": "x"})
        result = RuleValidator().validate(rule, data)
        assert result.passed is False

    def test_none_actual(self) -> None:
        rule = _rule(vtype="regex", pattern=r".")
        data = _data("crm_config", {})
        result = RuleValidator().validate(rule, data)
        assert result.passed is False


# ---------------------------------------------------------------------------
# Presence
# ---------------------------------------------------------------------------


class TestPresence:
    """Tests for presence validation strategy."""

    def test_present(self) -> None:
        rule = _rule(vtype="presence")
        data = _data("crm_config", {"stonith-enabled": "true"})
        result = RuleValidator().validate(rule, data)
        assert result.passed is True

    def test_absent(self) -> None:
        rule = _rule(vtype="presence")
        data = _data("crm_config", {})
        result = RuleValidator().validate(rule, data)
        assert result.passed is False

    def test_empty_string_is_absent(self) -> None:
        rule = _rule(vtype="presence")
        data = _data("crm_config", {"stonith-enabled": ""})
        result = RuleValidator().validate(rule, data)
        assert result.passed is False

    def test_whitespace_is_absent(self) -> None:
        rule = _rule(vtype="presence")
        data = _data("crm_config", {"stonith-enabled": "   "})
        result = RuleValidator().validate(rule, data)
        assert result.passed is False


# ---------------------------------------------------------------------------
# Custom
# ---------------------------------------------------------------------------


class TestCustom:
    """Tests for custom validation strategy (placeholder)."""

    def test_custom_auto_passes(self) -> None:
        rule = _rule(vtype="custom", custom_function="check_something")
        data = _data("crm_config", {"stonith-enabled": "any"})
        result = RuleValidator().validate(rule, data)
        assert result.passed is True
        assert "skipped" in result.message


# ---------------------------------------------------------------------------
# No validator
# ---------------------------------------------------------------------------


class TestNoValidator:
    """Tests for rules without a validator spec."""

    def test_auto_pass(self) -> None:
        rule = Rule(id="R-NONE", name="No validator")
        data = _data("sysctl", {})
        result = RuleValidator().validate(rule, data)
        assert result.passed is True
        assert "auto-pass" in result.message.lower()


# ---------------------------------------------------------------------------
# Value resolution
# ---------------------------------------------------------------------------


class TestValueResolution:
    """Tests for _resolve_value — direct parameter lookup."""

    def test_direct_lookup(self) -> None:
        rule = _rule(source="sysctl", parameter="vm.swappiness")
        data = _data("sysctl", {"vm.swappiness": "10"})
        result = RuleValidator().validate(rule, data)
        assert result.actual == "10"

    def test_crm_config_direct_lookup(self) -> None:
        """CIB section normalizers strip prefixes, so direct lookup works."""
        rule = _rule(source="crm_config", parameter="stonith-enabled")
        data = _data("crm_config", {"stonith-enabled": "true"})
        result = RuleValidator().validate(rule, data)
        assert result.actual == "true"

    def test_cib_resource_direct_lookup(self) -> None:
        """CIB section normalizer strips 'resource.' prefix."""
        rule = _rule(source="cib_resource", parameter="rsc_SAPHana.SID")
        data = _data("cib_resource", {"rsc_SAPHana.SID": "HDB"})
        result = RuleValidator().validate(rule, data)
        assert result.actual == "HDB"

    def test_missing_parameter_returns_none(self) -> None:
        rule = _rule(source="custom_source", parameter="param")
        data = _data("custom_source", {})
        result = RuleValidator().validate(rule, data)
        assert result.actual is None


# ---------------------------------------------------------------------------
# validate_many
# ---------------------------------------------------------------------------


class TestValidateMany:
    """Tests for validate_many — batch evaluation."""

    def test_empty_rules(self) -> None:
        results = RuleValidator().validate_many([], {})
        assert results == []

    def test_multiple_rules(self) -> None:
        rules = [
            _rule(rule_id="R1", source="sysctl", parameter="a", expected="1"),
            _rule(rule_id="R2", source="sysctl", parameter="b", expected="2"),
        ]
        data_map = {"sysctl": _data("sysctl", {"a": "1", "b": "wrong"})}
        results = RuleValidator().validate_many(rules, data_map)
        assert len(results) == 2
        assert results[0].passed is True
        assert results[1].passed is False

    def test_missing_source_skipped(self) -> None:
        rules = [_rule(source="sysctl", parameter="a", expected="1")]
        data_map = {}
        results = RuleValidator().validate_many(rules, data_map)
        assert len(results) == 1
        assert results[0].passed is True
        assert results[0].skipped is True
        assert "skipped" in results[0].message.lower()

    def test_mixed_sources(self) -> None:
        rules = [
            _rule(rule_id="R1", source="sysctl", parameter="x", expected="1"),
            _rule(
                rule_id="R2",
                source="crm_config",
                parameter="stonith-enabled",
                expected="true",
            ),
        ]
        data_map = {
            "sysctl": _data("sysctl", {"x": "1"}),
            "crm_config": _data("crm_config", {"stonith-enabled": "true"}),
        }
        results = RuleValidator().validate_many(rules, data_map)
        assert all(r.passed for r in results)

    def test_result_order_matches_rules(self) -> None:
        rules = [
            _rule(rule_id="R-A", source="s", parameter="a", expected="1"),
            _rule(rule_id="R-B", source="s", parameter="b", expected="2"),
        ]
        data_map = {"s": _data("s", {"a": "1", "b": "2"})}
        results = RuleValidator().validate_many(rules, data_map)
        assert [r.rule_id for r in results] == ["R-A", "R-B"]
