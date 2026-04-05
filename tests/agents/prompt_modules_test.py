# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for prompt module system."""

from __future__ import annotations

import pytest

from src.agents.prompt_modules import (
    ABSOLUTE_RULES,
    CORE_IDENTITY,
    HOW_TO_INVESTIGATE,
    HOW_TO_WORK,
    PAST_EXPERIENCE,
    REMINDERS,
    THINK_ALOUD,
    TOOLS_REFERENCE,
    PromptModule,
    PromptModuleRegistry,
    assemble,
    default_registry,
)


class TestPromptModule:
    """Tests for the PromptModule dataclass."""

    def test_frozen(self) -> None:
        mod = PromptModule(name="x", heading="# X", body="body")
        with pytest.raises(AttributeError):
            mod.name = "y"  # type: ignore[misc]

    def test_default_priority(self) -> None:
        mod = PromptModule(name="x", heading="# X", body="body")
        assert mod.priority == 50

    def test_custom_priority(self) -> None:
        mod = PromptModule(name="x", heading="# X", body="body", priority=5)
        assert mod.priority == 5


class TestPromptModuleRegistry:
    """Tests for the module registry."""

    def test_default_registry_has_builtins(self) -> None:
        names = default_registry.all_names()
        assert "core_identity" in names
        assert "absolute_rules" in names
        assert "reminders" in names

    def test_register_adds_module(self) -> None:
        reg = PromptModuleRegistry()
        custom = PromptModule(name="custom_mod", heading="# Custom", body="hi")
        reg.register(custom)
        assert reg.get("custom_mod") is custom

    def test_register_replaces_existing(self) -> None:
        reg = PromptModuleRegistry()
        v1 = PromptModule(name="x", heading="# X", body="v1")
        v2 = PromptModule(name="x", heading="# X", body="v2")
        reg.register(v1)
        reg.register(v2)
        assert reg.get("x") is v2

    def test_get_missing_returns_none(self) -> None:
        reg = PromptModuleRegistry()
        assert reg.get("nonexistent") is None


class TestAssemble:
    """Tests for the assemble function."""

    def test_all_builtins_included_by_default(self) -> None:
        result = assemble()
        assert "ABSOLUTE RULES" in result
        assert "Think out loud" in result
        assert "How to work" in result
        assert "How to investigate" in result
        assert "Reminders" in result

    def test_selective_modules(self) -> None:
        result = assemble(["core_identity", "reminders"])
        assert "SAP infrastructure specialist" in result
        assert "Never guess or assume" in result
        assert "ABSOLUTE RULES" not in result

    def test_priority_ordering(self) -> None:
        result = assemble()
        identity_pos = result.find("SAP infrastructure specialist")
        rules_pos = result.find("ABSOLUTE RULES")
        reminders_pos = result.find("Reminders")
        assert identity_pos < rules_pos < reminders_pos

    def test_missing_module_skipped(self) -> None:
        result = assemble(["core_identity", "no_such_module"])
        assert "SAP infrastructure specialist" in result

    def test_extra_modules_appended(self) -> None:
        extra = PromptModule(
            name="extra",
            heading="# Extra",
            body="Custom extra content",
            priority=100,
        )
        result = assemble(extra_modules=[extra])
        assert "Custom extra content" in result

    def test_extra_modules_sorted_by_priority(self) -> None:
        early = PromptModule(name="early", heading="", body="EARLY", priority=1)
        late = PromptModule(name="late", heading="", body="LATE", priority=999)
        result = assemble(["core_identity"], extra_modules=[late, early])
        # Extra modules are merged with selected modules and sorted globally.
        # core_identity has priority=0, early=1, late=999.
        assert result.find("SAP infrastructure specialist") < result.find("EARLY")
        assert result.find("EARLY") < result.find("LATE")

    def test_empty_selection_returns_empty(self) -> None:
        result = assemble([])
        assert result == ""

    def test_custom_registry(self) -> None:
        reg = PromptModuleRegistry(modules={})
        reg.register(PromptModule(name="only", heading="", body="Only module"))
        result = assemble(["only"], registry=reg)
        assert result == "Only module"
