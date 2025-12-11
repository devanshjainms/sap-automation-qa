# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""
Echo agent powered by Semantic Kernel for documentation assistance.

This agent uses Semantic Kernel with DocumentationPlugin for intelligent
documentation-based help using function calling.
"""

from semantic_kernel import Kernel

from src.agents.agents.base import BaseSKAgent, TracingPhase
from src.agents.plugins.documentation import DocumentationPlugin
from src.agents.prompts import ECHO_AGENT_SK_SYSTEM_PROMPT
from src.agents.observability import get_logger

logger = get_logger(__name__)


class EchoAgentSK(BaseSKAgent):
    """Agent for providing documentation-based help using Semantic Kernel.

    This agent uses SK's native function calling to interact with documentation,
    allowing the LLM to autonomously choose which documentation to retrieve.
    """

    def __init__(self, kernel: Kernel) -> None:
        """Initialize EchoAgent with Semantic Kernel.

        :param kernel: Configured Semantic Kernel instance
        :type kernel: Kernel
        """
        super().__init__(
            name="echo",
            description=(
                "Provides general help, documentation, and information about the framework. "
                "Use for greetings, general questions, or when user intent is unclear. "
                "NEVER use this agent for executing tests or running commands."
            ),
            kernel=kernel,
            system_prompt=ECHO_AGENT_SK_SYSTEM_PROMPT,
        )

        documentation_plugin = DocumentationPlugin()
        self.kernel.add_plugin(plugin=documentation_plugin, plugin_name="Documentation")

        logger.info("EchoAgentSK initialized with Documentation plugin")

    def _get_tracing_phase(self) -> TracingPhase:
        """Return documentation_retrieval as the primary tracing phase."""
        return "documentation_retrieval"
