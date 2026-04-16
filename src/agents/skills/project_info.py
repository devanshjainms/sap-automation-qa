# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Project Info Skill — framework knowledge as discoverable resources.

A resource-only skill (no scripts) that provides the agent with
contextual knowledge about the SAP Testing Automation Framework.
All content is sourced from ``strings.py`` for easy customization.
"""

from __future__ import annotations

from agent_framework import Skill, SkillResource

from src.agents.skills.strings import (
    PROJECT_INFO_ARCHITECTURE_CONTENT,
    PROJECT_INFO_CONFIGURATION_CONTENT,
    PROJECT_INFO_DEPLOYMENT_CONTENT,
    PROJECT_INFO_DESCRIPTION,
    PROJECT_INFO_HA_SCENARIOS_CONTENT,
    PROJECT_INFO_INSTRUCTIONS,
    PROJECT_INFO_NAME,
    PROJECT_INFO_RES_ARCHITECTURE_DESC,
    PROJECT_INFO_RES_ARCHITECTURE_NAME,
    PROJECT_INFO_RES_CONFIG_DESC,
    PROJECT_INFO_RES_CONFIG_NAME,
    PROJECT_INFO_RES_DEPLOYMENT_DESC,
    PROJECT_INFO_RES_DEPLOYMENT_NAME,
    PROJECT_INFO_RES_SCENARIOS_DESC,
    PROJECT_INFO_RES_SCENARIOS_NAME,
)


def build_project_info_skill() -> Skill:
    """Build the project info skill with static resources.

    :returns: Configured ``Skill`` instance.
    """
    return Skill(
        name=PROJECT_INFO_NAME,
        description=PROJECT_INFO_DESCRIPTION,
        content=PROJECT_INFO_INSTRUCTIONS,
        resources=[
            SkillResource(
                name=PROJECT_INFO_RES_ARCHITECTURE_NAME,
                description=PROJECT_INFO_RES_ARCHITECTURE_DESC,
                content=PROJECT_INFO_ARCHITECTURE_CONTENT,
            ),
            SkillResource(
                name=PROJECT_INFO_RES_SCENARIOS_NAME,
                description=PROJECT_INFO_RES_SCENARIOS_DESC,
                content=PROJECT_INFO_HA_SCENARIOS_CONTENT,
            ),
            SkillResource(
                name=PROJECT_INFO_RES_CONFIG_NAME,
                description=PROJECT_INFO_RES_CONFIG_DESC,
                content=PROJECT_INFO_CONFIGURATION_CONTENT,
            ),
            SkillResource(
                name=PROJECT_INFO_RES_DEPLOYMENT_NAME,
                description=PROJECT_INFO_RES_DEPLOYMENT_DESC,
                content=PROJECT_INFO_DEPLOYMENT_CONTENT,
            ),
        ],
    )
