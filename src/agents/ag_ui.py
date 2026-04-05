# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""AG-UI integration — exposes the SAP agent via the official
``add_agent_framework_fastapi_endpoint`` from the Agent Framework.

Persistence is handled by ``ConversationHistoryProvider`` inside
the agent's context providers — the framework manages everything.
"""

from __future__ import annotations
import logging
from typing import Optional
from fastapi import FastAPI
from agent_framework_ag_ui import AgentFrameworkAgent, add_agent_framework_fastapi_endpoint
from src.agents.agent import SapAgentFactory
from src.agents.agent_config import TRIAGE_CONFIG

logger = logging.getLogger(__name__)


def register_ag_ui(
    app: FastAPI,
    factory: SapAgentFactory,
    path: str = "/ag-ui",
    allow_origins: Optional[list[str]] = None,
) -> None:
    """Register the AG-UI endpoint using the official framework function.

    Creates an ``AgentFrameworkAgent`` wrapper around our SAP agent
    and registers it via ``add_agent_framework_fastapi_endpoint``.
    Session management uses ``service_session`` so the AG-UI
    ``thread_id`` maps to our conversation ID for persistence.

    :param app: The FastAPI application.
    :param factory: Agent factory with MCP connections.
    :param path: Endpoint path (default ``/ag-ui``).
    :param allow_origins: CORS origins.
    """
    agent = factory.create_agent(config=TRIAGE_CONFIG)
    ag_ui_agent = AgentFrameworkAgent(
        agent=agent,
        name="SAP-Agent",
        description=(
            "SAP infrastructure specialist — investigates system "
            "health, runs diagnostics, manages HA tests and schedules."
        ),
        use_service_session=True,
    )

    add_agent_framework_fastapi_endpoint(
        app,
        ag_ui_agent,
        path,
        allow_origins=allow_origins,
    )
    logger.info("AG-UI endpoint registered at %s", path)
