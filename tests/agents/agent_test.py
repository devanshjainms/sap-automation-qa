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


# ---------------------------------------------------------------------------
# Tests — SapAgentFactory
# ---------------------------------------------------------------------------


class TestSapAgentFactory:
    """Tests for the ``SapAgentFactory`` class."""

    @pytest.mark.asyncio
    async def test_create_connects_three_mcp_tools(self) -> None:
        """Factory creates and connects triage, staf, and ops MCP tools."""
        with patch(
            "src.agents.agent.MCPStreamableHTTPTool"
        ) as mock_cls:
            mock_cls.return_value = _make_mock_mcp_tool()

            factory = await SapAgentFactory.create(
                mcp_url="http://test:8001/mcp",
                endpoint="https://x.openai.azure.com",
            )

        assert mock_cls.call_count == 3
        calls = mock_cls.call_args_list
        assert calls[0][1]["name"] == "sap-triage"
        assert calls[0][1]["url"] == "http://test:8001/mcp"
        assert calls[0][1]["allowed_tools"] == (
            SapAgentFactory.TRIAGE_TOOLS
        )
        assert calls[1][1]["name"] == "sap-staf"
        assert calls[1][1]["allowed_tools"] == (
            SapAgentFactory.STAF_TOOLS
        )
        assert calls[2][1]["name"] == "sap-ops"
        assert calls[2][1]["allowed_tools"] == (
            SapAgentFactory.OPS_TOOLS
        )
        assert (
            mock_cls.return_value.connect.await_count == 3
        )

    @pytest.mark.asyncio
    async def test_mcp_url_property(self) -> None:
        with patch(
            "src.agents.agent.MCPStreamableHTTPTool"
        ) as mock_cls:
            mock_cls.return_value = _make_mock_mcp_tool()
            factory = await SapAgentFactory.create(
                mcp_url="http://custom:9999/mcp",
            )
        assert factory.mcp_url == "http://custom:9999/mcp"

    @pytest.mark.asyncio
    async def test_tool_counts(self) -> None:
        """tool_counts returns per-group function counts."""
        triage = _make_mock_mcp_tool("sap-triage", 6)
        staf = _make_mock_mcp_tool("sap-staf", 9)
        ops = _make_mock_mcp_tool("sap-ops", 7)

        with patch(
            "src.agents.agent.MCPStreamableHTTPTool"
        ) as mock_cls:
            mock_cls.side_effect = [triage, staf, ops]
            factory = await SapAgentFactory.create(
                mcp_url="http://test:8001/mcp",
            )

        counts = factory.tool_counts
        assert counts["triage"] == 6
        assert counts["staf"] == 9
        assert counts["ops"] == 7

    @patch("src.agents.agent.AzureOpenAIChatClient")
    @pytest.mark.asyncio
    async def test_create_workflow_returns_workflow(
        self, mock_client_cls: MagicMock,
    ) -> None:
        """create_workflow builds a GroupChat workflow."""
        mock_agent = MagicMock()
        mock_client_cls.return_value.as_agent.return_value = mock_agent

        with patch(
            "src.agents.agent.MCPStreamableHTTPTool"
        ) as mock_mcp:
            mock_mcp.return_value = _make_mock_mcp_tool()
            factory = await SapAgentFactory.create(
                mcp_url="http://test:8001/mcp",
                endpoint="https://x.openai.azure.com",
            )

        with patch(
            "src.agents.agent.GroupChatBuilder"
        ) as mock_gcb:
            mock_workflow = MagicMock()
            mock_gcb.return_value.build.return_value = mock_workflow
            result = factory.create_workflow()

        assert result is mock_workflow

    @patch("src.agents.agent.AzureOpenAIChatClient")
    @pytest.mark.asyncio
    async def test_create_workflow_builds_four_agents(
        self, mock_client_cls: MagicMock,
    ) -> None:
        """create_workflow creates 4 agents: triage, staf, ops, router."""
        mock_client_cls.return_value.as_agent.return_value = MagicMock()

        with patch(
            "src.agents.agent.MCPStreamableHTTPTool"
        ) as mock_mcp:
            mock_mcp.return_value = _make_mock_mcp_tool()
            factory = await SapAgentFactory.create(
                mcp_url="http://test:8001/mcp",
                endpoint="https://x.openai.azure.com",
            )

        with patch("src.agents.agent.GroupChatBuilder") as mock_gcb:
            mock_gcb.return_value.build.return_value = MagicMock()
            factory.create_workflow()

        # 3 specialist + 1 orchestrator = 4 as_agent calls
        assert (
            mock_client_cls.return_value.as_agent.call_count == 4
        )
        names = [
            c[1]["name"]
            for c in mock_client_cls.return_value.as_agent.call_args_list
        ]
        assert names == [
            "Triage-Agent",
            "STAF-Agent",
            "Ops-Agent",
            "SAP-Router",
        ]

    @patch("src.agents.agent.AzureOpenAIChatClient")
    @pytest.mark.asyncio
    async def test_specialist_agents_receive_mcp_tools(
        self, mock_client_cls: MagicMock,
    ) -> None:
        """Each specialist gets its MCPStreamableHTTPTool in tools=."""
        mock_client_cls.return_value.as_agent.return_value = MagicMock()

        triage_mcp = _make_mock_mcp_tool("sap-triage")
        staf_mcp = _make_mock_mcp_tool("sap-staf")
        ops_mcp = _make_mock_mcp_tool("sap-ops")

        with patch(
            "src.agents.agent.MCPStreamableHTTPTool"
        ) as mock_cls:
            mock_cls.side_effect = [triage_mcp, staf_mcp, ops_mcp]
            factory = await SapAgentFactory.create(
                mcp_url="http://test:8001/mcp",
                endpoint="https://x.openai.azure.com",
            )

        with patch("src.agents.agent.GroupChatBuilder") as mock_gcb:
            mock_gcb.return_value.build.return_value = MagicMock()
            factory.create_workflow()

        calls = mock_client_cls.return_value.as_agent.call_args_list
        # Triage agent gets triage MCP tool
        assert calls[0][1]["tools"] == [triage_mcp]
        # STAF agent gets staf MCP tool
        assert calls[1][1]["tools"] == [staf_mcp]
        # Ops agent gets ops MCP tool
        assert calls[2][1]["tools"] == [ops_mcp]
        # Orchestrator gets no tools
        assert "tools" not in calls[3][1]

    @patch("src.agents.agent.AzureOpenAIChatClient")
    @pytest.mark.asyncio
    async def test_workspace_context_appended(
        self, mock_client_cls: MagicMock,
    ) -> None:
        """Workspace context is appended to agent instructions."""
        mock_client_cls.return_value.as_agent.return_value = MagicMock()

        with patch(
            "src.agents.agent.MCPStreamableHTTPTool"
        ) as mock_mcp:
            mock_mcp.return_value = _make_mock_mcp_tool()
            factory = await SapAgentFactory.create(
                mcp_url="http://test:8001/mcp",
                endpoint="https://x.openai.azure.com",
            )

        with patch("src.agents.agent.GroupChatBuilder") as mock_gcb:
            mock_gcb.return_value.build.return_value = MagicMock()
            factory.create_workflow(
                workspace_context="Workspace: PRD",
            )

        for call in (
            mock_client_cls.return_value.as_agent.call_args_list
        ):
            assert "Workspace: PRD" in call[1]["instructions"]

    @patch("src.agents.agent.AzureOpenAIChatClient")
    @pytest.mark.asyncio
    async def test_all_agents_receive_compaction_strategy(
        self, mock_client_cls: MagicMock,
    ) -> None:
        """Every agent (specialists + orchestrator) gets a compaction strategy."""
        mock_client_cls.return_value.as_agent.return_value = MagicMock()

        with patch(
            "src.agents.agent.MCPStreamableHTTPTool"
        ) as mock_mcp:
            mock_mcp.return_value = _make_mock_mcp_tool()
            factory = await SapAgentFactory.create(
                mcp_url="http://test:8001/mcp",
                endpoint="https://x.openai.azure.com",
            )

        with patch("src.agents.agent.GroupChatBuilder") as mock_gcb:
            mock_gcb.return_value.build.return_value = MagicMock()
            factory.create_workflow()

        for call in mock_client_cls.return_value.as_agent.call_args_list:
            strategy = call[1].get("compaction_strategy")
            assert strategy is not None, (
                f"Agent {call[1]['name']} missing compaction_strategy"
            )
            assert isinstance(strategy, TokenBudgetComposedStrategy)

    @patch("src.agents.agent.AzureOpenAIChatClient")
    @pytest.mark.asyncio
    async def test_client_receives_kwargs(
        self, mock_client_cls: MagicMock,
    ) -> None:
        """AzureOpenAIChatClient receives endpoint/deployment/key."""
        mock_client_cls.return_value.as_agent.return_value = MagicMock()

        with patch(
            "src.agents.agent.MCPStreamableHTTPTool"
        ) as mock_mcp:
            mock_mcp.return_value = _make_mock_mcp_tool()
            factory = await SapAgentFactory.create(
                mcp_url="http://test:8001/mcp",
                endpoint="https://my.openai.azure.com",
                deployment_name="gpt-4o",
                api_key="key-123",
                api_version="2025-01-01",
            )

        with patch("src.agents.agent.GroupChatBuilder") as mock_gcb:
            mock_gcb.return_value.build.return_value = MagicMock()
            factory.create_workflow()

        client_kwargs = mock_client_cls.call_args[1]
        assert client_kwargs["endpoint"] == (
            "https://my.openai.azure.com"
        )
        assert client_kwargs["deployment_name"] == "gpt-4o"
        assert client_kwargs["api_key"] == "key-123"
        assert client_kwargs["api_version"] == "2025-01-01"

    @pytest.mark.asyncio
    async def test_omits_none_client_kwargs(self) -> None:
        with patch(
            "src.agents.agent.MCPStreamableHTTPTool"
        ) as mock_mcp:
            mock_mcp.return_value = _make_mock_mcp_tool()
            factory = await SapAgentFactory.create(
                mcp_url="http://test:8001/mcp",
            )
        assert "endpoint" not in factory._client_kwargs
        assert "api_key" not in factory._client_kwargs

    @pytest.mark.asyncio
    async def test_close_shuts_all_tools(self) -> None:
        """close() calls close on triage, staf, ops MCP tools."""
        triage = _make_mock_mcp_tool("sap-triage")
        staf = _make_mock_mcp_tool("sap-staf")
        ops = _make_mock_mcp_tool("sap-ops")

        with patch(
            "src.agents.agent.MCPStreamableHTTPTool"
        ) as mock_cls:
            mock_cls.side_effect = [triage, staf, ops]
            factory = await SapAgentFactory.create(
                mcp_url="http://test:8001/mcp",
            )

        await factory.close()

        triage.close.assert_awaited_once()
        staf.close.assert_awaited_once()
        ops.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_async_context_manager(self) -> None:
        """Can be used as ``async with`` context manager."""
        with patch(
            "src.agents.agent.MCPStreamableHTTPTool"
        ) as mock_mcp:
            mock_tool = _make_mock_mcp_tool()
            mock_mcp.return_value = mock_tool
            factory = await SapAgentFactory.create(
                mcp_url="http://test:8001/mcp",
            )

        async with factory as f:
            assert f is factory

        assert mock_tool.close.await_count == 3


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
                tool.connect.side_effect = ConnectionError(
                    "refused"
                )
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
            patch.dict(
                "os.environ", {"MY_TOKEN": "secret-123"}
            ),
        ):
            await SapAgentFactory.create(
                mcp_url="http://test:8001/mcp",
                mcp_config=config,
            )

        # Find the call for the "secure" external server
        ext_call = next(
            k for k in captured_kwargs if k.get("name") == "secure"
        )
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

        with patch(
            "src.agents.agent.MCPStreamableHTTPTool"
        ) as mock_cls:
            mock_cls.return_value = _make_mock_mcp_tool()
            factory = await SapAgentFactory.create(
                mcp_url="http://test:8001/mcp",
                mcp_config=config,
            )

        # Only 3 local tools created (no external)
        assert mock_cls.call_count == 3
        assert "off" not in factory.tool_counts
