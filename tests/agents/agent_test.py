# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for ``SapAgentFactory``."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from agent_framework import MCPStreamableHTTPTool, TokenBudgetComposedStrategy

from src.agents.agent import SapAgentFactory
from src.core.models.mcp_config import (
    BearerAuth,
    McpServerEntry,
    McpServersConfig,
)

# ---------------------------------------------------------------------------
# Helpers — mock MCPStreamableHTTPTool
# ---------------------------------------------------------------------------


def _make_mock_mcp_tool(name: str = "sap-test", n_functions: int = 3):
    """Create a mock MCPStreamableHTTPTool with fake functions."""
    tool = AsyncMock(spec=MCPStreamableHTTPTool)
    tool.name = name
    tool.functions = [MagicMock() for _ in range(n_functions)]
    tool.connect = AsyncMock()
    tool.close = AsyncMock()
    return tool


def _mock_as_agent(**kwargs):
    """Create a mock agent that preserves the ``name`` kwarg.

    ``HandoffBuilder`` uses ``agent.name`` for routing and JSON
    serialization, so the mock must carry a real string.
    """
    m = MagicMock()
    m.name = kwargs.get("name", "mock-agent")
    m.description = kwargs.get("description", "")
    return m


class _MockHandoffBuilder:
    """Lightweight HandoffBuilder stand-in that accepts MagicMock agents."""

    last_instance: "_MockHandoffBuilder | None" = None

    def __init__(self, **kwargs):
        self._kwargs = kwargs
        self._participants = kwargs.get("participants", [])
        self.autonomous_mode_kwargs: dict | None = None
        _MockHandoffBuilder.last_instance = self

    def with_start_agent(self, agent):
        return self

    def add_handoff(self, source, targets, **kwargs):
        return self

    def with_autonomous_mode(self, **kwargs):
        self.autonomous_mode_kwargs = kwargs
        return self

    def build(self):
        return MagicMock(name="mock-workflow")


# ---------------------------------------------------------------------------
# Tests — SapAgentFactory
# ---------------------------------------------------------------------------


