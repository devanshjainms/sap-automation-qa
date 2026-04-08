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
from pydantic import BaseModel
from agent_framework import (
    BaseContextProvider,
    CharacterEstimatorTokenizer,
    ChatOptions,
    CompactionStrategy,
    FunctionInvocationConfiguration,
    MCPStreamableHTTPTool,
    SlidingWindowStrategy,
    TokenBudgetComposedStrategy,
    ToolResultCompactionStrategy,
)
from agent_framework.azure import AzureOpenAIChatClient, AzureOpenAIResponsesClient
from src.mcp_server.server import mcp as _mcp_server
from agent_framework._types import Message as AFMessage
from agent_framework.orchestrations import HandoffBuilder
from src.agents.providers.middleware import (
    AgentExceptionMiddleware,
    FunctionGuardMiddleware,
    OutputSanitizationMiddleware,
)
from src.agents.agent_config import (
    AgentConfig,
    InvestigationIntent,
    config_for_intent,
    COORDINATOR_ROLE_PROMPT,
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


class IntentClassification(BaseModel):
    """Structured output schema for intent classification."""

    intent: str


class SapAgentFactory:
    """Creates agent workflows wired to MCP tools.

    Supports two workflow patterns based on classified intent:

    - **TRIAGE / TEST**: HandoffBuilder with a Coordinator that
      routes to Investigator and TestRunner specialists.
    - **GENERAL / KNOWLEDGE**: Single agent with all tools in a
      natural think → act → observe → think loop.

    :param mcp_url: URL of the SAP MCP server endpoint.
    :param mcp_config: External MCP server configuration.
    :param endpoint: Azure OpenAI endpoint URL.
    :param deployment_name: Deployment / model name.
    :param api_key: API key (omit for managed-identity auth).
    :param api_version: API version string.
    """

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
        self._utility_client: Optional[AzureOpenAIChatClient] = None

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

    _CLASSIFY_PROMPT = (
        "Classify the user's message into exactly one intent.\n\n"
        "Intents:\n"
        "- **triage**: Investigate, diagnose, or troubleshoot a live SAP system "
        "(cluster issues, failover, node crashes, health checks, configuration review).\n"
        "- **test**: Run, schedule, or execute SAP HA / functional tests (STAF, test suites).\n"
        "- **knowledge**: Ask about SAP rules, SAP Notes, best practices, "
        "configuration guidelines, or recommendations.\n"
        "- **general**: Greetings, smalltalk, or anything that does not fit the above.\n\n"
        "User message: {text}"
    )

    def _get_utility_client(self) -> AzureOpenAIChatClient:
        """Return a shared client for lightweight LLM calls."""
        if self._utility_client is None:
            self._utility_client = AzureOpenAIChatClient(**self._client_kwargs)
        return self._utility_client

    async def _generate_title(self, user_text: str) -> str:
        """Generate a short conversation title via a lightweight LLM call.

        :param user_text: The first user message in the conversation.
        :returns: A short title string (≤8 words).
        """
        client = self._get_utility_client()
        prompt = self._TITLE_PROMPT.format(text=user_text[:200])
        options: ChatOptions = {"max_tokens": 500}
        response = await client.get_response(
            messages=[AFMessage("user", [prompt])],
            options=options,
        )
        return response.text or user_text[:80]

    async def classify_intent(
        self,
        user_text: str,
    ) -> InvestigationIntent:
        """Classify user text into an investigation intent via LLM.

        Uses a single structured-output call with low token budget.
        Falls back to ``GENERAL`` on empty input or LLM errors.

        :param user_text: The user's message text.
        :returns: Classified intent.
        """
        if not user_text.strip():
            return InvestigationIntent.GENERAL

        raw = ""
        try:
            client = self._get_utility_client()
            prompt = self._CLASSIFY_PROMPT.format(text=user_text[:500])
            classify_options: ChatOptions[IntentClassification] = {
                "max_tokens": 500,
                "response_format": IntentClassification,
            }
            response = await client.get_response(
                messages=[AFMessage("user", [prompt])],
                options=classify_options,
            )
            parsed = response.value
            if parsed is not None:
                raw = parsed.intent.strip().lower()
            else:
                raw = (response.text or "").strip().lower()
            return InvestigationIntent(raw)
        except (ValueError, KeyError):
            logger.warning("Intent classification returned invalid value: %r", raw)
            return InvestigationIntent.GENERAL
        except Exception:
            logger.warning("Intent classification failed, defaulting to GENERAL", exc_info=True)
            return InvestigationIntent.GENERAL

    def _build_compaction_strategy(
        self,
        token_budget: int,
    ) -> CompactionStrategy:
        """Build a token-budget compaction strategy for agent context.

        :param token_budget: Token budget from ``AgentConfig``.
        :returns: Composed compaction strategy.
        """
        tokenizer = CharacterEstimatorTokenizer()
        return TokenBudgetComposedStrategy(
            token_budget=token_budget,
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
        except BaseException:
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

    def create_workflow(
        self,
        *,
        workspace_context: Optional[str] = None,
        user_query: Optional[str] = None,
        config: Optional[AgentConfig] = None,
        thread_id: Optional[str] = None,
    ) -> Any:
        """Create a workflow for the given intent.

        - **TRIAGE / TEST**: HandoffBuilder with a triage coordinator
          that routes to domain specialists (investigator, test runner)
          in autonomous mode — each specialist has a full ReAct loop.
        - **GENERAL / KNOWLEDGE**: Single agent with all tools —
          natural think → act → observe → think loop.

        :param workspace_context: Per-conversation context string.
        :param user_query: First user message for intent classification.
        :param config: Agent configuration (from ``classify_intent``).
        :param thread_id: AG-UI thread ID for conversation persistence.
        :returns: Built Workflow instance.
        """
        if config is None:
            config = config_for_intent(InvestigationIntent.GENERAL)

        instructions = assemble(config.module_names)
        client = AzureOpenAIChatClient(**self._client_kwargs)

        context_providers: list[Any] = []
        if self._conversation_store:
            context_providers.append(
                ConversationHistoryProvider(
                    self._conversation_store,
                    title_generator=self._generate_title,
                    conversation_id=thread_id,
                    save_enabled=False,
                )
            )
        if workspace_context:
            context_providers.append(WorkspaceContextProvider(workspace_context))
        if config.inject_kb and self._retriever:
            context_providers.append(
                KnowledgeContextProvider(
                    retriever=self._retriever,
                    user_query=user_query,
                )
            )

        all_tools = [t for t in [self._mcp_tool] + self._external_mcps if t is not None]
        compaction = self._build_compaction_strategy(token_budget=config.token_budget)
        func_config = FunctionInvocationConfiguration(
            max_iterations=config.max_rounds,
            max_consecutive_errors_per_request=self._MAX_CONSECUTIVE_ERRORS,
            include_detailed_errors=False,
        )
        middleware = [
            AgentExceptionMiddleware(),
            OutputSanitizationMiddleware(),
            FunctionGuardMiddleware(),
        ]

        if config.intent in (InvestigationIntent.TRIAGE, InvestigationIntent.TEST):
            return self._build_handoff_workflow(
                client=client,
                instructions=instructions,
                config=config,
                all_tools=all_tools,
                compaction=compaction,
                func_config=func_config,
                middleware=middleware,
                context_providers=context_providers,
            )

        return self._build_single_agent_workflow(
            client=client,
            instructions=instructions,
            all_tools=all_tools,
            compaction=compaction,
            func_config=func_config,
            middleware=middleware,
            context_providers=context_providers,
            config=config,
        )

    def create_agent(
        self,
        *,
        workspace_context: Optional[str] = None,
        user_query: Optional[str] = None,
        config: Optional[AgentConfig] = None,
        thread_id: Optional[str] = None,
    ) -> Any:
        """Create a plain Agent (not wrapped in a Workflow).

        Use this for GENERAL / KNOWLEDGE intents where a single agent
        with all tools suffices.  The returned agent satisfies
        ``SupportsAgentRun`` and can be passed directly to
        ``AgentFrameworkAgent`` for native AG-UI streaming.

        :param workspace_context: Per-conversation context string.
        :param user_query: User message for KB injection.
        :param config: Agent configuration.
        :param thread_id: Conversation ID for history provider.
        :returns: An ``Agent`` instance with tools and middleware wired.
        """
        if config is None:
            config = config_for_intent(InvestigationIntent.GENERAL)

        instructions = assemble(config.module_names)

        client = AzureOpenAIResponsesClient(**self._client_kwargs)

        # CopilotKit sends full message history in each AG-UI request,
        # so ConversationHistoryProvider is not needed here (it would
        # duplicate messages and cause tool_call/result mismatches).
        context_providers: list[Any] = []
        if workspace_context:
            context_providers.append(WorkspaceContextProvider(workspace_context))
        if config.inject_kb and self._retriever:
            context_providers.append(
                KnowledgeContextProvider(
                    retriever=self._retriever,
                    user_query=user_query,
                )
            )

        all_tools = [t for t in [self._mcp_tool] + self._external_mcps if t is not None]
        compaction = self._build_compaction_strategy(
            token_budget=config.token_budget,
        )
        func_config = FunctionInvocationConfiguration(
            max_iterations=config.max_rounds,
            max_consecutive_errors_per_request=self._MAX_CONSECUTIVE_ERRORS,
            include_detailed_errors=False,
        )
        middleware = [
            AgentExceptionMiddleware(),
            OutputSanitizationMiddleware(),
            FunctionGuardMiddleware(),
        ]

        agent = client.as_agent(
            name="SAP-Agent",
            description="SAP infrastructure specialist for Azure.",
            instructions=instructions,
            tools=all_tools,
            middleware=middleware,
            function_invocation_configuration=func_config,
            compaction_strategy=compaction,
            context_providers=context_providers,
            default_options={
                "reasoning": {"effort": "medium", "summary": "concise"},
            },
        )
        logger.info("Created single agent intent=%s", config.intent.value)
        return agent

    def _build_single_agent_workflow(
        self,
        *,
        client: AzureOpenAIChatClient,
        instructions: str,
        all_tools: list,
        compaction: CompactionStrategy,
        func_config: FunctionInvocationConfiguration,
        middleware: list,
        context_providers: list,
        config: AgentConfig,
    ) -> Any:
        """Build a single-agent workflow (natural ReAct loop).

        One agent with all tools — the LLM naturally interleaves
        thinking and tool calls.  This is the simplest pattern and
        matches how GitHub Copilot works.

        :returns: Built Workflow (HandoffBuilder single-participant).
        """
        agent = client.as_agent(
            name="SAP-Agent",
            description="SAP infrastructure specialist for Azure.",
            instructions=instructions,
            tools=all_tools,
            middleware=middleware,
            function_invocation_configuration=func_config,
            compaction_strategy=compaction,
            context_providers=context_providers,
        )

        logger.info("Created single-agent workflow intent=%s", config.intent.value)
        return (
            HandoffBuilder(
                name="sap-single-agent",
                participants=[agent],
            )
            .with_start_agent(agent)
            .build()
        )

    def _build_handoff_workflow(
        self,
        *,
        client: AzureOpenAIChatClient,
        instructions: str,
        config: AgentConfig,
        all_tools: list,
        compaction: CompactionStrategy,
        func_config: FunctionInvocationConfiguration,
        middleware: list,
        context_providers: list,
    ) -> Any:
        """Build a HandoffBuilder workflow with autonomous specialists.

        - **Coordinator**: Reads the request, identifies the system,
          then routes to the right specialist.
        - **Specialists**: Built from ``config.specialists`` — each
          has its own prompt modules and role prompt.

        Each specialist iterates autonomously until done, then
        hands back to the coordinator for the final response.

        :returns: Built Workflow with handoff routing.
        """
        coordinator = client.as_agent(
            name="Coordinator",
            description="Routes requests to the right specialist.",
            instructions=instructions + COORDINATOR_ROLE_PROMPT,
            tools=all_tools,
            middleware=middleware,
            function_invocation_configuration=func_config,
            compaction_strategy=compaction,
            context_providers=context_providers,
        )

        specialists = []
        for spec in config.specialists:
            agent = client.as_agent(
                name=spec.name,
                description=spec.description,
                instructions=assemble(spec.module_names) + spec.role_prompt,
                tools=all_tools,
                middleware=middleware,
                function_invocation_configuration=func_config,
                compaction_strategy=compaction,
            )
            specialists.append(agent)

        all_agents = [coordinator] + specialists
        turn_limits: dict[str, int] = {
            "Coordinator": config.coordinator_turn_limit,
        }
        for spec in config.specialists:
            turn_limits[spec.name] = config.max_rounds

        builder = (
            HandoffBuilder(
                name="sap-handoff",
                participants=all_agents,
            )
            .with_start_agent(coordinator)
            .add_handoff(coordinator, specialists)
        )
        for agent in specialists:
            builder = builder.add_handoff(agent, [coordinator])

        logger.info("Created handoff workflow intent=%s", config.intent.value)
        return builder.with_autonomous_mode(turn_limits=turn_limits).build()

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
