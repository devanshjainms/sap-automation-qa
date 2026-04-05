# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for provider re-exports and MessageRole values."""

from src.core.models.conversation import MessageRole

# Verify that the providers package re-exports Agent Framework types.
from src.agents.providers import (
    Agent,
    AgentResponse,
    AzureOpenAIChatClient,
    FunctionTool,
)

# ---------------------------------------------------------------------------
# MessageRole (still live in core/models/conversation.py)
# ---------------------------------------------------------------------------


class TestMessageRoleValues:
    """Validate MessageRole values used across the codebase."""

    def test_values(self):
        assert MessageRole.SYSTEM == "system"
        assert MessageRole.USER == "user"
        assert MessageRole.ASSISTANT == "assistant"
        assert MessageRole.TOOL_CALL == "tool_call"
        assert MessageRole.TOOL_RESULT == "tool_result"


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