@patch("src.agents.agent.HandoffBuilder", _MockHandoffBuilder)
class TestSapAgentFactory:
    """Tests for the ``SapAgentFactory`` class."""

    @pytest.mark.asyncio
    async def test_create_connects_mcp_tools(self) -> None:
        """Factory creates SAP MCP + Microsoft Learn MCP tools."""
        fake_tool = MagicMock()
        fake_tool.name = "fake_tool"
        with (
            patch("src.agents.agent.MCPStreamableHTTPTool") as mock_cls,
            patch(
                "src.agents.agent._mcp_server._tool_manager.list_tools",
                return_value=[fake_tool],
            ),
        ):
            mock_cls.return_value = _make_mock_mcp_tool("sap-tools")

            factory = await SapAgentFactory.create(
                mcp_url="http://test:8001/mcp",
                endpoint="https://x.openai.azure.com",
            )

        # SAP MCP + Microsoft Learn MCP = 2 connections
        assert mock_cls.call_count == 2
        sap_call = mock_cls.call_args_list[0]
        assert sap_call[1]["name"] == "sap-tools"
        assert sap_call[1]["url"] == "http://test:8001/mcp"
        assert sap_call[1]["allowed_tools"] == ["fake_tool"]

    @pytest.mark.asyncio
    async def test_mcp_url_property(self) -> None:
        with patch("src.agents.agent.MCPStreamableHTTPTool") as mock_cls:
            mock_cls.return_value = _make_mock_mcp_tool()
            factory = await SapAgentFactory.create(
                mcp_url="http://custom:9999/mcp",
            )
        assert factory.mcp_url == "http://custom:9999/mcp"

    @pytest.mark.asyncio
    async def test_tool_counts(self) -> None:
        """tool_counts returns function count."""
        tool = _make_mock_mcp_tool("sap-tools", 20)

        with patch("src.agents.agent.MCPStreamableHTTPTool") as mock_cls:
            mock_cls.return_value = tool
            factory = await SapAgentFactory.create(
                mcp_url="http://test:8001/mcp",
            )

        counts = factory.tool_counts
        assert counts["sap"] == 20

    @patch("src.agents.agent.AzureOpenAIChatClient")
    @pytest.mark.asyncio
    async def test_create_workflow_returns_workflow(
        self,
        mock_client_cls: MagicMock,
    ) -> None:
        mock_client_cls.return_value.as_agent.side_effect = _mock_as_agent

        with patch("src.agents.agent.MCPStreamableHTTPTool") as mock_mcp:
            mock_mcp.return_value = _make_mock_mcp_tool()
            factory = await SapAgentFactory.create(
                mcp_url="http://test:8001/mcp",
                endpoint="https://x.openai.azure.com",
            )

        result = factory.create_workflow()
        assert result is not None

    @patch("src.agents.agent.AzureOpenAIChatClient")
    @pytest.mark.asyncio
    async def test_general_intent_builds_single_agent(
        self,
        mock_client_cls: MagicMock,
    ) -> None:
        """GENERAL intent creates a single SAP-Agent."""
        mock_client_cls.return_value.as_agent.side_effect = _mock_as_agent

        with patch("src.agents.agent.MCPStreamableHTTPTool") as mock_mcp:
            mock_mcp.return_value = _make_mock_mcp_tool()
            factory = await SapAgentFactory.create(
                mcp_url="http://test:8001/mcp",
                endpoint="https://x.openai.azure.com",
            )

        factory.create_workflow()

        assert mock_client_cls.return_value.as_agent.call_count == 1
        call = mock_client_cls.return_value.as_agent.call_args
        assert call[1]["name"] == "SAP-Agent"

    @patch("src.agents.agent.AzureOpenAIChatClient")
    @pytest.mark.asyncio
    async def test_single_agent_has_autonomous_mode(
        self,
        mock_client_cls: MagicMock,
    ) -> None:
        """Single-agent workflow enables autonomous mode with turn limits."""
        mock_client_cls.return_value.as_agent.side_effect = _mock_as_agent

        with patch("src.agents.agent.MCPStreamableHTTPTool") as mock_mcp:
            mock_mcp.return_value = _make_mock_mcp_tool()
            factory = await SapAgentFactory.create(
                mcp_url="http://test:8001/mcp",
                endpoint="https://x.openai.azure.com",
            )

        factory.create_workflow()

        hb = _MockHandoffBuilder.last_instance
        assert hb is not None
        assert hb.autonomous_mode_kwargs is not None
        assert "SAP-Agent" in hb.autonomous_mode_kwargs["turn_limits"]

    @patch("src.agents.agent.AzureOpenAIChatClient")
    @pytest.mark.asyncio
    async def test_handoff_turn_limits_from_config(
        self,
        mock_client_cls: MagicMock,
    ) -> None:
        """Handoff workflow reads turn limits from config."""
        mock_client_cls.return_value.as_agent.side_effect = _mock_as_agent

        with patch("src.agents.agent.MCPStreamableHTTPTool") as mock_mcp:
            mock_mcp.return_value = _make_mock_mcp_tool()
            factory = await SapAgentFactory.create(
                mcp_url="http://test:8001/mcp",
                endpoint="https://x.openai.azure.com",
            )

        from src.agents.agent_config import TRIAGE_CONFIG

        factory.create_workflow(config=TRIAGE_CONFIG)

        hb = _MockHandoffBuilder.last_instance
        assert hb is not None
        limits = hb.autonomous_mode_kwargs["turn_limits"]
        assert limits["Coordinator"] == TRIAGE_CONFIG.coordinator_turn_limit
        assert limits["Investigator"] == TRIAGE_CONFIG.max_rounds
        assert limits["TestRunner"] == TRIAGE_CONFIG.max_rounds

    @patch("src.agents.agent.AzureOpenAIChatClient")
    @pytest.mark.asyncio
    async def test_triage_intent_builds_handoff_agents(
        self,
        mock_client_cls: MagicMock,
    ) -> None:
        """TRIAGE intent creates Coordinator + Investigator + TestRunner."""
        mock_client_cls.return_value.as_agent.side_effect = _mock_as_agent

        with patch("src.agents.agent.MCPStreamableHTTPTool") as mock_mcp:
            mock_mcp.return_value = _make_mock_mcp_tool()
            factory = await SapAgentFactory.create(
                mcp_url="http://test:8001/mcp",
                endpoint="https://x.openai.azure.com",
            )

        from src.agents.agent_config import TRIAGE_CONFIG

        factory.create_workflow(config=TRIAGE_CONFIG)

        assert mock_client_cls.return_value.as_agent.call_count == 3
        calls = mock_client_cls.return_value.as_agent.call_args_list
        names = {c[1]["name"] for c in calls}
        assert names == {"Coordinator", "Investigator", "TestRunner"}

    @patch("src.agents.agent.AzureOpenAIChatClient")
    @pytest.mark.asyncio
    async def test_agent_receives_mcp_tool(
        self,
        mock_client_cls: MagicMock,
    ) -> None:
        """The agent gets the MCPStreamableHTTPTool in tools=."""
        mock_client_cls.return_value.as_agent.side_effect = _mock_as_agent

        mcp_tool = _make_mock_mcp_tool("sap-tools")

        with patch("src.agents.agent.MCPStreamableHTTPTool") as mock_cls:
            mock_cls.return_value = mcp_tool
            factory = await SapAgentFactory.create(
                mcp_url="http://test:8001/mcp",
                endpoint="https://x.openai.azure.com",
            )

        factory.create_workflow()

        # Single-agent (GENERAL) gets all tools.
        call = mock_client_cls.return_value.as_agent.call_args
        assert mcp_tool in call[1]["tools"]

    @patch("src.agents.agent.AzureOpenAIChatClient")
    @pytest.mark.asyncio
    async def test_workspace_context_provider_added(
        self,
        mock_client_cls: MagicMock,
    ) -> None:
        """Workspace context is injected via a context provider."""
        mock_client_cls.return_value.as_agent.side_effect = _mock_as_agent

        with patch("src.agents.agent.MCPStreamableHTTPTool") as mock_mcp:
            mock_mcp.return_value = _make_mock_mcp_tool()
            factory = await SapAgentFactory.create(
                mcp_url="http://test:8001/mcp",
                endpoint="https://x.openai.azure.com",
            )

            factory.create_workflow(
                workspace_context="Workspace: PRD",
            )

        # Single agent gets the workspace context provider.
        call = mock_client_cls.return_value.as_agent.call_args
        providers = call[1]["context_providers"]
        from src.agents.agent import WorkspaceContextProvider

        assert any(isinstance(p, WorkspaceContextProvider) for p in providers)

    @patch("src.agents.agent.AzureOpenAIChatClient")
    @pytest.mark.asyncio
    async def test_agent_receives_compaction_strategy(
        self,
        mock_client_cls: MagicMock,
    ) -> None:
        """Agent gets a compaction strategy."""
        mock_client_cls.return_value.as_agent.side_effect = _mock_as_agent

        with patch("src.agents.agent.MCPStreamableHTTPTool") as mock_mcp:
            mock_mcp.return_value = _make_mock_mcp_tool()
            factory = await SapAgentFactory.create(
                mcp_url="http://test:8001/mcp",
                endpoint="https://x.openai.azure.com",
            )

            factory.create_workflow()

        # Single agent gets the compaction strategy.
        call = mock_client_cls.return_value.as_agent.call_args
        strategy = call[1].get("compaction_strategy")
        assert isinstance(strategy, TokenBudgetComposedStrategy)

    @patch("src.agents.agent.AzureOpenAIChatClient")
    @pytest.mark.asyncio
    async def test_client_receives_kwargs(
        self,
        mock_client_cls: MagicMock,
    ) -> None:
        """AzureOpenAIChatClient receives endpoint/deployment/key."""
        mock_client_cls.return_value.as_agent.side_effect = _mock_as_agent

        with patch("src.agents.agent.MCPStreamableHTTPTool") as mock_mcp:
            mock_mcp.return_value = _make_mock_mcp_tool()
            factory = await SapAgentFactory.create(
                mcp_url="http://test:8001/mcp",
                endpoint="https://my.openai.azure.com",
                deployment_name="gpt-4o",
                api_key="key-123",
                api_version="2025-01-01",
            )

            factory.create_workflow()

        client_kwargs = mock_client_cls.call_args[1]
        assert client_kwargs["endpoint"] == "https://my.openai.azure.com"
        assert client_kwargs["deployment_name"] == "gpt-4o"
        assert client_kwargs["api_key"] == "key-123"
        assert client_kwargs["api_version"] == "2025-01-01"

    @pytest.mark.asyncio
    async def test_omits_none_client_kwargs(self) -> None:
        with patch("src.agents.agent.MCPStreamableHTTPTool") as mock_mcp:
            mock_mcp.return_value = _make_mock_mcp_tool()
            factory = await SapAgentFactory.create(
                mcp_url="http://test:8001/mcp",
            )
        assert "endpoint" not in factory._client_kwargs
        assert "api_key" not in factory._client_kwargs

    @pytest.mark.asyncio
    async def test_close_shuts_tool(self) -> None:
        """close() calls close on MCP tools."""
        tool = _make_mock_mcp_tool("sap-tools")

        with patch("src.agents.agent.MCPStreamableHTTPTool") as mock_cls:
            mock_cls.return_value = tool
            factory = await SapAgentFactory.create(
                mcp_url="http://test:8001/mcp",
            )

        await factory.close()

        # SAP MCP tool closed; mslearn closed via _external_mcps
        assert tool.close.await_count >= 1

    @pytest.mark.asyncio
    async def test_async_context_manager(self) -> None:
        """Can be used as ``async with`` context manager."""
        with patch("src.agents.agent.MCPStreamableHTTPTool") as mock_mcp:
            mock_tool = _make_mock_mcp_tool()
            mock_mcp.return_value = mock_tool
            factory = await SapAgentFactory.create(
                mcp_url="http://test:8001/mcp",
            )

        async with factory as f:
            assert f is factory

        assert mock_tool.close.await_count >= 1


