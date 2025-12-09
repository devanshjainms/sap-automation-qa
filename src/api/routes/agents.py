# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Agent management API routes."""

from typing import Optional

from fastapi import APIRouter

from src.agents.models import AgentInfo, AgentListResponse
from src.agents.agents.base import AgentRegistry

router = APIRouter(prefix="/agents", tags=["agents"])

# Global agent registry - set by app.py during startup
_agent_registry: Optional[AgentRegistry] = None


def get_agent_registry() -> Optional[AgentRegistry]:
    """Get the global agent registry instance.

    :returns: AgentRegistry instance or None
    :rtype: Optional[AgentRegistry]
    """
    return _agent_registry


def set_agent_registry(registry: AgentRegistry) -> None:
    """Set the global agent registry instance.

    :param registry: AgentRegistry instance to use
    :type registry: AgentRegistry
    """
    global _agent_registry
    _agent_registry = registry


@router.get("", response_model=AgentListResponse)
async def list_agents() -> AgentListResponse:
    """List available agents and their descriptions."""
    if _agent_registry is None:
        return AgentListResponse(agents=[], error="Registry not initialized")

    agents_data = _agent_registry.list_agents()
    agents = [AgentInfo(name=a["name"], description=a["description"]) for a in agents_data]
    return AgentListResponse(agents=agents, error=None)
