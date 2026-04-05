# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
SAP Agent factory — creates agents wired to MCP tools.

The agent connects to the SAP MCP server over HTTP using
``MCPStreamableHTTPTool`` from the Agent Framework.  All tool
invocations traverse the full MCP protocol — no internal API access.
"""

from __future__ import annotations
import logging
import os
from typing import Any, Optional
import asyncio
import httpx
from agent_framework import (
    Agent,
    AgentSession,
    BaseContextProvider,
    CharacterEstimatorTokenizer,
    CompactionStrategy,
    FunctionInvocationConfiguration,
    MCPStreamableHTTPTool,
    SlidingWindowStrategy,
    TokenBudgetComposedStrategy,
    ToolResultCompactionStrategy,
)
from agent_framework.azure import AzureOpenAIChatClient
from src.mcp_server.server import mcp as _mcp_server
from agent_framework._types import Message as AFMessage
from src.agents.providers.middleware import (
    AgentExceptionMiddleware,
    FunctionGuardMiddleware,
    InvestigationChatMiddleware,
    OutputSanitizationMiddleware,
)
from src.agents.agent_config import (
    AgentConfig,
    InvestigationIntent,
    classify,
    config_for_intent,
)
from src.agents.prompt_modules import assemble
from src.agents.providers.history_provider import ConversationHistoryProvider
from src.agents.providers.knowledge_provider import KnowledgeContextProvider
from src.core.knowledge.retrieval import HybridRetriever
from src.core.models.mcp_config import (
    BearerAuth,
    McpServerEntry,
    McpServersConfig,
)
from src.core.storage.conversation_store import ConversationStore
from src.core.models.workspace import WorkspaceContextProvider

logger = logging.getLogger(__name__)

DEFAULT_MCP_URL = "http://localhost:{port}/mcp".format(
    port=os.environ.get("MCP_PORT", "8001"),
)


class SapAgentFactory:
    """Creates a single-agent workflow wired to MCP tools.

    One agent receives all SAP tools (triage, STAF, ops) via a single
    ``MCPStreamableHTTPTool``.  This avoids the multi-agent relay
    overhead (orchestrator → specialist → orchestrator) and keeps the
    LLM's response as the final output — no lossy relay layer.

    :param mcp_url: URL of the SAP MCP server endpoint.
    :param mcp_config: External MCP server configuration.
    :param endpoint: Azure OpenAI endpoint URL.
    :param deployment_name: Deployment / model name.
    :param api_key: API key (omit for managed-identity auth).
    :param api_version: API version string.
    """

    DEFAULT_MAX_ROUNDS = 75
    DEFAULT_TOKEN_BUDGET = 120_000
    _MAX_CONSECUTIVE_ERRORS = 5

    _MCP_CONNECT_RETRIES = 5
    _MCP_CONNECT_BACKOFF = 2.0
    _MSLEARN_MCP_URL = "https://learn.microsoft.com/api/mcp"
    _AZURE_MCP_URL = os.environ.get("AZURE_MCP_URL", "")

    def __init__(
        self,
        *,
        mcp_url: str = DEFAULT_MCP_URL,
        mcp_config: Optional[McpServersConfig] = None,
        conversation_store: Optional[ConversationStore] = None,
        retriever: Optional[HybridRetriever] = None,
        endpoint: Optional[str] = None,
        deployment_name: Optional[str] = None,
        api_key: Optional[str] = None,
        api_version: Optional[str] = None,
    ) -> None:
        self._mcp_url = mcp_url
        self._mcp_config = mcp_config or McpServersConfig()
        self._conversation_store = conversation_store
        self._retriever = retriever
        self._client_kwargs = self._build_client_kwargs(
            endpoint,
            deployment_name,
            api_key,
            api_version,
        )
        self._mcp_tool: Optional[MCPStreamableHTTPTool] = None
        self._external_mcps: list[MCPStreamableHTTPTool] = []

    async def __aenter__(self) -> SapAgentFactory:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()

    @property
    def mcp_url(self) -> str:
        """The SAP MCP server URL."""
        return self._mcp_url

    @property
    def tool_counts(self) -> dict[str, int]:
        """Tool counts (after connection)."""
        counts: dict[str, int] = {}
        if self._mcp_tool:
            counts["sap"] = len(self._mcp_tool.functions)
        for tool in self._external_mcps:
            counts[tool.name] = len(tool.functions)
        return counts

    @classmethod
    async def create(
        cls,
        *,
        mcp_url: str = DEFAULT_MCP_URL,
        mcp_config: Optional[McpServersConfig] = None,
        conversation_store: Optional[ConversationStore] = None,
        retriever: Optional[HybridRetriever] = None,
        endpoint: Optional[str] = None,
        deployment_name: Optional[str] = None,
        api_key: Optional[str] = None,
        api_version: Optional[str] = None,
    ) -> SapAgentFactory:
        """Async factory — connects to MCP server(s) and discovers tools.

        :param mcp_url: URL of the SAP MCP server endpoint.
        :param mcp_config: External MCP server configuration.
        :param conversation_store: SQLite conversation persistence.
        :param retriever: Knowledge retriever for proactive KB injection.
        :param endpoint: Azure OpenAI endpoint URL.
        :param deployment_name: Deployment / model name.
        :param api_key: API key (omit for managed-identity auth).
        :param api_version: API version string.
        :returns: Factory with MCP connections established.
        """
        factory = cls(
            mcp_url=mcp_url,
            mcp_config=mcp_config,
            conversation_store=conversation_store,
            retriever=retriever,
            endpoint=endpoint,
            deployment_name=deployment_name,
            api_key=api_key,
            api_version=api_version,
        )
        await factory._connect_tools()
        return factory

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

    _TITLE_PROMPT = (
        "Summarize the following user question in at most 8 words. "
        "Return ONLY the title text, no quotes or punctuation at the end.\n\n"
        "User question: {text}"
    )

    async def _generate_title(self, user_text: str) -> str:
        """Generate a short conversation title via a lightweight LLM call.

        :param user_text: The first user message in the conversation.
        :returns: A short title string (≤8 words).
        """
        client = AzureOpenAIChatClient(**self._client_kwargs)
        prompt = self._TITLE_PROMPT.format(text=user_text[:200])
        response = await client.get_response(
            messages=[AFMessage("user", [prompt])],
            options={"max_tokens": 30, "temperature": 0},
        )
        return response.text or user_text[:80]

    def _build_compaction_strategy(
        self,
        token_budget: int | None = None,
    ) -> CompactionStrategy:
        """Build a token-budget compaction strategy for agent context.

        :param token_budget: Overrides ``DEFAULT_TOKEN_BUDGET``.
        :returns: Composed compaction strategy.
        """
        budget = token_budget or self.DEFAULT_TOKEN_BUDGET
        tokenizer = CharacterEstimatorTokenizer()
        return TokenBudgetComposedStrategy(
            token_budget=budget,
            tokenizer=tokenizer,
            strategies=[
                ToolResultCompactionStrategy(keep_last_tool_call_groups=10),
                SlidingWindowStrategy(keep_last_groups=30),
            ],
        )

    async def _connect_primary(self) -> MCPStreamableHTTPTool:
        """Connect to the SAP MCP server with exponential backoff.

        :returns: Connected MCP tool.
        :raises Exception: After all retries are exhausted.
        """
        tool = MCPStreamableHTTPTool(
            name="sap-tools",
            url=self._mcp_url,
            allowed_tools=sorted(t.name for t in _mcp_server._tool_manager.list_tools()),
        )
        delay = self._MCP_CONNECT_BACKOFF
        for attempt in range(1, self._MCP_CONNECT_RETRIES + 1):
            try:
                await tool.connect()
                return tool
            except Exception:
                if attempt == self._MCP_CONNECT_RETRIES:
                    logger.warning(
                        "Failed to connect MCP tool after %d attempts",
                        attempt,
                    )
                    raise
                logger.info(
                    "MCP connect attempt %d/%d failed, retrying in %.0fs",
                    attempt,
                    self._MCP_CONNECT_RETRIES,
                    delay,
                )
                await asyncio.sleep(delay)
                delay *= 2
        return tool

    async def _try_connect_mcp(self, tool: MCPStreamableHTTPTool) -> bool:
        """Try to connect an optional MCP server.

        :param tool: Pre-built MCP tool to connect.
        :returns: True if connected successfully.
        """
        try:
            await tool.connect()
            self._external_mcps.append(tool)
            logger.info("Connected %s MCP: %d tools", tool.name, len(tool.functions))
            return True
        except Exception:
            logger.warning(
                "%s MCP unavailable — continuing without it",
                tool.name,
                exc_info=True,
            )
            return False

    async def _connect_tools(self) -> None:
        """Connect to the SAP MCP server and all optional MCP servers."""
        self._mcp_tool = await self._connect_primary()

        optional: list[MCPStreamableHTTPTool] = [
            MCPStreamableHTTPTool(
                name="microsoft-learn",
                url=self._MSLEARN_MCP_URL,
                allowed_tools=[
                    "microsoft_docs_search",
                    "microsoft_docs_fetch",
                    "microsoft_code_sample_search",
                ],
            ),
        ]
        if self._AZURE_MCP_URL:
            optional.append(
                MCPStreamableHTTPTool(
                    name="azure",
                    url=self._AZURE_MCP_URL,
                    load_prompts=False,
                )
            )

        for entry in self._mcp_config.enabled_servers:
            optional.append(self._build_external_mcp(entry))

        for tool in optional:
            await self._try_connect_mcp(tool)

        logger.info("Connected MCP tools: %s", self.tool_counts)

    def create_agent(
        self,
        *,
        workspace_context: Optional[str] = None,
        user_query: Optional[str] = None,
        config: Optional[AgentConfig] = None,
    ) -> Agent:
        """Create an agent with an agentic execution loop.

        When *config* is ``None`` the intent is auto-classified from
        *user_query* and the matching :class:`AgentConfig` is used.

        :param workspace_context: Per-conversation context string.
        :param user_query: First user message for intent classification
            and proactive KB injection.
        :param config: Explicit agent configuration. Auto-detected when
            ``None``.
        :returns: Configured ``Agent`` instance.
        """
        if config is None:
            intent = classify(user_query or "")
            config = config_for_intent(intent)

        instructions = assemble(config.module_names)

        client = AzureOpenAIChatClient(**self._client_kwargs)
        providers: list[Any] = []

        if self._conversation_store:
            providers.append(
                ConversationHistoryProvider(
                    self._conversation_store,
                    title_generator=self._generate_title,
                )
            )
        if workspace_context:
            providers.append(WorkspaceContextProvider(workspace_context))
        if config.inject_kb and self._retriever:
            providers.append(
                KnowledgeContextProvider(
                    retriever=self._retriever,
                    user_query=user_query,
                )
            )

        agent = client.as_agent(
            name="SAP-Agent",
            description=(
                "SAP configuration and infrastructure specialist for Azure. "
                "Investigates system health, runs diagnostics, "
                "manages Azure's SAP Testing Automation Framework tests and schedules."
            ),
            instructions=instructions,
            tools=[t for t in [self._mcp_tool] + self._external_mcps if t is not None],
            middleware=[
                AgentExceptionMiddleware(),
                *(
                    [InvestigationChatMiddleware(min_evidence=config.min_evidence)]
                    if config.min_evidence > 0
                    else []
                ),
                OutputSanitizationMiddleware(),
                FunctionGuardMiddleware(),
            ],
            function_invocation_configuration=FunctionInvocationConfiguration(
                max_iterations=config.max_rounds,
                max_consecutive_errors_per_request=self._MAX_CONSECUTIVE_ERRORS,
                include_detailed_errors=False,
            ),
            compaction_strategy=self._build_compaction_strategy(
                token_budget=config.token_budget,
            ),
            context_providers=providers,
        )

        logger.info(
            "Created agent intent=%s modules=%d tools=%s",
            config.intent.value,
            len(config.module_names),
            self.tool_counts,
        )
        return agent

    async def close(self) -> None:
        """Shut down all MCP tool connections."""
        if self._mcp_tool:
            try:
                await self._mcp_tool.close()
            except Exception:
                logger.debug("Error closing MCP tool", exc_info=True)
        for tool in self._external_mcps:
            try:
                await tool.close()
            except Exception:
                logger.debug("Error closing external MCP tool", exc_info=True)
        self._external_mcps.clear()