# ---------------------------------------------------------------------------
# Tests — SapAgentFactory external MCP servers
# ---------------------------------------------------------------------------


class TestSapAgentFactoryExternal:
    """Tests for external MCP server connection."""

    @pytest.mark.asyncio
    async def test_connects_external_servers(self) -> None:
        """External servers from mcp_config are connected."""
        ext_tool = _make_mock_mcp_tool("azure-monitor", 5)
        config = McpServersConfig(
            servers=[
                McpServerEntry(
                    name="azure-monitor",
                    url="http://monitor:8002/mcp",
                )
            ]
        )

        tools_created = []

        def _track_mcp(**kwargs):
            if kwargs.get("name") == "azure-monitor":
                tools_created.append(ext_tool)
                return ext_tool
            return _make_mock_mcp_tool(kwargs.get("name", ""))

        with patch(
            "src.agents.agent.MCPStreamableHTTPTool",
            side_effect=_track_mcp,
        ):
            factory = await SapAgentFactory.create(
                mcp_url="http://test:8001/mcp",
                mcp_config=config,
            )

        counts = factory.tool_counts
        assert counts.get("azure-monitor") == 5
        ext_tool.connect.assert_awaited()

    @pytest.mark.asyncio
    async def test_external_connection_failure_graceful(self) -> None:
        """Failed external connection is logged, not raised."""
        config = McpServersConfig(
            servers=[
                McpServerEntry(
                    name="broken",
                    url="http://down:9999/mcp",
                )
            ]
        )

        call_count = 0

        def _fail_on_external(**kwargs):
            nonlocal call_count
            call_count += 1
            tool = _make_mock_mcp_tool(
                kwargs.get("name", ""),
            )
            if kwargs.get("name") == "broken":
                tool.connect.side_effect = ConnectionError("refused")
            return tool

        with patch(
            "src.agents.agent.MCPStreamableHTTPTool",
            side_effect=_fail_on_external,
        ):
            factory = await SapAgentFactory.create(
                mcp_url="http://test:8001/mcp",
                mcp_config=config,
            )

        assert "broken" not in factory.tool_counts

    @pytest.mark.asyncio
    async def test_bearer_auth_creates_http_client(self) -> None:
        """Bearer auth builds httpx client with Authorization header."""
        config = McpServersConfig(
            servers=[
                McpServerEntry(
                    name="secure",
                    url="http://secure:8002/mcp",
                    auth=BearerAuth(token_env="MY_TOKEN"),
                )
            ]
        )

        captured_kwargs: list[dict] = []

        def _capture(**kwargs):
            captured_kwargs.append(kwargs)
            return _make_mock_mcp_tool(
                kwargs.get("name", ""),
            )

        with (
            patch(
                "src.agents.agent.MCPStreamableHTTPTool",
                side_effect=_capture,
            ),
            patch.dict("os.environ", {"MY_TOKEN": "secret-123"}),
        ):
            await SapAgentFactory.create(
                mcp_url="http://test:8001/mcp",
                mcp_config=config,
            )

        # Find the call for the "secure" external server
        ext_call = next(k for k in captured_kwargs if k.get("name") == "secure")
        http_client = ext_call.get("http_client")
        assert http_client is not None
        auth_header = http_client.headers.get("authorization")
        assert auth_header == "Bearer secret-123"

    @pytest.mark.asyncio
    async def test_disabled_server_skipped(self) -> None:
        """Disabled external servers are not connected to."""
        config = McpServersConfig(
            servers=[
                McpServerEntry(
                    name="off",
                    url="http://off:8001/mcp",
                    enabled=False,
                )
            ]
        )

        with patch("src.agents.agent.MCPStreamableHTTPTool") as mock_cls:
            mock_cls.return_value = _make_mock_mcp_tool()
            factory = await SapAgentFactory.create(
                mcp_url="http://test:8001/mcp",
                mcp_config=config,
            )

        # SAP MCP + Microsoft Learn MCP (no external disabled)
        assert mock_cls.call_count == 2
        assert "off" not in factory.tool_counts


