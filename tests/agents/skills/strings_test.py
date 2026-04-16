# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for skill string constants."""

from __future__ import annotations

import pytest

from src.agents.skills import strings

_ALL_STRING_NAMES = [name for name in dir(strings) if name.isupper() and not name.startswith("_")]


class TestStringConstants:
    """Validate that all skill string constants are well-formed."""

    @pytest.mark.parametrize("name", _ALL_STRING_NAMES)
    def test_non_empty(self, name: str) -> None:
        """Every exported constant must be a non-empty string."""
        value = getattr(strings, name)
        assert isinstance(value, str), f"{name} is not a string"
        assert value.strip(), f"{name} is empty or whitespace"

    def test_skill_names_are_kebab_case(self) -> None:
        """Skill names must be lowercase kebab-case (a-z, 0-9, -)."""
        import re

        pattern = re.compile(r"^[a-z][a-z0-9-]*$")
        for name in _ALL_STRING_NAMES:
            if name.endswith("_NAME") and not name.endswith("_RES_"):
                value = getattr(strings, name)
                if "RES_" not in name and "SCRIPT_" not in name:
                    assert pattern.match(value), f"{name}={value!r} is not kebab-case"

    def test_no_duplicate_skill_names(self) -> None:
        """Skill names must be unique."""
        names = [
            getattr(strings, n)
            for n in _ALL_STRING_NAMES
            if n.endswith("_NAME") and "RES_" not in n and "SCRIPT_" not in n
        ]
        assert len(names) == len(set(names)), f"Duplicate skill names: {names}"

    def test_descriptions_under_500_chars(self) -> None:
        """Descriptions should be concise (under 500 chars)."""
        for name in _ALL_STRING_NAMES:
            if name.endswith("_DESC") or name.endswith("_DESCRIPTION"):
                value = getattr(strings, name)
                assert len(value) < 500, f"{name} is {len(value)} chars (max 500)"
