# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Chat service — bridges the API layer with Agent Framework execution.

``ChatService`` is the glue between the REST chat endpoints and the
multi-agent GroupChat workflow.  It formats conversation history into
a task message for the workflow, streams ``WorkflowEvent`` outputs
back to the caller, and persists the final assistant reply.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator
from agent_framework import (
    ResponseStream,
    WorkflowEvent,
    WorkflowRunResult,
)
from src.agents.agent import SapAgentFactory
from src.core.models.conversation import (
    Message,
    MessageRole,
)
from src.core.storage.conversation_store import ConversationStore

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChatEvent:
    """Event emitted during streaming chat processing.

    :param event_type: Type of event (``token``, ``done``, ``error``).
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
    """Bridges the chat API with Agent Framework workflow execution.

    :param factory: Agent factory for creating per-turn workflows.
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
            conversation_id, Message(role=MessageRole.USER, content=user_content)
        )
        history = self._store.get_history(conversation_id)
        task = self._build_task(history, user_content, conv.workspace_id)
        workflow = self._factory.create_workflow(
            workspace_context=self._workspace_context(conv.workspace_id),
        )
        try:
            result: WorkflowRunResult = await workflow.run(task)
            outputs = result.get_outputs()
            reply_text = str(outputs[-1]) if outputs else ""
        except Exception:
            logger.exception(
                "Workflow execution failed for conversation %s",
                conversation_id,
            )
            reply_text = self._ERROR_REPLY
        assistant_msg = Message(role=MessageRole.ASSISTANT, content=reply_text)
        self._store.add_message(conversation_id, assistant_msg)
        return assistant_msg

    async def stream_response(
        self,
        conversation_id: str,
        user_content: str,
    ) -> AsyncGenerator[ChatEvent, None]:
        """Stream the workflow response as incremental events.

        Each specialist agent output is emitted as a ``token`` event.
        The final assembled text is emitted as ``done``.

        :param conversation_id: Conversation identifier.
        :param user_content: User message text.
        :yields: ChatEvent with ``event_type`` of ``token``, ``done``, or ``error``.
        :raises ValueError: If conversation not found or archived.
        """
        conv = self._validate_conversation(conversation_id)
        self._store.add_message(
            conversation_id, Message(role=MessageRole.USER, content=user_content)
        )
        history = self._store.get_history(conversation_id)
        task = self._build_task(history, user_content, conv.workspace_id)
        workflow = self._factory.create_workflow(
            workspace_context=self._workspace_context(conv.workspace_id),
        )
        full_text = ""
        try:
            stream: ResponseStream[WorkflowEvent, WorkflowRunResult] = workflow.run(
                task, stream=True
            )
            async for event in stream:
                if event.type == "output":
                    chunk = str(event.data) if event.data else ""
                    if chunk:
                        full_text += chunk
                        yield ChatEvent(event_type="token", data={"text": chunk})

            result = await stream.get_final_response()
            if not full_text:
                outputs = result.get_outputs()
                full_text = str(outputs[-1]) if outputs else ""

            yield ChatEvent(event_type="done", data={"text": full_text})

        except Exception as exc:
            logger.exception(
                "Workflow streaming failed for conversation %s",
                conversation_id,
            )
            if not full_text:
                full_text = self._ERROR_REPLY
            yield ChatEvent(
                event_type="error",
                data={"error": str(exc), "text": full_text},
            )

        assistant_msg = Message(role=MessageRole.ASSISTANT, content=full_text)
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
        return f"Workspace: {workspace_id}" if workspace_id else ""

    @staticmethod
    def _build_task(
        history: list[Message],
        current_query: str,
        workspace_id: str | None,
    ) -> str:
        """Format conversation history and current query as a task.

        The task string is passed to ``Workflow.run()`` as the initial
        message for the GroupChat orchestrator.

        :param history: Fitted conversation history.
        :param current_query: Current user message.
        :param workspace_id: Active workspace identifier.
        :returns: Formatted task string.
        """
        parts: list[str] = []
        if workspace_id:
            parts.append(f"[Workspace: {workspace_id}]")

        prior = [
            m
            for m in history
            if m.role in (MessageRole.USER, MessageRole.ASSISTANT) and m.content != current_query
        ]
        if prior:
            parts.append("Previous conversation:")
            for msg in prior[-10:]:
                role = "User" if msg.role == MessageRole.USER else "Assistant"
                parts.append(f"  {role}: {msg.content}")
            parts.append("")

        parts.append(f"Current request: {current_query}")
        return "\n".join(parts)