# ---------------------------------------------------------------------------
# Tests — Intent classification (LLM-based)
# ---------------------------------------------------------------------------


class TestClassifyIntent:
    """Tests for ``SapAgentFactory.classify_intent``."""

    @pytest.mark.asyncio
    async def test_triage_intent(self) -> None:
        """LLM returning 'triage' maps to TRIAGE."""
        response = MagicMock()
        response.text = "triage"

        with patch("src.agents.agent.MCPStreamableHTTPTool") as mock_mcp:
            mock_mcp.return_value = _make_mock_mcp_tool()
            factory = await SapAgentFactory.create(
                mcp_url="http://test:8001/mcp",
                endpoint="https://x.openai.azure.com",
            )

        with patch("src.agents.agent.AzureOpenAIChatClient") as mock_client:
            mock_client.return_value.get_response = AsyncMock(return_value=response)
            result = await factory.classify_intent("investigate cluster failure")

        from src.agents.agent_config import InvestigationIntent

        assert result == InvestigationIntent.TRIAGE

    @pytest.mark.asyncio
    async def test_test_intent(self) -> None:
        """LLM returning 'test' maps to TEST."""
        response = MagicMock()
        response.text = "test"

        with patch("src.agents.agent.MCPStreamableHTTPTool") as mock_mcp:
            mock_mcp.return_value = _make_mock_mcp_tool()
            factory = await SapAgentFactory.create(
                mcp_url="http://test:8001/mcp",
                endpoint="https://x.openai.azure.com",
            )

        with patch("src.agents.agent.AzureOpenAIChatClient") as mock_client:
            mock_client.return_value.get_response = AsyncMock(return_value=response)
            result = await factory.classify_intent("run HA test suite")

        from src.agents.agent_config import InvestigationIntent

        assert result == InvestigationIntent.TEST

    @pytest.mark.asyncio
    async def test_knowledge_intent(self) -> None:
        """LLM returning 'knowledge' maps to KNOWLEDGE."""
        response = MagicMock()
        response.text = "knowledge"

        with patch("src.agents.agent.MCPStreamableHTTPTool") as mock_mcp:
            mock_mcp.return_value = _make_mock_mcp_tool()
            factory = await SapAgentFactory.create(
                mcp_url="http://test:8001/mcp",
                endpoint="https://x.openai.azure.com",
            )

        with patch("src.agents.agent.AzureOpenAIChatClient") as mock_client:
            mock_client.return_value.get_response = AsyncMock(return_value=response)
            result = await factory.classify_intent("what is SAP Note 2369910?")

        from src.agents.agent_config import InvestigationIntent

        assert result == InvestigationIntent.KNOWLEDGE

    @pytest.mark.asyncio
    async def test_general_intent(self) -> None:
        """LLM returning 'general' maps to GENERAL."""
        response = MagicMock()
        response.text = "general"

        with patch("src.agents.agent.MCPStreamableHTTPTool") as mock_mcp:
            mock_mcp.return_value = _make_mock_mcp_tool()
            factory = await SapAgentFactory.create(
                mcp_url="http://test:8001/mcp",
                endpoint="https://x.openai.azure.com",
            )

        with patch("src.agents.agent.AzureOpenAIChatClient") as mock_client:
            mock_client.return_value.get_response = AsyncMock(return_value=response)
            result = await factory.classify_intent("hello there")

        from src.agents.agent_config import InvestigationIntent

        assert result == InvestigationIntent.GENERAL

    @pytest.mark.asyncio
    async def test_empty_input_returns_general(self) -> None:
        """Empty string skips LLM call, returns GENERAL."""
        with patch("src.agents.agent.MCPStreamableHTTPTool") as mock_mcp:
            mock_mcp.return_value = _make_mock_mcp_tool()
            factory = await SapAgentFactory.create(
                mcp_url="http://test:8001/mcp",
            )

        from src.agents.agent_config import InvestigationIntent

        result = await factory.classify_intent("")
        assert result == InvestigationIntent.GENERAL

    @pytest.mark.asyncio
    async def test_whitespace_only_returns_general(self) -> None:
        """Whitespace-only input returns GENERAL without LLM call."""
        with patch("src.agents.agent.MCPStreamableHTTPTool") as mock_mcp:
            mock_mcp.return_value = _make_mock_mcp_tool()
            factory = await SapAgentFactory.create(
                mcp_url="http://test:8001/mcp",
            )

        from src.agents.agent_config import InvestigationIntent

        result = await factory.classify_intent("   ")
        assert result == InvestigationIntent.GENERAL

    @pytest.mark.asyncio
    async def test_invalid_llm_response_returns_general(self) -> None:
        """Invalid LLM response falls back to GENERAL."""
        response = MagicMock()
        response.text = "banana"

        with patch("src.agents.agent.MCPStreamableHTTPTool") as mock_mcp:
            mock_mcp.return_value = _make_mock_mcp_tool()
            factory = await SapAgentFactory.create(
                mcp_url="http://test:8001/mcp",
                endpoint="https://x.openai.azure.com",
            )

        with patch("src.agents.agent.AzureOpenAIChatClient") as mock_client:
            mock_client.return_value.get_response = AsyncMock(return_value=response)
            result = await factory.classify_intent("some text")

        from src.agents.agent_config import InvestigationIntent

        assert result == InvestigationIntent.GENERAL

    @pytest.mark.asyncio
    async def test_llm_error_returns_general(self) -> None:
        """LLM exception falls back to GENERAL."""
        with patch("src.agents.agent.MCPStreamableHTTPTool") as mock_mcp:
            mock_mcp.return_value = _make_mock_mcp_tool()
            factory = await SapAgentFactory.create(
                mcp_url="http://test:8001/mcp",
                endpoint="https://x.openai.azure.com",
            )

        with patch("src.agents.agent.AzureOpenAIChatClient") as mock_client:
            mock_client.return_value.get_response = AsyncMock(
                side_effect=RuntimeError("LLM down"),
            )
            result = await factory.classify_intent("investigate something")

        from src.agents.agent_config import InvestigationIntent

        assert result == InvestigationIntent.GENERAL

    @pytest.mark.asyncio
    async def test_uses_structured_output(self) -> None:
        """Classifier passes IntentClassification as response_format."""
        response = MagicMock()
        response.text = "triage"

        with patch("src.agents.agent.MCPStreamableHTTPTool") as mock_mcp:
            mock_mcp.return_value = _make_mock_mcp_tool()
            factory = await SapAgentFactory.create(
                mcp_url="http://test:8001/mcp",
                endpoint="https://x.openai.azure.com",
            )

        with patch("src.agents.agent.AzureOpenAIChatClient") as mock_client:
            mock_client.return_value.get_response = AsyncMock(return_value=response)
            await factory.classify_intent("check my cluster")

        call_kwargs = mock_client.return_value.get_response.call_args
        options = call_kwargs[1]["options"]
        from src.agents.agent import IntentClassification

        assert options["response_format"] is IntentClassification
        assert options["temperature"] == 0
        assert options["max_tokens"] == 20


