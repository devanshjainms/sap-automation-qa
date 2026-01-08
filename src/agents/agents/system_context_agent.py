# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""
SystemContextAgent powered by Semantic Kernel.

This agent uses Semantic Kernel for agentic workspace management
with function calling, replacing the custom tool loop.

NOTE: This agent has NO hardcoded methods - all workspace operations
are performed by the LLM autonomously calling WorkspacePlugin tools.
"""

from semantic_kernel import Kernel

from src.agents.agents.base import SAPAutomationAgent
from src.agents.workspace.workspace_store import WorkspaceStore
from src.agents.plugins.workspace import WorkspacePlugin
from src.agents.prompts import SYSTEM_CONTEXT_AGENT_SYSTEM_PROMPT
from src.agents.observability import get_logger

logger = get_logger(__name__)


class SystemContextAgentSK(SAPAutomationAgent):
    """Agent for managing SAP QA system workspaces using Semantic Kernel.

    This agent uses SK's native function calling to interact with workspaces,
    allowing the LLM to autonomously choose which workspace operations to perform.

    All workspace operations are handled via WorkspacePlugin tools:
    - list_workspaces(): List available workspaces
    - workspace_exists(): Check if workspace exists
    - read_workspace_file(): Read hosts.yaml, sap-parameters.yaml, etc.
    - get_system_configuration(): Get full system config
    - create_workspace(): Create new workspace
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

        self.workspace_store: WorkspaceStore = workspace_store
        logger.info("SystemContextAgentSK initialized with Workspace plugin")
