# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""
Orchestrator powered by Semantic Kernel AgentGroupChat.

This orchestrator uses the Semantic Kernel Agents framework for routing
and multi-agent coordination.
"""

from typing import Optional

from semantic_kernel import Kernel
from semantic_kernel.agents.group_chat.agent_group_chat import AgentGroupChat
from semantic_kernel.agents.strategies.selection import kernel_function_selection_strategy
from semantic_kernel.agents.strategies.termination import default_termination_strategy
from semantic_kernel.contents import ChatHistory, AuthorRole

from src.agents.models.chat import ChatRequest, ChatResponse, ChatMessage
from src.agents.agents.base import AgentRegistry
from src.agents.models.streaming import emit_thinking_start, emit_thinking_step, emit_thinking_end
from src.agents.observability import get_logger


logger = get_logger(__name__)


class OrchestratorSK:
    """Routes chat requests to appropriate agents using AgentGroupChat."""

    def __init__(self, registry: AgentRegistry, kernel: Kernel) -> None:
        """Initialize orchestrator with agent registry and Semantic Kernel.

        :param registry: AgentRegistry containing available agents
        :type registry: AgentRegistry
        :param kernel: Configured Semantic Kernel instance
        :type kernel: Kernel
        """
        self.registry = registry
        self.kernel = kernel
        self.selection_strategy = self._build_selection_strategy()
        self.termination_strategy = default_termination_strategy.DefaultTerminationStrategy(
            maximum_iterations=10
        )
        logger.info("OrchestratorSK initialized with Semantic Kernel AgentGroupChat")

    def _build_selection_strategy(self) -> kernel_function_selection_strategy.KernelFunctionSelectionStrategy:
        agents = self.registry.all_agents()
        agent_summaries = [f"- {agent.name}: {agent.description}" for agent in agents]
        available_names = {agent.name for agent in agents}
        prompt = (
            "You are selecting the best agent to handle the user's latest request.\n"
            "Choose ONLY from the available agent names listed below.\n\n"
            "Available agents:\n"
            + "\n".join(agent_summaries)
            + "\n\nConversation history:\n{{$history}}\n\n"
            "Available agent names (comma-separated): {{$agent}}\n\n"
            "Return ONLY the agent name that should respond next."
        )

        selection_function = self.kernel.add_function(
            plugin_name="agent_selection",
            function_name="select_next_agent",
            prompt=prompt,
            description="Select the next agent to respond based on conversation history.",
            prompt_kwargs={"allow_dangerously_set_content": True},
        )

        def _parse_selection_result(result) -> str:
            if result is None:
                return next(iter(available_names))
            content = str(result.value if hasattr(result, "value") else result).strip()
            if content in available_names:
                return content
            first_token = content.split()[0] if content else ""
            if first_token in available_names:
                return first_token
            for name in available_names:
                if name.lower() in content.lower():
                    return name
            return next(iter(available_names))

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

        :param request: ChatRequest with conversation history
        :type request: ChatRequest
        :param context: Optional metadata for agent execution
        :type context: Optional[dict]
        :returns: ChatResponse from the selected agent(s)
        :rtype: ChatResponse
        """
        await emit_thinking_start()

        agent_chain: list[str] = []
        chat_history = ChatHistory()
        for msg in request.messages:
            if msg.role == "user":
                chat_history.add_user_message(msg.content)
            elif msg.role == "assistant":
                chat_history.add_assistant_message(msg.content)
            elif msg.role == "system":
                chat_history.add_system_message(msg.content)

        group_chat = AgentGroupChat(
            agents=self.registry.all_agents(),
            selection_strategy=self.selection_strategy,
            termination_strategy=self.termination_strategy,
            chat_history=chat_history,
        )

        final_content = ""
        iteration_count = 0

        async for message in group_chat.invoke():
            if message.role != AuthorRole.ASSISTANT:
                continue
            iteration_count += 1
            final_content = message.content or ""
            agent_name = message.name or "assistant"
            agent_chain.append(agent_name)
            await emit_thinking_step(
                agent=agent_name,
                action=f"{agent_name} responded",
                status="complete",
            )

        if not final_content:
            final_content = (
                "I've consulted the specialized agents but couldn't produce a final summary. "
                "Please try rephrasing your request."
            )

        await emit_thinking_end()

        return ChatResponse(
            messages=[ChatMessage(role="assistant", content=final_content)],
            agent_chain=agent_chain,
            reasoning_trace=None,
            metadata={"iterations": iteration_count},
        )
