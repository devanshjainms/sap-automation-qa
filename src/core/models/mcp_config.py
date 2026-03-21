# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""MCP server configuration models.

Defines the schema for ``WORKSPACES/CONFIG/mcp_servers.yaml``
including per-server tool filtering, safety annotations, and
preamble hints (Section 4.8 of STAF.md).
"""

from enum import Enum
from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, Field


class SafetyTier(str, Enum):
    """Per-server safety annotation (Section 4.8.2).

    Controls how the agent treats tool calls from this server.
    """

    READ_ONLY = "read_only"
    CONFIRM_WRITES = "confirm_writes"
    CONFIRM_ALL = "confirm_all"


class BearerAuth(BaseModel):
    """Bearer token authentication config."""

    type: Literal["bearer"] = "bearer"
    token_env: str = Field(description="Environment variable holding the bearer token")


class McpServerEntry(BaseModel):
    """Configuration for a single external MCP server.

    :param name: Human-readable server name (unique identifier).
    :param url: Server URL (e.g., ``http://localhost:8001``).
    :param auth: Authentication method.
    :param safety: Safety tier for this server's tools.
    :param tools: Tool filtering config.
    :param preamble_hint: Text injected into the agent's capability
        layer describing when/how to use this server's tools.
    :param enabled: Whether this server is active.
    """

    name: str
    url: str
    auth: Union[str, BearerAuth] = "none"
    safety: SafetyTier = SafetyTier.READ_ONLY
    tools: dict[str, Any] = Field(
        default_factory=lambda: {"allow": "all"},
        description="Tool filtering. ``allow: all`` or ``allow: [prefix1, prefix2]``",
    )
    preamble_hint: str = ""
    enabled: bool = True

    @property
    def tool_allow_list(self) -> Optional[list[str]]:
        """Return the tool allow-list, or None if all tools are allowed."""
        allow = self.tools.get("allow", "all")
        if allow == "all":
            return None
        if isinstance(allow, list):
            return allow
        return None

    def tool_is_allowed(self, tool_name: str) -> bool:
        """Check whether a tool name passes this server's filter.

        :param tool_name: MCP tool name to check.
        :returns: True if the tool is allowed.
        """
        prefixes = self.tool_allow_list
        if prefixes is None:
            return True
        return any(prefix in tool_name for prefix in prefixes)


class McpServersConfig(BaseModel):
    """Top-level schema for ``mcp_servers.yaml``.

    :param servers: List of external MCP server configurations.
    """

    servers: list[McpServerEntry] = Field(default_factory=list)

    @property
    def enabled_servers(self) -> list[McpServerEntry]:
        """Return only enabled server entries."""
        return [s for s in self.servers if s.enabled]