# ---------------------------------------------------------------------------
# Tests — Agentic execution loop configuration
# ---------------------------------------------------------------------------


@patch("src.agents.agent.HandoffBuilder", _MockHandoffBuilder)
class TestAgenticLoopConfiguration:
    """Tests for the agentic loop settings in create_workflow."""

    @patch("src.agents.agent.AzureOpenAIChatClient")
    @pytest.mark.asyncio
    async def test_max_iterations_uses_default_max_rounds(
        self,
        mock_client_cls: MagicMock,
    ) -> None:
        """max_iterations matches GENERAL config max_rounds (30)."""
        mock_client_cls.return_value.as_agent.side_effect = _mock_as_agent

        with patch("src.agents.agent.MCPStreamableHTTPTool") as mock_mcp:
            mock_mcp.return_value = _make_mock_mcp_tool()
            factory = await SapAgentFactory.create(
                mcp_url="http://test:8001/mcp",
                endpoint="https://x.openai.azure.com",
            )

        factory.create_workflow()

        call = mock_client_cls.return_value.as_agent.call_args
        fic = call[1]["function_invocation_configuration"]
        assert fic["max_iterations"] == 30

    @patch("src.agents.agent.AzureOpenAIChatClient")
    @pytest.mark.asyncio
    async def test_consecutive_errors_limit_set(
        self,
        mock_client_cls: MagicMock,
    ) -> None:
        """max_consecutive_errors_per_request is configured."""
        mock_client_cls.return_value.as_agent.side_effect = _mock_as_agent

        with patch("src.agents.agent.MCPStreamableHTTPTool") as mock_mcp:
            mock_mcp.return_value = _make_mock_mcp_tool()
            factory = await SapAgentFactory.create(
                mcp_url="http://test:8001/mcp",
                endpoint="https://x.openai.azure.com",
            )

        factory.create_workflow()

        call = mock_client_cls.return_value.as_agent.call_args
        fic = call[1]["function_invocation_configuration"]
        assert fic["max_consecutive_errors_per_request"] == 5

    @patch("src.agents.agent.AzureOpenAIChatClient")
    @pytest.mark.asyncio
    async def test_detailed_errors_disabled(
        self,
        mock_client_cls: MagicMock,
    ) -> None:
        """include_detailed_errors is False (middleware handles errors)."""
        mock_client_cls.return_value.as_agent.side_effect = _mock_as_agent

        with patch("src.agents.agent.MCPStreamableHTTPTool") as mock_mcp:
            mock_mcp.return_value = _make_mock_mcp_tool()
            factory = await SapAgentFactory.create(
                mcp_url="http://test:8001/mcp",
                endpoint="https://x.openai.azure.com",
            )

        factory.create_workflow()

        call = mock_client_cls.return_value.as_agent.call_args
        fic = call[1]["function_invocation_configuration"]
        assert fic["include_detailed_errors"] is False

    @patch("src.agents.agent.AzureOpenAIChatClient")
    @pytest.mark.asyncio
    async def test_instructions_contain_agentic_loop(
        self,
        mock_client_cls: MagicMock,
    ) -> None:
        """System prompt enforces think-aloud and iterative investigation."""
        mock_client_cls.return_value.as_agent.side_effect = _mock_as_agent

        with patch("src.agents.agent.MCPStreamableHTTPTool") as mock_mcp:
            mock_mcp.return_value = _make_mock_mcp_tool()
            factory = await SapAgentFactory.create(
                mcp_url="http://test:8001/mcp",
                endpoint="https://x.openai.azure.com",
            )

        factory.create_workflow()

        # Single SAP-Agent gets the full instruction set.
        call = mock_client_cls.return_value.as_agent.call_args
        instructions = call[1]["instructions"]
        assert "ABSOLUTE RULES" in instructions
        assert "Think out loud" in instructions
        assert "How to work" in instructions
        assert "Reminders" in instructions

    @patch("src.agents.agent.AzureOpenAIChatClient")
    @pytest.mark.asyncio
    async def test_middleware_wired(
        self,
        mock_client_cls: MagicMock,
    ) -> None:
        """Middleware classes are passed to the agent."""
        mock_client_cls.return_value.as_agent.side_effect = _mock_as_agent

        with patch("src.agents.agent.MCPStreamableHTTPTool") as mock_mcp:
            mock_mcp.return_value = _make_mock_mcp_tool()
            factory = await SapAgentFactory.create(
                mcp_url="http://test:8001/mcp",
                endpoint="https://x.openai.azure.com",
            )

        factory.create_workflow()

        call = mock_client_cls.return_value.as_agent.call_args
        middleware_list = call[1]["middleware"]
        from src.agents.providers.middleware import (
            AgentExceptionMiddleware,
            FunctionGuardMiddleware,
            OutputSanitizationMiddleware,
        )

        types = [type(m) for m in middleware_list]
        assert AgentExceptionMiddleware in types
        assert FunctionGuardMiddleware in types
        assert OutputSanitizationMiddleware in types

    @patch("src.agents.agent.AzureOpenAIChatClient")
    @pytest.mark.asyncio
    async def test_agent_gets_history_provider(
        self,
        mock_client_cls: MagicMock,
    ) -> None:
        """The agent receives a ConversationHistoryProvider."""
        mock_client_cls.return_value.as_agent.side_effect = _mock_as_agent
        store = MagicMock()

        with patch("src.agents.agent.MCPStreamableHTTPTool") as mock_mcp:
            mock_mcp.return_value = _make_mock_mcp_tool()
            factory = await SapAgentFactory.create(
                mcp_url="http://test:8001/mcp",
                endpoint="https://x.openai.azure.com",
                conversation_store=store,
            )

        factory.create_workflow(thread_id="thread-abc")

        from src.agents.providers.history_provider import ConversationHistoryProvider

        call = mock_client_cls.return_value.as_agent.call_args
        providers = call[1].get("context_providers", [])
        assert any(isinstance(p, ConversationHistoryProvider) for p in providers)

    @patch("src.agents.agent.AzureOpenAIChatClient")
    @pytest.mark.asyncio
    async def test_history_provider_save_disabled_for_workflow(
        self,
        mock_client_cls: MagicMock,
    ) -> None:
        """History provider has save_enabled=False (AG-UI handles persistence)."""
        mock_client_cls.return_value.as_agent.side_effect = _mock_as_agent
        store = MagicMock()

        with patch("src.agents.agent.MCPStreamableHTTPTool") as mock_mcp:
            mock_mcp.return_value = _make_mock_mcp_tool()
            factory = await SapAgentFactory.create(
                mcp_url="http://test:8001/mcp",
                endpoint="https://x.openai.azure.com",
                conversation_store=store,
            )

        factory.create_workflow(thread_id="thread-xyz")

        from src.agents.providers.history_provider import ConversationHistoryProvider

        call = mock_client_cls.return_value.as_agent.call_args
        providers = call[1].get("context_providers", [])
        for p in providers:
            if isinstance(p, ConversationHistoryProvider):
                assert not p._save_enabled

    @patch("src.agents.agent.AzureOpenAIChatClient")
    @pytest.mark.asyncio
    async def test_thread_id_propagated_to_history_provider(
        self,
        mock_client_cls: MagicMock,
    ) -> None:
        """thread_id is set as conversation_id on all history providers."""
        mock_client_cls.return_value.as_agent.side_effect = _mock_as_agent
        store = MagicMock()

        with patch("src.agents.agent.MCPStreamableHTTPTool") as mock_mcp:
            mock_mcp.return_value = _make_mock_mcp_tool()
            factory = await SapAgentFactory.create(
                mcp_url="http://test:8001/mcp",
                endpoint="https://x.openai.azure.com",
                conversation_store=store,
            )

        factory.create_workflow(thread_id="my-thread-123")

        from src.agents.providers.history_provider import ConversationHistoryProvider

        call = mock_client_cls.return_value.as_agent.call_args
        providers = call[1].get("context_providers", [])
        for p in providers:
            if isinstance(p, ConversationHistoryProvider):
                assert p._conversation_id == "my-thread-123"

    @patch("src.agents.agent.AzureOpenAIChatClient")
    @pytest.mark.asyncio
    async def test_agent_prompt_forbids_confirmation(
        self,
        mock_client_cls: MagicMock,
    ) -> None:
        """Agent prompt explicitly forbids asking for confirmation."""
        mock_client_cls.return_value.as_agent.side_effect = _mock_as_agent

        with patch("src.agents.agent.MCPStreamableHTTPTool") as mock_mcp:
            mock_mcp.return_value = _make_mock_mcp_tool()
            factory = await SapAgentFactory.create(
                mcp_url="http://test:8001/mcp",
                endpoint="https://x.openai.azure.com",
            )

        factory.create_workflow()

        call = mock_client_cls.return_value.as_agent.call_args
        instructions = call[1]["instructions"]
        assert "NEVER" in instructions
