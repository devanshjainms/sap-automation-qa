# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for agent configuration."""

from __future__ import annotations

import pytest

from src.agents.agent_config import (
    GENERAL_CONFIG,
    INVESTIGATOR_SPEC,
    KNOWLEDGE_CONFIG,
    TEST_CONFIG,
    TEST_RUNNER_SPEC,
    TRIAGE_CONFIG,
    AgentConfig,
    InvestigationIntent,
    SpecialistConfig,
    config_for_intent,
)


class TestAgentConfig:
    """Tests for AgentConfig and config_for_intent."""

    def test_config_is_frozen(self) -> None:
        with pytest.raises(AttributeError):
            TRIAGE_CONFIG.max_rounds = 10  # type: ignore[misc]

    def test_triage_config(self) -> None:
        cfg = config_for_intent(InvestigationIntent.TRIAGE)
        assert cfg is TRIAGE_CONFIG
        assert cfg.inject_kb is True
        assert "how_to_investigate" in cfg.module_names
        assert len(cfg.specialists) == 2
        assert cfg.coordinator_turn_limit == 10
        names = {s.name for s in cfg.specialists}
        assert names == {"Investigator", "TestRunner"}

    def test_test_config(self) -> None:
        cfg = config_for_intent(InvestigationIntent.TEST)
        assert cfg is TEST_CONFIG
        assert cfg.inject_kb is False
        assert cfg.max_rounds == 50
        assert "how_to_investigate" not in cfg.module_names
        assert len(cfg.specialists) == 2

    def test_knowledge_config(self) -> None:
        cfg = config_for_intent(InvestigationIntent.KNOWLEDGE)
        assert cfg is KNOWLEDGE_CONFIG
        assert cfg.inject_kb is True
        assert cfg.max_rounds == 30
        assert len(cfg.specialists) == 0

    def test_general_config(self) -> None:
        cfg = config_for_intent(InvestigationIntent.GENERAL)
        assert cfg is GENERAL_CONFIG
        assert cfg.inject_kb is False
        assert len(cfg.specialists) == 0

    def test_specialist_config_frozen(self) -> None:
        with pytest.raises(AttributeError):
            INVESTIGATOR_SPEC.name = "x"  # type: ignore[misc]

    def test_investigator_spec_has_investigate_module(self) -> None:
        assert "how_to_investigate" in INVESTIGATOR_SPEC.module_names
        assert INVESTIGATOR_SPEC.role_prompt != ""

    def test_test_runner_spec_no_investigate_module(self) -> None:
        assert "how_to_investigate" not in TEST_RUNNER_SPEC.module_names
        assert TEST_RUNNER_SPEC.role_prompt != ""
