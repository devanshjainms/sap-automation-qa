# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for intent classification and agent configuration."""

from __future__ import annotations

import pytest

from src.agents.agent_config import (
    GENERAL_CONFIG,
    KNOWLEDGE_CONFIG,
    TEST_CONFIG,
    TRIAGE_CONFIG,
    AgentConfig,
    InvestigationIntent,
    classify,
    config_for_intent,
)


class TestClassify:
    """Tests for lightweight intent classification."""

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("investigate the SCS cluster", InvestigationIntent.TRIAGE),
            ("triage HANA failover issue", InvestigationIntent.TRIAGE),
            ("diagnose why node2 is offline", InvestigationIntent.TRIAGE),
            ("cluster status looks wrong", InvestigationIntent.TRIAGE),
            ("node crashed last night", InvestigationIntent.TRIAGE),
            ("resource failed to start", InvestigationIntent.TRIAGE),
            ("troubleshoot split brain", InvestigationIntent.TRIAGE),
        ],
    )
    def test_triage_intent(self, text: str, expected: InvestigationIntent) -> None:
        assert classify(text) == expected

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("run HA test suite on PRD", InvestigationIntent.TEST),
            ("execute functional tests", InvestigationIntent.TEST),
            ("schedule a STAF test", InvestigationIntent.TEST),
            ("run test for DatabaseHighAvailability", InvestigationIntent.TEST),
        ],
    )
    def test_test_intent(self, text: str, expected: InvestigationIntent) -> None:
        assert classify(text) == expected

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("what is SAP Note 2369910?", InvestigationIntent.KNOWLEDGE),
            ("explain best practices for HANA HA", InvestigationIntent.KNOWLEDGE),
            ("what rule checks sysctl?", InvestigationIntent.KNOWLEDGE),
            ("recommend settings for net.ipv4", InvestigationIntent.KNOWLEDGE),
        ],
    )
    def test_knowledge_intent(self, text: str, expected: InvestigationIntent) -> None:
        assert classify(text) == expected

    def test_general_fallback(self) -> None:
        assert classify("hello there") == InvestigationIntent.GENERAL

    def test_empty_input(self) -> None:
        assert classify("") == InvestigationIntent.GENERAL


class TestAgentConfig:
    """Tests for AgentConfig and config_for_intent."""

    def test_config_is_frozen(self) -> None:
        with pytest.raises(AttributeError):
            TRIAGE_CONFIG.max_rounds = 10  # type: ignore[misc]

    def test_triage_config(self) -> None:
        cfg = config_for_intent(InvestigationIntent.TRIAGE)
        assert cfg is TRIAGE_CONFIG
        assert cfg.inject_kb is True
        assert cfg.min_evidence == 3
        assert "how_to_investigate" in cfg.module_names

    def test_test_config(self) -> None:
        cfg = config_for_intent(InvestigationIntent.TEST)
        assert cfg is TEST_CONFIG
        assert cfg.inject_kb is False
        assert cfg.max_rounds == 50
        assert "how_to_investigate" not in cfg.module_names

    def test_knowledge_config(self) -> None:
        cfg = config_for_intent(InvestigationIntent.KNOWLEDGE)
        assert cfg is KNOWLEDGE_CONFIG
        assert cfg.inject_kb is True
        assert cfg.max_rounds == 30

    def test_general_config(self) -> None:
        cfg = config_for_intent(InvestigationIntent.GENERAL)
        assert cfg is GENERAL_CONFIG
        assert cfg.inject_kb is False
