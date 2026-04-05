# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Chat service — bridges the API layer with Agent Framework execution.

``ChatService`` is the glue between the REST chat endpoints and the
Agent Framework.  It formats conversation history, streams
events back to the caller in real time
(including tool calls and reasoning), and persists the final reply.
"""

from __future__ import annotations
import json
import logging
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator

from agent_framework import (
    AgentResponse,
    AgentResponseUpdate,
    ResponseStream,
)
from agent_framework._types import Message as AFMessage
from src.agents.agent import SapAgentFactory
from src.core.models.conversation import (
    Message,
    MessageRole,
)
from src.core.storage.conversation_store import ConversationStore

logger = logging.getLogger(__name__)


def _extract_text(update: AgentResponseUpdate) -> str:
    """Extract visible text from a streaming update.

    :param update: An ``AgentResponseUpdate`` from the agent stream.
    :returns: Extracted text, or empty string.
    """
    return update.text or ""


def _extract_thinking(update: AgentResponseUpdate) -> str:
    """Extract ``text_reasoning`` content from an update.

    :param update: An ``AgentResponseUpdate``.
    :returns: Concatenated reasoning text, or empty string.
    """
    parts: list[str] = []
    for content in update.contents:
        if content.type == "text_reasoning" and content.text:
            parts.append(content.text)
    return "\n".join(parts)


def _extract_activities(update: AgentResponseUpdate) -> list[dict[str, Any]]:
    """Extract tool activity from a streaming update.

    Captures both ``function_call`` (what's being called) and
    ``function_result`` (what came back) content types to give the
    UI a complete picture of agent investigation steps.

    :param update: An ``AgentResponseUpdate``.
    :returns: List of activity dicts with ``type`` and details.
    """
    activities: list[dict[str, Any]] = []
    for c in update.contents:
        d = c.to_dict()
        if c.type == "function_call":
            name = d.get("name", "")
            args_str = d.get("arguments", "")
            if not name:
                continue
            try:
                args = json.loads(args_str) if args_str else {}
            except (json.JSONDecodeError, TypeError):
                args = {}
            desc = name
            if name == "run_evidence_collector" and args.get("definition_id"):
                desc = args["definition_id"]
            elif name == "get_workspace" and args.get("workspace_id"):
                desc = f"workspace {args['workspace_id']}"
            elif name == "query_knowledge" and args.get("query"):
                desc = f"search: {args['query'][:50]}"
            activities.append(
                {
                    "phase": "call",
                    "tool": name,
                    "description": desc,
                }
            )
        elif c.type == "function_result":
            result_text = d.get("result", "")
            preview = result_text[:200] if result_text else ""
            activities.append(
                {
                    "phase": "result",
                    "tool": d.get("call_id", ""),
                    "preview": preview,
                }
            )
    return activities


@dataclass(frozen=True)
class ChatEvent:
    """Event emitted during streaming chat processing.

    :param event_type: ``token``, ``thinking``, ``activity``,
        ``done``, or ``error``.
    :param data: Event payload dict.
    """

    event_type: str
    data: dict[str, Any] = field(default_factory=dict)

    def to_sse(self) -> str:
        """Format as a Server-Sent Event line pair.

        :returns: SSE-formatted string ending with double newline.
        """
        return f"event: {self.event_type}\ndata: {json.dumps(self.data)}\n\n"


class ChatService:
    """Bridges the chat API with Agent Framework execution.

    Uses formalized sequential workflows for execution.

    :param factory: Agent factory for creating workflows.
    :param conversation_store: Persistence layer for conversations.
    """

    _ERROR_REPLY = (
        "I encountered an error while processing your request. "
        "Please try again or rephrase your question."
    )

    def __init__(
        self,
        factory: SapAgentFactory,
        conversation_store: ConversationStore,
    ) -> None:
        self._factory = factory
        self._store = conversation_store
        self._sessions: dict[str, Any] = {}

    @property
    def factory(self) -> SapAgentFactory:
        """The agent factory backing this service."""
        return self._factory

    async def send_message(
        self,
        conversation_id: str,
        user_content: str,
    ) -> Message:
        """Process a user message and return the assistant response.

        :param conversation_id: Conversation identifier.
        :param user_content: User message text.
        :returns: The persisted assistant response message.
        :raises ValueError: If conversation not found or archived.
        """
        conv = self._validate_conversation(conversation_id)
        self._store.add_message(
            conversation_id,
            Message(role=MessageRole.USER, content=user_content),
        )
        workflow = self._factory.create_workflow(
            workspace_context=self._workspace_context(conv.workspace_id),
            user_query=user_content,
        )
        try:
            response = await workflow.run(message=user_content, stream=False)
            reply_text = ""
            if hasattr(response, "output") and response.output:
                if isinstance(response.output, list) and hasattr(response.output[-1], 'content'):
                    reply_text = str(response.output[-1].content)
                elif hasattr(response.output, "text"):
                    reply_text = response.output.text or ""
                elif isinstance(response.output, str):
                    reply_text = response.output
            metadata: dict[str, Any] = {}
        except Exception:
            logger.exception(
                "Workflow execution failed for conversation %s",
                conversation_id,
            )
            reply_text = self._ERROR_REPLY
            metadata = {}

        assistant_msg = Message(
            role=MessageRole.ASSISTANT,
            content=reply_text,
            metadata=metadata,
        )
        self._store.add_message(conversation_id, assistant_msg)
        return assistant_msg

    async def stream_response(
        self,
        conversation_id: str,
        user_content: str,
    ) -> AsyncGenerator[ChatEvent, None]:
        """Stream the workflow response as incremental events.

        :param conversation_id: Conversation identifier.
        :param user_content: User message text.
        :yields: ``ChatEvent`` instances in real time.
        :raises ValueError: If conversation not found or archived.
        """
        conv = self._validate_conversation(conversation_id)
        self._store.add_message(
            conversation_id,
            Message(role=MessageRole.USER, content=user_content),
        )
        workflow = self._factory.create_workflow(
            workspace_context=self._workspace_context(conv.workspace_id),
            user_query=user_content,
        )
        streamed_text = ""
        metadata: dict[str, Any] = {}
        try:
            stream = workflow.run(message=user_content, stream=True)

            async for event in stream:
                # Handle streaming from multiple agents in the workflow graph
                if event.type == "data" and isinstance(event.data, AgentResponseUpdate):
                    update = event.data
                    agent_name = event.executor_id or "SAP-Agent"
                    
                    for act in _extract_activities(update):
                        yield ChatEvent(
                            event_type="activity",
                            data=act,
                        )

                    reasoning = _extract_thinking(update)
                    if reasoning:
                        yield ChatEvent(
                            event_type="thinking",
                            data={"agent": agent_name, "text": reasoning},
                        )

                    chunk = _extract_text(update)
                    if chunk:
                        streamed_text += chunk
                        yield ChatEvent(
                            event_type="token",
                            data={"agent": agent_name, "text": chunk},
                        )

            response = await stream.get_final_response()
            if hasattr(response, "output") and response.output:
                if isinstance(response.output, list) and hasattr(response.output[-1], 'content'):
                    streamed_text = str(response.output[-1].content)
                elif hasattr(response.output, "text") and response.output.text:
                    streamed_text = response.output.text
                elif isinstance(response.output, str):
                    streamed_text = response.output
            
            logger.info("Workflow produced stream of %d chars.", len(streamed_text))
            yield ChatEvent(
                event_type="done",
                data={"text": streamed_text},
            )

        except Exception as exc:
            logger.exception(
                "Workflow streaming failed for conversation %s",
                conversation_id,
            )
            if not streamed_text:
                streamed_text = self._ERROR_REPLY
            yield ChatEvent(
                event_type="error",
                data={"error": str(exc), "text": streamed_text},
            )

        assistant_msg = Message(
            role=MessageRole.ASSISTANT,
            content=streamed_text,
            metadata=metadata,
        )
        self._store.add_message(conversation_id, assistant_msg)

    def _validate_conversation(self, conversation_id: str) -> Any:
        """Load and validate a conversation exists and is active.

        :param conversation_id: Conversation identifier.
        :returns: The conversation object.
        :raises ValueError: If not found or archived.
        """
        conv = self._store.get(conversation_id)
        if conv is None:
            raise ValueError(f"Conversation {conversation_id} not found")
        if conv.is_archived:
            raise ValueError("Cannot send messages to an archived conversation")
        return conv

    @staticmethod
    def _workspace_context(workspace_id: str | None) -> str:
        """Format workspace context for agent instructions.

        :param workspace_id: Active workspace identifier.
        :returns: Context string or empty.
        """
        if workspace_id:
            return f"Active workspace: {workspace_id}"
        return (
            "No workspace is set for this conversation. "
            "If the user mentions a system by name or identifier "
            "(e.g. 'X02', 'S11', 'PRD'), use `list_workspaces` to "
            "find the matching workspace and proceed autonomously."
        )

    @staticmethod
    def _build_task(
        history: list[Message],
        current_query: str,
        workspace_id: str | None,
    ) -> list[AFMessage]:
        """Format conversation history as Agent Framework messages.

        :param history: Fitted conversation history.
        :param current_query: Current user message.
        :param workspace_id: Active workspace identifier.
        :returns: List of chat messages for the agent.
        """
        messages: list[AFMessage] = []

        if workspace_id:
            messages.append(AFMessage("user", [f"[Context: Active workspace is {workspace_id}]"]))
            messages.append(AFMessage("assistant", ["Understood."]))

        prior = [
            m
            for m in history
            if m.role in (MessageRole.USER, MessageRole.ASSISTANT) and m.content != current_query
        ]
        for msg in prior[-10:]:
            role = "user" if msg.role == MessageRole.USER else "assistant"
            messages.append(AFMessage(role, [msg.content]))

        messages.append(AFMessage("user", [current_query]))
        return messages
