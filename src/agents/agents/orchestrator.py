# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""
Orchestrator powered by Semantic Kernel AgentGroupChat.

This orchestrator uses the Semantic Kernel Agents framework for routing
and multi-agent coordination with:
- Domain-aware agent selection
- Shared context persistence across agent hops
- Automatic SID/workspace resolution
- Request-scoped context for plugins (conversation_id, user_id)
"""

from typing import Optional, Any, cast, Callable
import asyncio
import json
import re

from semantic_kernel import Kernel
from semantic_kernel.agents.group_chat.agent_group_chat import AgentGroupChat
from semantic_kernel.agents.strategies.selection import kernel_function_selection_strategy
from semantic_kernel.agents.strategies.termination.kernel_function_termination_strategy import (
    KernelFunctionTerminationStrategy,
)
from semantic_kernel.contents import ChatHistory, AuthorRole, ChatMessageContent
from semantic_kernel.functions import KernelFunction
from semantic_kernel.functions.kernel_function_from_prompt import KernelFunctionFromPrompt
from semantic_kernel.prompt_template import PromptTemplateConfig, InputVariable

from src.agents.models.chat import ChatRequest, ChatResponse, ChatMessage
from src.agents.agents.base import AgentRegistry
from src.agents.models.streaming import emit_thinking_start, emit_thinking_step, emit_thinking_end
from src.agents.observability import get_logger
from src.agents.request_context import RequestContext
from src.agents.approval_state import ApprovalStateManager
from src.agents.prompts import AGENT_SELECTION_PROMPT, TERMINATION_PROMPT


logger = get_logger(__name__)


class ConversationContext:
    """Shared context that persists across agent hops within a conversation.

    This enables agents to share discovered information without re-querying.
    """

    def __init__(self) -> None:
        self._context: dict[str, Any] = {
            "resolved_workspace": None,
            "resolved_sid": None,
            "discovered_hosts": None,
            "system_config": None,
            "os_type": None,
            "last_agent": None,
            "agent_findings": {},
        }

    def set(self, key: str, value: Any) -> None:
        """Set a context value."""
        self._context[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        """Get a context value."""
        return self._context.get(key, default)

    def add_agent_finding(self, agent_name: str, finding: dict) -> None:
        """Record findings from an agent for other agents to use."""
        if agent_name not in self._context["agent_findings"]:
            self._context["agent_findings"][agent_name] = []
        self._context["agent_findings"][agent_name].append(finding)

    def get_context_summary(self) -> str:
        """Get a summary of current context for agent prompts."""
        summary_parts = []

        if self._context["resolved_workspace"]:
            summary_parts.append(f"Workspace: {self._context['resolved_workspace']}")
        if self._context["resolved_sid"]:
            summary_parts.append(f"SAP SID: {self._context['resolved_sid']}")
        if self._context["os_type"]:
            summary_parts.append(f"OS: {self._context['os_type']}")
        if self._context["last_agent"]:
            summary_parts.append(f"Previous agent: {self._context['last_agent']}")

        return " | ".join(summary_parts) if summary_parts else "No context established yet"

    def to_dict(self) -> dict:
        """Export context as dictionary."""
        return dict(self._context)


class OrchestratorSK:
    """Routes chat requests to appropriate agents using AgentGroupChat.

    Features:
    - Domain-aware selection with SAP terminology understanding
    - Shared context persistence across agent hops (database-backed)
    - Automatic SID pattern detection
    """

    def __init__(
        self,
        registry: AgentRegistry,
        kernel: Kernel,
        conversation_manager: Optional[Any] = None,
    ) -> None:
        """Initialize orchestrator with agent registry and Semantic Kernel.

        :param registry: AgentRegistry containing available agents
        :type registry: AgentRegistry
        :param kernel: Configured Semantic Kernel instance
        :type kernel: Kernel
        :param conversation_manager: ConversationManager for persistent context
        :type conversation_manager: Optional[ConversationManager]
        """
        self.registry = registry
        self.kernel = kernel
        self._conversation_manager = conversation_manager
        self._conversation_contexts: dict[str, ConversationContext] = {}
        self.selection_strategy = self._build_selection_strategy()
        self.termination_strategy = self._build_termination_strategy()
        self._valid_sids: set[str] = set()
        self._refresh_valid_sids()

        logger.info(
            f"OrchestratorSK initialized with {len(self._valid_sids)} valid SIDs, "
            f"persistence={'enabled' if conversation_manager else 'disabled'}"
        )

    def _refresh_valid_sids(self) -> None:
        """Refresh the cache of valid SIDs from workspace store."""
        try:
            from src.agents.agents.action_executor_agent import ActionExecutorAgent

            action_executor = self.registry.get("action_executor")
            if isinstance(action_executor, ActionExecutorAgent) and action_executor.workspace_store:
                workspaces = action_executor.workspace_store.list_workspace_ids()
                self._valid_sids = set()
                for ws_id in workspaces:
                    parts = ws_id.upper().replace("-", "_").split("_")
                    for part in parts:
                        if len(part) == 3 and part[0].isalpha():
                            self._valid_sids.add(part)
                    self._valid_sids.add(ws_id.upper())
                logger.info(
                    f"Cached {len(self._valid_sids)} valid SIDs: {sorted(self._valid_sids)[:10]}..."
                )
        except Exception as e:
            logger.warning(f"Could not refresh SID cache: {e}")

    def _get_or_create_context(self, conversation_id: Optional[str]) -> ConversationContext:
        """Get or create a conversation context.

        If conversation_manager is available, loads persisted context from
        the database. Otherwise uses in-memory storage (not reliable with
        multiple workers).
        """
        if not conversation_id:
            return ConversationContext()
        if conversation_id not in self._conversation_contexts:
            self._conversation_contexts[conversation_id] = ConversationContext()
            if self._conversation_manager:
                try:
                    persisted = self._conversation_manager.get_conversation_context(conversation_id)
                    if persisted:
                        ctx = self._conversation_contexts[conversation_id]
                        if persisted.get("resolved_sid"):
                            ctx.set("resolved_sid", persisted["resolved_sid"])
                        if persisted.get("resolved_workspace"):
                            ctx.set("resolved_workspace", persisted["resolved_workspace"])
                        logger.info(
                            f"Loaded persisted context for {conversation_id}: "
                            f"SID={persisted.get('resolved_sid')}, "
                            f"workspace={persisted.get('resolved_workspace')}"
                        )
                except Exception as e:
                    logger.warning(f"Failed to load persisted context: {e}")

        return self._conversation_contexts[conversation_id]

    def _persist_context(
        self, conversation_id: Optional[str], context: ConversationContext
    ) -> None:
        """Persist context to database if conversation_manager is available."""
        if not conversation_id or not self._conversation_manager:
            return

        try:
            sid = context.get("resolved_sid")
            workspace = context.get("resolved_workspace")
            if sid or workspace:
                self._conversation_manager.update_conversation_context(
                    conversation_id=conversation_id,
                    sid=sid,
                    workspace_id=workspace,
                )
        except Exception as e:
            logger.warning(f"Failed to persist context: {e}")

    def _detect_sid_in_message(self, message: str) -> Optional[str]:
        """Detect if the message contains a valid SID from known workspaces.

        This approach is resilient because it only matches SIDs that actually
        exist in the workspace store. No exclusion lists needed - "pcs", "crm",
        "the", etc. simply won't match because they aren't real workspaces.

        :param message: User message to scan
        :type message: str
        :returns: Detected SID or None
        :rtype: Optional[str]
        """
        if not self._valid_sids:
            self._refresh_valid_sids()
            if not self._valid_sids:
                return None
        sid_pattern = r"\b([A-Za-z][A-Za-z0-9]{2})\b"
        candidates = re.findall(sid_pattern, message)
        for candidate in candidates:
            if candidate.upper() in self._valid_sids:
                logger.info(f"Detected valid SID: {candidate.upper()}")
                return candidate.upper()

        return None

    def _build_termination_strategy(self) -> KernelFunctionTerminationStrategy:
        """Build LLM-based termination strategy that evaluates conversation completion.

        Uses a KernelFunction with a termination prompt to determine if the user's
        goal has been achieved, rather than relying on fixed iteration counts.

        :returns: Configured KernelFunctionTerminationStrategy
        :rtype: KernelFunctionTerminationStrategy
        """
        prompt_config = PromptTemplateConfig(
            name="should_terminate",
            description="Evaluate if conversation goal is achieved and should terminate.",
            template=TERMINATION_PROMPT,
            input_variables=[
                InputVariable(
                    name="history",
                    description="The conversation history",
                    allow_dangerously_set_content=True,
                ),
                InputVariable(
                    name="agent",
                    description="The last agent that responded",
                    allow_dangerously_set_content=True,
                ),
            ],
            allow_dangerously_set_content=True,
        )

        termination_function = KernelFunctionFromPrompt(
            function_name="should_terminate",
            plugin_name="termination",
            prompt_template_config=prompt_config,
        )

        def _parse_termination_result(result) -> bool:
            """Parse termination result - returns True if conversation should end.

            :param result: The result from the termination function
            :returns: True if conversation should terminate, False otherwise
            :rtype: bool
            """
            if result is None:
                logger.warning("Termination check returned None, continuing conversation")
                return False

            content = str(result.value if hasattr(result, "value") else result).strip().upper()
            should_terminate = "YES" in content and "NO" not in content[:3]

            logger.info(
                f"Termination check result: '{content[:100]}' -> terminate={should_terminate}"
            )

            return should_terminate

        return KernelFunctionTerminationStrategy(
            kernel=self.kernel,
            function=termination_function,
            result_parser=_parse_termination_result,
            agent_variable_name="agent",
            history_variable_name="history",
            maximum_iterations=5,
        )

    def _build_selection_strategy(
        self,
    ) -> kernel_function_selection_strategy.KernelFunctionSelectionStrategy:
        """Build domain-aware agent selection strategy."""
        agents = self.registry.all_agents()
        agent_descriptions = "\n".join([f"- {agent.name}: {agent.description}" for agent in agents])
        available_names = {agent.name for agent in agents}

        selection_function = cast(
            KernelFunction,
            KernelFunctionFromPrompt(
                function_name="select_next_agent",
                plugin_name="agent_selection",
                prompt_template_config=PromptTemplateConfig(
                    template=AGENT_SELECTION_PROMPT,
                    description="Select the next agent based on user intent and domain context.",
                    input_variables=[
                        InputVariable(
                            name="_history_",
                            description="Conversation history (injected by SK)",
                            is_required=False,
                            allow_dangerously_set_content=True,
                        ),
                    ],
                    allow_dangerously_set_content=True,
                ),
            ),
        )

        self.kernel.add_function(plugin_name="agent_selection", function=selection_function)

        def _parse_selection_result(result) -> str:
            """Parse selection result with fallback logic."""
            if result is None:
                logger.warning("Selection returned None, defaulting to echo")
                return "echo"

            content = str(result.value if hasattr(result, "value") else result).strip().lower()
            if content in available_names:
                return content
            first_token = content.split()[0] if content else ""
            if first_token in available_names:
                return first_token

            for name in available_names:
                if name in content:
                    return name
            if any(word in content for word in ["workspace", "sid", "system", "list"]):
                return "system_context"
            if any(word in content for word in ["test", "recommend", "plan"]):
                return "test_advisor"
            if any(word in content for word in ["execute", "run", "ssh", "command", "investigate", "diagnose", "check", "analyze"]):
                return "action_executor"

            logger.warning(f"Could not parse selection result: '{content}', defaulting to echo")
            return "echo"

        return kernel_function_selection_strategy.KernelFunctionSelectionStrategy(
            kernel=self.kernel,
            function=selection_function,
            result_parser=_parse_selection_result,
        )

    async def handle_chat(
        self,
        request: ChatRequest,
        context: Optional[dict] = None,
    ) -> ChatResponse:
        """Route chat request to appropriate agents and return response.

        Sets RequestContext so plugins can access conversation_id, user_id, etc.
        without parameter injection.

        :param request: ChatRequest with conversation history
        :type request: ChatRequest
        :param context: Optional metadata for agent execution
        :type context: Optional[dict]
        :returns: ChatResponse from the selected agent(s)
        :rtype: ChatResponse
        """
        await emit_thinking_start()
        conversation_id = context.get("conversation_id") if context else None
        user_id = context.get("user_id") if context else None
        correlation_id = request.correlation_id if hasattr(request, "correlation_id") else None
        RequestContext.set(
            conversation_id=conversation_id,
            user_id=user_id,
            correlation_id=correlation_id,
        )

        if conversation_id:
            ApprovalStateManager.get_or_create(conversation_id)

        conv_context = self._get_or_create_context(conversation_id)
        latest_user_msg = ""
        for msg in reversed(request.messages):
            if msg.role == "user":
                latest_user_msg = msg.content
                break

        detected_sid = self._detect_sid_in_message(latest_user_msg)
        if detected_sid:
            old_sid = conv_context.get("resolved_sid")
            old_workspace = conv_context.get("resolved_workspace")
            if old_sid != detected_sid:
                conv_context.set("resolved_sid", detected_sid)
                logger.info(f"Updated SID: {old_sid} -> {detected_sid}")
                if old_workspace and detected_sid not in old_workspace.upper():
                    conv_context.set("resolved_workspace", None)
                    logger.info(
                        f"Cleared workspace {old_workspace} (doesn't match new SID {detected_sid})"
                    )

        preserved_sid = conv_context.get("resolved_sid")
        preserved_workspace = conv_context.get("resolved_workspace")
        if preserved_sid or preserved_workspace:
            RequestContext.update(sid=preserved_sid, workspace_id=preserved_workspace)

        logger.info(f"Context state - SID: {preserved_sid}, Workspace: {preserved_workspace}")

        agent_chain: list[str] = []
        chat_history = ChatHistory()

        context_prefix = ""
        if preserved_sid or preserved_workspace:
            context_parts = []
            if preserved_sid:
                context_parts.append(f"SAP SID: {preserved_sid}")
            if preserved_workspace:
                context_parts.append(f"Workspace: {preserved_workspace}")
            if conv_context.get("os_type"):
                context_parts.append(f"OS: {conv_context.get('os_type')}")

            context_prefix = "[CONTEXT: " + ", ".join(context_parts) + "] "
            logger.info(f"Context prefix for user message: {context_prefix}")

        last_user_idx = -1
        for i, msg in enumerate(request.messages):
            if msg.role == "user":
                last_user_idx = i

        for i, msg in enumerate(request.messages):
            if msg.role == "user":
                content = msg.content
                if i == last_user_idx and context_prefix:
                    content = context_prefix + content
                chat_history.add_user_message(content)
            elif msg.role == "assistant":
                chat_history.add_assistant_message(msg.content)
            elif msg.role == "system":
                chat_history.add_system_message(msg.content)
        agents = self.registry.all_agents()
        agent_descriptions = "\n".join([f"- {agent.name}: {agent.description}" for agent in agents])

        group_chat = AgentGroupChat(
            agents=agents,
            selection_strategy=self.selection_strategy,
            termination_strategy=self.termination_strategy,
            chat_history=chat_history,
        )

        final_content = ""
        iteration_count = 0

        try:
            async for message in group_chat.invoke():
                if message.role != AuthorRole.ASSISTANT:
                    continue

                iteration_count += 1
                final_content = message.content or ""
                agent_name = message.name or "assistant"
                agent_chain.append(agent_name)
                conv_context.set("last_agent", agent_name)
                self._extract_context_from_response(final_content, conv_context)

            if not final_content:
                final_content = (
                    "I've consulted the specialized agents but couldn't produce a final summary. "
                    "Please try rephrasing your request."
                )

            await asyncio.sleep(0.1)
        finally:
            self._persist_context(conversation_id, conv_context)
            RequestContext.clear()
            await emit_thinking_end()

        return ChatResponse(
            messages=[ChatMessage(role="assistant", content=final_content)],
            agent_chain=agent_chain,
            reasoning_trace=None,
            metadata={
                "iterations": iteration_count,
                "context": conv_context.to_dict(),
            },
        )

    def _extract_context_from_response(
        self, response: str, conv_context: ConversationContext
    ) -> None:
        """Extract OS type from agent response.

        NOTE: We intentionally DON'T extract workspace/SID from responses.
        That led to pollution when listing workspaces. Context should come from:
        1. User's message (SID detection in handle_chat)
        2. Agent explicitly resolving via tools (resolve_user_reference, etc.)

        We only extract OS type here since it's unambiguous and useful.
        """
        if not conv_context.get("os_type"):
            response_lower = response.lower()
            if "sles" in response_lower or "suse" in response_lower:
                conv_context.set("os_type", "SLES")
            elif "rhel" in response_lower or "red hat" in response_lower:
                conv_context.set("os_type", "RHEL")

    def clear_context(self, conversation_id: str) -> None:
        """Clear context for a conversation."""
        if conversation_id in self._conversation_contexts:
            del self._conversation_contexts[conversation_id]
            logger.info(f"Cleared context for conversation {conversation_id}")
