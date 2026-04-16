# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for the project info skill."""

from __future__ import annotations

from src.agents.skills.project_info import build_project_info_skill
from src.agents.skills.strings import (
    PROJECT_INFO_ARCHITECTURE_CONTENT,
    PROJECT_INFO_CONFIGURATION_CONTENT,
    PROJECT_INFO_DEPLOYMENT_CONTENT,
    PROJECT_INFO_HA_SCENARIOS_CONTENT,
)


class TestBuildProjectInfoSkill:
    """Tests for build_project_info_skill factory."""

    def test_skill_metadata(self) -> None:
        skill = build_project_info_skill()
        assert skill.name == "project-info"
        assert skill.description
        assert skill.content
        assert len(skill.resources) == 4
        assert skill.scripts == [] or len(skill.scripts) == 0

    def test_resource_names(self) -> None:
        skill = build_project_info_skill()
        names = [r.name for r in skill.resources]
        assert "architecture" in names
        assert "ha-test-scenarios" in names
        assert "configuration" in names
        assert "deployment" in names

    def test_architecture_resource(self) -> None:
        skill = build_project_info_skill()
        resource = next(r for r in skill.resources if r.name == "architecture")
        assert resource.content == PROJECT_INFO_ARCHITECTURE_CONTENT
        assert "Technology Stack" in resource.content

    def test_ha_scenarios_resource(self) -> None:
        skill = build_project_info_skill()
        resource = next(r for r in skill.resources if r.name == "ha-test-scenarios")
        assert resource.content == PROJECT_INFO_HA_SCENARIOS_CONTENT
        assert "HANA Database HA" in resource.content
        assert "Central Services HA" in resource.content

    def test_configuration_resource(self) -> None:
        skill = build_project_info_skill()
        resource = next(r for r in skill.resources if r.name == "configuration")
        assert resource.content == PROJECT_INFO_CONFIGURATION_CONTENT
        assert "Workspace Structure" in resource.content

    def test_deployment_resource(self) -> None:
        skill = build_project_info_skill()
        resource = next(r for r in skill.resources if r.name == "deployment")
        assert resource.content == PROJECT_INFO_DEPLOYMENT_CONTENT
        assert "Docker" in resource.content
