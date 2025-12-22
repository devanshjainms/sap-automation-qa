# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""
SystemContextAgent powered by Semantic Kernel.

This agent uses Semantic Kernel for agentic workspace management
with function calling, replacing the custom tool loop.
"""

from semantic_kernel import Kernel

from src.agents.agents.base import SAPAutomationAgent
import json
from src.agents.workspace.workspace_store import WorkspaceStore
from src.agents.plugins.workspace import WorkspacePlugin
from src.agents.prompts import SYSTEM_CONTEXT_AGENT_SYSTEM_PROMPT
from src.agents.observability import get_logger

logger = get_logger(__name__)


class SystemContextAgentSK(SAPAutomationAgent):
    """Agent for managing SAP QA system workspaces using Semantic Kernel.

    This agent uses SK's native function calling to interact with workspaces,
    allowing the LLM to autonomously choose which workspace operations to perform.
    """

    def __init__(self, kernel: Kernel, workspace_store: WorkspaceStore) -> None:
        """Initialize SystemContextAgent with Semantic Kernel.

        :param kernel: Configured Semantic Kernel instance
        :type kernel: Kernel
        :param workspace_store: WorkspaceStore instance for managing workspaces
        :type workspace_store: WorkspaceStore
        """
        workspace_plugin = WorkspacePlugin(workspace_store)
        super().__init__(
            name="system_context",
            description=(
                "Manages SAP QA system workspaces. Use this agent when the user wants to: "
                "list existing workspaces, find a workspace by SID/environment, "
                "get workspace details, or create a new workspace for testing."
            ),
            kernel=kernel,
            instructions=SYSTEM_CONTEXT_AGENT_SYSTEM_PROMPT,
            plugins=[workspace_plugin],
        )

        # Attach workspace_store after base initialization to avoid pydantic hooks
        object.__setattr__(self, "workspace_store", workspace_store)

        logger.info("SystemContextAgentSK initialized with Workspace plugin")

    def _format_with_source(self, text: str, source: dict) -> dict:
        """Helper to return structured answers with source metadata.

        :param text: assistant content
        :param source: dict describing source file/location
        :returns: dict with content and metadata
        """
        return {"content": text, "metadata": {"sources": [source]}}

    def get_system_configuration(self, sid: str, workspace_hint: str | None = None) -> dict:
        """Retrieve system configuration for a given SID.

        This method will prefer calling the WorkspacePlugin's get_system_configuration
        kernel function (via the plugin instance) to ensure we use the same tool
        the LLM would call. The returned JSON includes 'sources' which we attach
        into the response metadata.
        """
        # Resolve workspace ID
        workspace = None
        if workspace_hint:
            workspace = self.workspace_store.get_workspace(workspace_hint)
        if not workspace:
            candidates = self.workspace_store.find_workspaces_by_sid(sid)
            if len(candidates) == 1:
                workspace = self.workspace_store.get_workspace(candidates[0])
            elif len(candidates) == 0:
                return {"content": f"No workspace found for SID {sid}", "metadata": {"sources": []}}
            else:
                return {"content": f"Multiple workspaces found for SID {sid}: {candidates}", "metadata": {"sources": []}}

        # Use the WorkspacePlugin registered with this agent if available
        workspace_plugin = None
        for p in getattr(self, "plugins", []) or []:
            if isinstance(p, WorkspacePlugin):
                workspace_plugin = p
                break

        if workspace_plugin is None:
            # Fallback to direct store read
            hosts_path = workspace.path / "hosts.yaml"
            content = f"Here is the system configuration for SAP system {sid} (workspace {workspace.workspace_id}).\n\nSee {hosts_path} for details."
            source = {"file": str(hosts_path), "workspace": workspace.workspace_id}
            return self._format_with_source(content, source)

        # Call the plugin's kernel-decorated function directly and parse JSON
        raw = workspace_plugin.get_system_configuration(workspace.workspace_id)
        try:
            parsed = json.loads(raw)
        except Exception:
            return {"content": "Failed to parse system configuration from workspace plugin", "metadata": {"sources": []}}

        # Build a friendly content summary and include parsed fields
        content_lines = [f"System configuration for SID {sid} (workspace {workspace.workspace_id}):"]
        if parsed.get("platform"):
            content_lines.append(f"• Platform: {parsed.get('platform')}")
        if parsed.get("database_high_availability") is not None:
            content_lines.append(f"• Database HA: {parsed.get('database_high_availability')}")
        if parsed.get("scs_high_availability") is not None:
            content_lines.append(f"• SCS HA: {parsed.get('scs_high_availability')}")
        if parsed.get("hosts"):
            content_lines.append(f"• Hosts: {len(parsed.get('hosts'))} entries (see sources)")

        content = "\n".join(content_lines)
        return {"content": content, "metadata": {"sources": parsed.get("sources", [])}, "data": parsed}
