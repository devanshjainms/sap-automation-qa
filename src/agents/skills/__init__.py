# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
SAP Agent Skills — discoverable, composable skill packages.

Provides ``build_skills_provider()`` to create a ``SkillsProvider``
with all SAP skills (triage, STAF test, project info) wired to the
application's core services via closures.
"""

from __future__ import annotations

import logging
from typing import Any

from agent_framework import SkillsProvider

from src.agents.skills.project_info import build_project_info_skill
from src.agents.skills.staf_test import build_staf_test_skill
from src.agents.skills.triage import build_triage_skill

logger = logging.getLogger(__name__)


def build_skills_provider(
    sap_context: Any,
    *,
    require_script_approval: bool = True,
) -> SkillsProvider:
    """Build a ``SkillsProvider`` with all SAP agent skills.

    Core services from ``sap_context`` are injected into skill scripts
    via closures — no global state required.

    :param sap_context: ``SapContext`` from the MCP server lifespan,
        providing access to ``triage_executor``, ``analyzer``,
        ``knowledge_store``, ``ssh_cache``, and ``core_api_url``.
    :param require_script_approval: When ``True``, the agent must
        obtain user approval before executing skill scripts (default).
    :returns: Configured ``SkillsProvider`` ready to add to an agent's
        context providers.
    """
    triage = build_triage_skill(sap_context)
    staf_test = build_staf_test_skill(sap_context)
    project_info = build_project_info_skill()

    provider = SkillsProvider(
        skills=[triage, staf_test, project_info],
        require_script_approval=require_script_approval,
    )

    logger.info(
        "Skills provider built: %s",
        [triage.name, staf_test.name, project_info.name],
    )
    return provider
