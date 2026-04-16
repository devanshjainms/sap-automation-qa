# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for the skills __init__ module (build_skills_provider)."""

from __future__ import annotations

from unittest.mock import MagicMock

from agent_framework import SkillsProvider

from src.agents.skills import build_skills_provider


def _make_sap_context() -> MagicMock:
    ctx = MagicMock()
    ctx.workspaces_base = "/tmp"
    ctx.core_api_url = "http://localhost:8000"
    ctx.knowledge_store.load_evidence_definitions.return_value = []
    return ctx


class TestBuildSkillsProvider:
    """Tests for build_skills_provider factory."""

    def test_returns_skills_provider(self) -> None:
        provider = build_skills_provider(_make_sap_context())
        assert isinstance(provider, SkillsProvider)

    def test_has_three_skills(self) -> None:
        provider = build_skills_provider(_make_sap_context())
        assert len(provider._skills) == 3

    def test_skill_names(self) -> None:
        provider = build_skills_provider(_make_sap_context())
        assert set(provider._skills.keys()) == {
            "sap-triage",
            "sap-staf-test",
            "project-info",
        }

    def test_builds_without_error_with_approval_default(self) -> None:
        provider = build_skills_provider(_make_sap_context())
        assert provider is not None

    def test_builds_without_error_approval_disabled(self) -> None:
        provider = build_skills_provider(_make_sap_context(), require_script_approval=False)
        assert provider is not None
