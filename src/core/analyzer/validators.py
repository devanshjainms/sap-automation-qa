# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Rule validator — evaluates rules against normalized evidence data.

Uses the **Strategy pattern**: dispatches to typed validation functions
based on ``ValidatorType``. Each function is small and focused.
"""

import logging
import re
from typing import Any, Callable, Optional

from src.core.analyzer.normalizers import NormalizedData
from src.core.models.knowledge import Rule, ValidatorSpec
from src.core.models.validators import ValidatorResult, ValidatorType

logger = logging.getLogger(__name__)


def _exact_match(actual: Any, spec: ValidatorSpec, rule_id: str) -> ValidatorResult:
    """Check whether actual value matches expected exactly.

    Handles list-of-acceptable-values in ``spec.expected``.
    Comparison is string-based and case-insensitive.
    """
    expected = spec.expected
    actual_str = str(actual).strip().lower() if actual is not None else ""

    if isinstance(expected, list):
        expected_strs = [str(e).strip().lower() for e in expected]
        passed = actual_str in expected_strs
        expected_display = expected
    else:
        expected_str = str(expected).strip().lower()
        passed = actual_str == expected_str
        expected_display = expected

    return ValidatorResult(
        passed=passed,
        rule_id=rule_id,
        expected=expected_display,
        actual=actual,
        validator_type=ValidatorType.EXACT_MATCH,
        message=f"{spec.parameter}: expected {expected_display}, got {actual}",
    )


def _min_value(actual: Any, spec: ValidatorSpec, rule_id: str) -> ValidatorResult:
    """Check whether actual value meets a minimum threshold."""
    try:
        actual_num = float(actual) if actual is not None else 0.0
    except (ValueError, TypeError):
        return ValidatorResult(
            passed=False,
            rule_id=rule_id,
            expected=spec.expected,
            actual=actual,
            validator_type=ValidatorType.MIN_VALUE,
            message=f"{spec.parameter}: cannot convert '{actual}' to number",
        )

    expected_num = float(spec.expected) if spec.expected is not None else 0.0
    passed = actual_num >= expected_num

    return ValidatorResult(
        passed=passed,
        rule_id=rule_id,
        expected=spec.expected,
        actual=actual,
        validator_type=ValidatorType.MIN_VALUE,
        message=f"{spec.parameter}: min {expected_num}, got {actual_num}",
    )


def _range_check(actual: Any, spec: ValidatorSpec, rule_id: str) -> ValidatorResult:
    """Check whether actual value falls within [min_value, max_value]."""
    try:
        actual_num = float(actual) if actual is not None else 0.0
    except (ValueError, TypeError):
        return ValidatorResult(
            passed=False,
            rule_id=rule_id,
            expected=f"[{spec.min_value}, {spec.max_value}]",
            actual=actual,
            validator_type=ValidatorType.RANGE,
            message=f"{spec.parameter}: cannot convert '{actual}' to number",
        )

    low = spec.min_value if spec.min_value is not None else float("-inf")
    high = spec.max_value if spec.max_value is not None else float("inf")
    passed = low <= actual_num <= high

    return ValidatorResult(
        passed=passed,
        rule_id=rule_id,
        expected=f"[{low}, {high}]",
        actual=actual_num,
        validator_type=ValidatorType.RANGE,
        message=f"{spec.parameter}: range [{low}, {high}], got {actual_num}",
    )


def _regex_match(actual: Any, spec: ValidatorSpec, rule_id: str) -> ValidatorResult:
    """Check whether actual value matches a regex pattern."""
    actual_str = str(actual) if actual is not None else ""
    pattern = spec.pattern or ""
    try:
        passed = bool(re.search(pattern, actual_str, re.IGNORECASE))
    except re.error as exc:
        logger.warning("Invalid regex in rule %s: %s", rule_id, exc)
        passed = False

    return ValidatorResult(
        passed=passed,
        rule_id=rule_id,
        expected=pattern,
        actual=actual,
        validator_type=ValidatorType.REGEX,
        message=f"{spec.parameter}: pattern /{pattern}/ {'matched' if passed else 'not matched'}",
    )


def _presence_check(actual: Any, spec: ValidatorSpec, rule_id: str) -> ValidatorResult:
    """Check whether a parameter exists (is not None and not empty)."""
    passed = actual is not None and str(actual).strip() != ""

    return ValidatorResult(
        passed=passed,
        rule_id=rule_id,
        expected="present",
        actual=actual,
        validator_type=ValidatorType.PRESENCE,
        message=f"{spec.parameter}: {'present' if passed else 'absent'}",
    )


def _custom_check(actual: Any, spec: ValidatorSpec, rule_id: str) -> ValidatorResult:
    """Placeholder for custom validation functions.

    Custom validators are not executed (security boundary).
    They are logged and marked as skipped.
    """
    logger.info(
        "Custom validator '%s' for rule %s — skipped (not implemented)",
        spec.custom_function,
        rule_id,
    )
    return ValidatorResult(
        passed=True,
        rule_id=rule_id,
        expected=f"custom:{spec.custom_function}",
        actual=actual,
        validator_type=ValidatorType.CUSTOM,
        message=f"{spec.parameter}: custom check skipped",
    )


_STRATEGIES: dict[
    ValidatorType,
    Callable[[Any, ValidatorSpec, str], ValidatorResult],
] = {
    ValidatorType.EXACT_MATCH: _exact_match,
    ValidatorType.MIN_VALUE: _min_value,
    ValidatorType.RANGE: _range_check,
    ValidatorType.REGEX: _regex_match,
    ValidatorType.PRESENCE: _presence_check,
    ValidatorType.CUSTOM: _custom_check,
}


class RuleValidator:
    """Evaluates rules against normalized evidence data.

    Uses the Strategy pattern to dispatch to the correct validation
    function based on ``ValidatorType``.
    """

    def validate(self, rule: Rule, data: NormalizedData) -> ValidatorResult:
        """Evaluate a single rule against normalized data.

        :param rule: The rule to evaluate.
        :param data: Normalized evidence data.
        :returns: Validation result.
        """
        spec = rule.validator
        if spec is None:
            return ValidatorResult(
                passed=True,
                rule_id=rule.id,
                message="No validator defined — auto-pass",
            )

        actual = self._resolve_value(spec, data)
        validator_type = ValidatorType(spec.type)
        strategy = _STRATEGIES.get(validator_type)

        if strategy is None:
            return ValidatorResult(
                passed=False,
                rule_id=rule.id,
                actual=actual,
                validator_type=validator_type,
                message=f"Unknown validator type: {spec.type}",
            )

        return strategy(actual, spec, rule.id)

    def validate_many(
        self, rules: list[Rule], data_map: dict[str, NormalizedData]
    ) -> list[ValidatorResult]:
        """Evaluate multiple rules against a source→data mapping.

        :param rules: Rules to evaluate.
        :param data_map: Mapping of source name → normalized data.
        :returns: List of results (one per rule).
        """
        results: list[ValidatorResult] = []
        for rule in rules:
            source = rule.validator.source if rule.validator else ""
            data = data_map.get(source)
            if data is None:
                results.append(
                    ValidatorResult(
                        passed=True,
                        rule_id=rule.id,
                        skipped=True,
                        message=f"Skipped: no evidence for source '{source}'",
                    )
                )
                continue
            results.append(self.validate(rule, data))
        return results

    def _resolve_value(self, spec: ValidatorSpec, data: NormalizedData) -> Optional[Any]:
        """Look up the actual value from normalized data.

        Direct parameter lookup only. Normalizers are responsible for
        producing keys that match rule parameter names.

        :param spec: Validator specification with the parameter name.
        :param data: Normalized evidence data.
        :returns: The actual value, or None if not found.
        """
        return data.get(spec.parameter)
