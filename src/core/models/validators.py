# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Validator type definitions and result models for rule evaluation."""

from dataclasses import dataclass
from enum import Enum
from typing import Any


class ValidatorType(str, Enum):
    """Strategy for validating an evidence value against a rule.
    Each type corresponds to a validation strategy in the analyzer.
    """

    EXACT_MATCH = "exact_match"
    MIN_VALUE = "min_value"
    RANGE = "range"
    REGEX = "regex"
    PRESENCE = "presence"
    CUSTOM = "custom"


@dataclass(frozen=True)
class ValidatorResult:
    """Outcome of evaluating a single rule against evidence.
    Immutable value object produced by the analyzer.

    :param passed: Whether the validation passed.
    :param rule_id: ID of the rule that was evaluated.
    :param expected: Expected value from the rule definition.
    :param actual: Actual value found in evidence.
    :param validator_type: Which validator strategy was used.
    :param message: Human-readable description of the result.
    :param skipped: True when evidence source was unavailable.
    """

    passed: bool
    rule_id: str
    expected: Any = None
    actual: Any = None
    validator_type: ValidatorType = ValidatorType.EXACT_MATCH
    message: str = ""
    skipped: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dictionary for JSON storage.

        :returns: Dictionary representation of the result.
        :rtype: dict[str, Any]
        """
        d = {
            "passed": self.passed,
            "rule_id": self.rule_id,
            "expected": self.expected,
            "actual": self.actual,
            "validator_type": self.validator_type.value,
            "message": self.message,
        }
        if self.skipped:
            d["skipped"] = True
        return d
