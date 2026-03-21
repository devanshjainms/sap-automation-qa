# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Provider package — re-exports from Microsoft Agent Framework.

The custom ``LlmProvider`` protocol and ``AzureOpenAiProvider`` have
been replaced by the Agent Framework's ``AzureOpenAIChatClient``.
This package now just re-exports framework types for convenience.
"""

from agent_framework import Agent, AgentResponse, FunctionTool
from agent_framework.azure import AzureOpenAIChatClient

__all__ = [
    "Agent",
    "AgentResponse",
    "AzureOpenAIChatClient",
    "FunctionTool",
]
