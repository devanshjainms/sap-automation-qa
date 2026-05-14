# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Validator type definitions for rule specifications."""

from enum import StrEnum


class ValidatorType(StrEnum):
    """Strategy for validating an evidence value against a rule."""

    EXACT_MATCH = "exact_match"
    MIN_VALUE = "min_value"
    RANGE = "range"
    REGEX = "regex"
    PRESENCE = "presence"
    CUSTOM = "custom"
