# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""AG-UI integration — exposes the SAP multi-agent workflow via AG-UI protocol."""

from __future__ import annotations
import logging
from agent_framework import Workflow
from agent_framework_ag_ui import AgentFrameworkWorkflow
from src.agents.agent import SapAgentFactory

logger = logging.getLogger(__name__)


def create_ag_ui_workflow(factory: SapAgentFactory) -> AgentFrameworkWorkflow:
    """
    Build an ``AgentFrameworkWorkflow`` backed by the SAP multi-agent factory.

    :param factory: Initialised ``SapAgentFactory`` with MCP connections.
    :returns: AG-UI–compatible wrapper that streams AG-UI protocol events.
    """

    def _workflow_factory(thread_id: str) -> Workflow:
        logger.debug("Creating GroupChat workflow for AG-UI thread %s", thread_id)
        return factory.create_workflow()

    return AgentFrameworkWorkflow(
        workflow_factory=_workflow_factory,
        name="SAP-Agent",
        description=(
            "SAP infrastructure assistant — triage, testing, "
            "and operations via multi-agent collaboration."
        ),
    )
