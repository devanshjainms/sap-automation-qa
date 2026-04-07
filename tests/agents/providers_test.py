# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for provider re-exports."""

# Verify that the providers package re-exports Agent Framework types.
from src.agents.providers import (
    Agent,
    AgentResponse,
    AzureOpenAIChatClient,
    FunctionTool,
)


# ---------------------------------------------------------------------------
# Provider re-export tests
# ---------------------------------------------------------------------------


class TestProviderReExports:
    """Verify the providers package re-exports Agent Framework types."""

    def test_agent_type(self):
        from agent_framework import Agent as OrigAgent

        assert Agent is OrigAgent

    def test_agent_response_type(self):
        from agent_framework import AgentResponse as OrigResp

        assert AgentResponse is OrigResp

    def test_function_tool_type(self):
        from agent_framework import FunctionTool as OrigFT

        assert FunctionTool is OrigFT

    def test_azure_client_type(self):
        from agent_framework.azure import (
            AzureOpenAIChatClient as OrigClient,
        )

        assert AzureOpenAIChatClient is OrigClient
