# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""Semantic Kernel-powered Test Advisor agent.

This agent recommends/selects tests and produces a structured TestPlan.
It does NOT produce executable jobs.
"""

from __future__ import annotations

from semantic_kernel import Kernel

from src.agents.agents.base import SAPAutomationAgent
from src.agents.observability import get_logger
from src.agents.plugins.test import TestPlannerPlugin
from src.agents.prompts import TEST_ADVISOR_AGENT_SYSTEM_PROMPT
from src.agents.workspace.workspace_store import WorkspaceStore

logger = get_logger(__name__)


class TestAdvisorAgentSK(SAPAutomationAgent):
    """Recommends tests and generates TestPlan (no execution jobs)."""

    def __init__(self, kernel: Kernel, workspace_store: WorkspaceStore):
        self.workspace_store = workspace_store

        self.test_planner_plugin = TestPlannerPlugin()
        super().__init__(
            name="test_advisor",
            description=(
                "Recommends SAP HA tests based on workspace configuration and generates a TestPlan. "
                "Does not execute and does not generate ActionPlan jobs."
            ),
            kernel=kernel,
            instructions=TEST_ADVISOR_AGENT_SYSTEM_PROMPT,
            plugins=[self.test_planner_plugin],
        )

        logger.info("TestAdvisorAgentSK initialized")
