# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""
Echo agent powered by Semantic Kernel for documentation assistance.

This agent uses Semantic Kernel with DocumentationPlugin for intelligent
documentation-based help using function calling.
"""

from typing import Optional

from semantic_kernel import Kernel
from semantic_kernel.contents import ChatHistory

from src.agents.models.chat import ChatMessage, ChatResponse
from src.agents.agents.base import Agent
from src.agents.plugins.documentation import DocumentationPlugin
from src.agents.prompts import ECHO_AGENT_SK_SYSTEM_PROMPT
from src.agents.models.reasoning import sanitize_snapshot
from src.agents.logging_config import get_logger

logger = get_logger(__name__)


class EchoAgentSK(Agent):
    """Agent for providing documentation-based help using Semantic Kernel.

    This agent uses SK's native function calling to interact with documentation,
    allowing the LLM to autonomously choose which documentation to retrieve.
    """

    def __init__(self, kernel: Kernel) -> None:
        """Initialize EchoAgent with Semantic Kernel.

        :param kernel: Configured Semantic Kernel instance
        :type kernel: Kernel
        """
        super().__init__(
            name="echo",
            description="Provides general help and information about the SAP QA assistant using "
            + "documentation context. Use for greetings, general questions, or when user intent is unclear.",
        )

        self.kernel = kernel
        documentation_plugin = DocumentationPlugin()
        self.kernel.add_plugin(plugin=documentation_plugin, plugin_name="Documentation")

        logger.info("EchoAgentSK initialized with Semantic Kernel and Documentation plugin")

    async def run(
        self,
        messages: list[ChatMessage],
        context: Optional[dict] = None,
    ) -> ChatResponse:
        """Execute the Echo agent using Semantic Kernel with documentation functions.

        This method uses SK's native function calling to let the LLM
        decide which documentation operations to perform.

        :param messages: List of ChatMessage objects from the conversation
        :type messages: list[ChatMessage]
        :param context: Optional context dictionary
        :type context: Optional[dict]
        :returns: ChatResponse with the agent's response
        :rtype: ChatResponse
        """
        logger.info(f"EchoAgentSK.run called with {len(messages)} messages")

        self.tracer.start()

        try:
            self.tracer.step(
                "documentation_retrieval",
                "tool_call",
                "Processing documentation assistance request with SK",
                input_snapshot=sanitize_snapshot(
                    {"message_count": len(messages), "has_context": context is not None}
                ),
            )

            chat_history = ChatHistory()
            chat_history.add_system_message(ECHO_AGENT_SK_SYSTEM_PROMPT)
            for msg in messages:
                if msg.role == "user":
                    chat_history.add_user_message(msg.content)
                elif msg.role == "assistant":
                    chat_history.add_assistant_message(msg.content)

            logger.info(f"Chat history prepared with {len(chat_history.messages)} messages")

            chat_service = self.kernel.get_service(service_id="azure_openai_chat")
            execution_settings = chat_service.get_prompt_execution_settings_class()(
                function_choice_behavior="auto",
                max_completion_tokens=2000,
            )
            logger.info("Calling SK chat completion with function calling enabled")
            response = await chat_service.get_chat_message_content(
                chat_history=chat_history,
                settings=execution_settings,
                kernel=self.kernel,
            )

            logger.info("SK chat completion returned successfully")
            response_content = str(response) if response else ""
            self.tracer.step(
                "response_generation",
                "inference",
                "Generated documentation-based response",
                output_snapshot=sanitize_snapshot(
                    {
                        "response_length": len(response_content),
                        "has_content": bool(response_content),
                    }
                ),
            )

            response_message = ChatMessage(
                role="assistant",
                content=response_content,
            )

            return ChatResponse(
                messages=[response_message], reasoning_trace=self.tracer.get_trace()
            )

        except Exception as e:
            logger.error(f"Error in EchoAgentSK: {type(e).__name__}: {e}", exc_info=True)

            self.tracer.step(
                "response_generation",
                "inference",
                f"Error during documentation assistance: {str(e)}",
                error=str(e),
                output_snapshot=sanitize_snapshot({"error_type": type(e).__name__}),
            )

            raise

        finally:
            self.tracer.finish()
