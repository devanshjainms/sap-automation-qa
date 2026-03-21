# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
SAP Agent factory — composes a multi-agent GroupChat workflow.

Each specialist agent connects to the SAP MCP server over HTTP using
``MCPStreamableHTTPTool`` from the Agent Framework.  All tool
invocations traverse the full MCP protocol — no internal API access.
"""

from __future__ import annotations
import logging
import os
from typing import Any, Optional
import httpx
from agent_framework import (
    CharacterEstimatorTokenizer,
    CompactionStrategy,
    FunctionInvocationConfiguration,
    MCPStreamableHTTPTool,
    SlidingWindowStrategy,
    TokenBudgetComposedStrategy,
    ToolResultCompactionStrategy,
    Workflow,
)
from agent_framework.azure import AzureOpenAIChatClient
from agent_framework.orchestrations import GroupChatBuilder
from src.core.models.mcp_config import (
    BearerAuth,
    McpServerEntry,
    McpServersConfig,
)

logger = logging.getLogger(__name__)

DEFAULT_MCP_URL = "http://localhost:{port}/mcp".format(
    port=os.environ.get("MCP_PORT", "8001"),
)


class SapAgentFactory:
    """Creates a multi-agent GroupChat workflow wired to MCP servers.

    Each specialist agent receives an ``MCPStreamableHTTPTool``
    configured with ``allowed_tools`` so that only the relevant
    subset of tools is visible.  All tool invocations traverse the
    MCP protocol end-to-end.

    :param mcp_url: URL of the SAP MCP server endpoint.
    :param mcp_config: External MCP server configuration.
    :param endpoint: Azure OpenAI endpoint URL.
    :param deployment_name: Deployment / model name.
    :param api_key: API key (omit for managed-identity auth).
    :param api_version: API version string.
    """

    DEFAULT_MAX_ROUNDS = 10
    DEFAULT_TOKEN_BUDGET = 120_000

    TRIAGE_TOOLS = [
        "collect_evidence",
        "run_analysis",
        "get_triage_report",
        "query_knowledge",
        "list_workspaces",
        "get_workspace",
    ]

    STAF_TOOLS = [
        "run_staf_test",
        "get_job_status",
        "get_job_results",
        "list_jobs",
        "cancel_job",
        "get_job_events",
        "get_job_log",
        "list_workspaces",
        "get_workspace",
    ]

    OPS_TOOLS = [
        "create_schedule",
        "list_schedules",
        "get_schedule",
        "update_schedule",
        "delete_schedule",
        "trigger_schedule",
        "get_schedule_jobs",
    ]

    _TRIAGE_INSTRUCTIONS = (
        "You are the Triage specialist for SAP infrastructure on Azure.\n"
        "Your job is to investigate SAP system issues by collecting "
        "evidence from cluster nodes, analyzing it against known rules "
        "and playbooks, and providing actionable findings with severity "
        "and remediation steps.\n\n"
        "Workflow:\n"
        "1. Collect evidence (logs, cluster state, configs).\n"
        "2. Analyze evidence against the knowledge base.\n"
        "3. Report findings with severity and remediation.\n\n"
        "All your tools are read-only — no writes to production systems."
    )

    _STAF_INSTRUCTIONS = (
        "You are the STAF (SAP Testing Automation Framework) specialist.\n"
        "Your job is to run HA functional tests, configuration checks, "
        "and manage test jobs.\n\n"
        "Capabilities:\n"
        "- Launch STAF test jobs (HA failover, config checks).\n"
        "- Monitor job status and retrieve results.\n"
        "- Cancel running jobs and stream job events/logs.\n\n"
        "Always confirm the workspace and test group before launching "
        "a test. Report results clearly with pass/fail counts."
    )

    _OPS_INSTRUCTIONS = (
        "You are the Operations specialist for SAP test scheduling.\n"
        "Your job is to manage recurring test schedules: create, list, "
        "update, delete, trigger, and inspect schedule-triggered jobs.\n\n"
        "Capabilities:\n"
        "- CRUD on cron-based schedules.\n"
        "- Immediate schedule triggering.\n"
        "- Listing jobs spawned by a schedule.\n\n"
        "Validate cron expressions and workspace IDs before creating "
        "schedules. Show next-run-time when reporting schedule details."
    )

    _ORCHESTRATOR_INSTRUCTIONS = (
        "You are SAP-Router, the orchestrator for a team of SAP "
        "infrastructure specialists.\n\n"
        "Your participants:\n"
        "- **Triage-Agent**: Investigation, diagnostics, evidence "
        "collection, analysis, knowledge-base queries.\n"
        "- **STAF-Agent**: Running tests, checking job status/results, "
        "cancelling jobs, reading job logs.\n"
        "- **Ops-Agent**: Schedule management (create, list, update, "
        "delete, trigger schedules).\n\n"
        "Route each user turn to the specialist whose expertise best "
        "matches the request. If a query spans multiple domains, engage "
        "agents in sequence. Summarize the final answer before "
        "terminating the conversation."
    )

    def __init__(
        self,
        *,
        mcp_url: str = DEFAULT_MCP_URL,
        mcp_config: Optional[McpServersConfig] = None,
        endpoint: Optional[str] = None,
        deployment_name: Optional[str] = None,
        api_key: Optional[str] = None,
        api_version: Optional[str] = None,
    ) -> None:
        self._mcp_url = mcp_url
        self._mcp_config = mcp_config or McpServersConfig()
        self._client_kwargs = self._build_client_kwargs(
            endpoint,
            deployment_name,
            api_key,
            api_version,
        )
        self._triage_mcp: Optional[MCPStreamableHTTPTool] = None
        self._staf_mcp: Optional[MCPStreamableHTTPTool] = None
        self._ops_mcp: Optional[MCPStreamableHTTPTool] = None
        self._external_mcps: list[MCPStreamableHTTPTool] = []

    @classmethod
    async def create(
        cls,
        *,
        mcp_url: str = DEFAULT_MCP_URL,
        mcp_config: Optional[McpServersConfig] = None,
        endpoint: Optional[str] = None,
        deployment_name: Optional[str] = None,
        api_key: Optional[str] = None,
        api_version: Optional[str] = None,
    ) -> SapAgentFactory:
        """Async factory — connects to MCP server(s) and discovers tools.

        :param mcp_url: URL of the SAP MCP server endpoint.
        :param mcp_config: External MCP server configuration.
        :param endpoint: Azure OpenAI endpoint URL.
        :param deployment_name: Deployment / model name.
        :param api_key: API key (omit for managed-identity auth).
        :param api_version: API version string.
        :returns: Factory with MCP connections established.
        """
        factory = cls(
            mcp_url=mcp_url,
            mcp_config=mcp_config,
            endpoint=endpoint,
            deployment_name=deployment_name,
            api_key=api_key,
            api_version=api_version,
        )
        await factory._connect_tools()
        return factory

    @property
    def mcp_url(self) -> str:
        """The SAP MCP server URL."""
        return self._mcp_url

    @property
    def tool_counts(self) -> dict[str, int]:
        """Tool counts per agent group (after connection)."""
        counts: dict[str, int] = {}
        if self._triage_mcp:
            counts["triage"] = len(self._triage_mcp.functions)
        if self._staf_mcp:
            counts["staf"] = len(self._staf_mcp.functions)
        if self._ops_mcp:
            counts["ops"] = len(self._ops_mcp.functions)
        for tool in self._external_mcps:
            counts[tool.name] = len(tool.functions)
        return counts

    def create_workflow(
        self,
        *,
        workspace_context: Optional[str] = None,
        max_rounds: int = DEFAULT_MAX_ROUNDS,
    ) -> Workflow:
        """Create a multi-agent GroupChat workflow for one conversation.

        :param workspace_context: Per-conversation context string (e.g. ``"Workspace: X02"``).
        :param max_rounds: Maximum orchestrator rounds before stopping.
        :returns: Configured ``Workflow`` instance.
        """
        client = AzureOpenAIChatClient(**self._client_kwargs)
        ctx_suffix = f"\n\n{workspace_context}" if workspace_context else ""
        compaction = self._build_compaction_strategy()

        triage_agent = client.as_agent(
            name="Triage-Agent",
            description=(
                "Investigation specialist: evidence collection, "
                "analysis, diagnostics, knowledge-base queries."
            ),
            instructions=self._TRIAGE_INSTRUCTIONS + ctx_suffix,
            tools=[self._triage_mcp],
            function_invocation_configuration=(FunctionInvocationConfiguration(max_iterations=15)),
            compaction_strategy=compaction,
        )

        staf_agent = client.as_agent(
            name="STAF-Agent",
            description=(
                "Test execution specialist: run STAF tests, "
                "check job status/results, manage running jobs."
            ),
            instructions=self._STAF_INSTRUCTIONS + ctx_suffix,
            tools=[self._staf_mcp],
            function_invocation_configuration=(FunctionInvocationConfiguration(max_iterations=15)),
            compaction_strategy=compaction,
        )

        ops_agent = client.as_agent(
            name="Ops-Agent",
            description=(
                "Operations specialist: schedule CRUD, " "triggering, and schedule-job inspection."
            ),
            instructions=self._OPS_INSTRUCTIONS + ctx_suffix,
            tools=[self._ops_mcp],
            function_invocation_configuration=(FunctionInvocationConfiguration(max_iterations=10)),
            compaction_strategy=compaction,
        )

        orchestrator = client.as_agent(
            name="SAP-Router",
            description="Routes user queries to specialist agents.",
            instructions=(self._ORCHESTRATOR_INSTRUCTIONS + ctx_suffix),
            compaction_strategy=compaction,
        )

        workflow = GroupChatBuilder(
            participants=[triage_agent, staf_agent, ops_agent],
            orchestrator_agent=orchestrator,
            max_rounds=max_rounds,
            intermediate_outputs=True,
        ).build()

        logger.info(
            "Created GroupChat workflow with 3 agents, " "max_rounds=%d, tools: %s",
            max_rounds,
            self.tool_counts,
        )
        return workflow

    async def close(self) -> None:
        """Shut down all MCP tool connections."""
        for tool in (
            self._triage_mcp,
            self._staf_mcp,
            self._ops_mcp,
        ):
            if tool:
                try:
                    await tool.close()
                except Exception:
                    logger.debug(
                        "Error closing MCP tool",
                        exc_info=True,
                    )
        for tool in self._external_mcps:
            try:
                await tool.close()
            except Exception:
                logger.debug(
                    "Error closing external MCP tool",
                    exc_info=True,
                )
        self._external_mcps.clear()

    async def __aenter__(self) -> SapAgentFactory:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()

    def _build_compaction_strategy(self) -> CompactionStrategy:
        """
        Build a token-budget compaction strategy for agent context.

        :returns: Composed compaction strategy.
        """
        tokenizer = CharacterEstimatorTokenizer()
        return TokenBudgetComposedStrategy(
            token_budget=self.DEFAULT_TOKEN_BUDGET,
            tokenizer=tokenizer,
            strategies=[
                ToolResultCompactionStrategy(keep_last_tool_call_groups=2),
                SlidingWindowStrategy(keep_last_groups=20),
            ],
        )

    async def _connect_tools(self) -> None:
        """Create and connect MCPStreamableHTTPTool per agent group."""
        self._triage_mcp = MCPStreamableHTTPTool(
            name="sap-triage",
            url=self._mcp_url,
            allowed_tools=self.TRIAGE_TOOLS,
        )
        await self._triage_mcp.connect()

        self._staf_mcp = MCPStreamableHTTPTool(
            name="sap-staf",
            url=self._mcp_url,
            allowed_tools=self.STAF_TOOLS,
        )
        await self._staf_mcp.connect()

        self._ops_mcp = MCPStreamableHTTPTool(
            name="sap-ops",
            url=self._mcp_url,
            allowed_tools=self.OPS_TOOLS,
        )
        await self._ops_mcp.connect()

        await self._connect_external()
        logger.info("Connected MCP tools: %s", self.tool_counts)

    async def _connect_external(self) -> None:
        """Connect to external MCP servers from configuration."""
        for entry in self._mcp_config.enabled_servers:
            try:
                tool = self._build_external_mcp(entry)
                await tool.connect()
                self._external_mcps.append(tool)
                logger.info(
                    "Connected external MCP %s: %d tools",
                    entry.name,
                    len(tool.functions),
                )
            except Exception:
                logger.warning(
                    "Failed to connect to MCP server %s at %s",
                    entry.name,
                    entry.url,
                    exc_info=True,
                )

    @staticmethod
    def _build_external_mcp(
        entry: McpServerEntry,
    ) -> MCPStreamableHTTPTool:
        """Build an MCPStreamableHTTPTool for an external server.

        :param entry: Server configuration entry.
        :returns: Configured (not yet connected) MCP tool.
        """
        kwargs: dict[str, Any] = {}
        if isinstance(entry.auth, BearerAuth):
            token = os.environ.get(entry.auth.token_env, "")
            if token:
                kwargs["http_client"] = httpx.AsyncClient(
                    headers={
                        "Authorization": f"Bearer {token}",
                    },
                )
        return MCPStreamableHTTPTool(
            name=entry.name,
            url=entry.url,
            description=entry.preamble_hint or "",
            **kwargs,
        )

    @staticmethod
    def _build_client_kwargs(
        endpoint: Optional[str],
        deployment_name: Optional[str],
        api_key: Optional[str],
        api_version: Optional[str],
    ) -> dict[str, Any]:
        """Build kwargs for ``AzureOpenAIChatClient``."""
        kwargs: dict[str, Any] = {}
        if endpoint:
            kwargs["endpoint"] = endpoint
        if deployment_name:
            kwargs["deployment_name"] = deployment_name
        if api_key:
            kwargs["api_key"] = api_key
        if api_version:
            kwargs["api_version"] = api_version
        return kwargs
