# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Workspace models."""

from typing import List, Any
from pydantic import BaseModel
from agent_framework import BaseContextProvider


class WorkspaceInfo(BaseModel):
    """Workspace information."""

    id: str
    name: str
    environment: str = ""
    path: str = ""
    config_exists: bool = False


class WorkspaceConfig(BaseModel):
    """Whitelisted workspace configuration fields safe for UI display."""

    sap_sid: str = ""
    db_sid: str = ""
    platform: str = ""
    db_instance_number: str = ""
    scs_instance_number: str = ""
    ers_instance_number: str = ""
    database_high_availability: bool = False
    scs_high_availability: bool = False
    database_cluster_type: str = ""
    scs_cluster_type: str = ""
    database_scale_out: bool = False
    nfs_provider: str = ""
    hosts: List[str] = []


class TestReport(BaseModel):
    """Metadata for an HTML test report file."""

    filename: str
    modified_at: str
    size_bytes: int


class WorkspaceListResponse(BaseModel):
    """Response containing list of workspaces."""

    workspaces: List[WorkspaceInfo]
    total: int


class WorkspaceContextProvider(BaseContextProvider):
    """Injects workspace context into agent instructions.

    Per the Agent Framework context provider pattern, this provider
    adds workspace-specific instructions before each agent run so
    the agent knows which SAP system the user is working with.

    :param workspace_context: Context string (e.g. workspace ID).
    """

    def __init__(self, workspace_context: str) -> None:
        super().__init__("workspace-context")
        self._context = workspace_context

    async def before_run(
        self,
        *,
        agent: Any,
        session: Any,
        context: Any,
        state: dict[str, Any],
    ) -> None:
        """Inject workspace context as additional instructions."""
        if self._context:
            context.extend_instructions(
                self.source_id,
                self._context,
            )
