# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Chat API routes for agent interaction."""

from typing import Optional

from fastapi import APIRouter, Query

from src.agents.models import ChatMessage, ChatRequest, ChatResponse
from src.agents.agents.orchestrator import OrchestratorSK
from src.agents.persistence import ConversationManager
from src.agents.logging_config import get_logger, set_correlation_id

logger = get_logger(__name__)

router = APIRouter(tags=["chat"])
_orchestrator: Optional[OrchestratorSK] = None
_conversation_manager: Optional[ConversationManager] = None


def get_orchestrator() -> Optional[OrchestratorSK]:
    """Get the global orchestrator instance.

    :returns: OrchestratorSK instance or None
    :rtype: Optional[OrchestratorSK]
    """
    return _orchestrator


def set_orchestrator(orchestrator: OrchestratorSK) -> None:
    """Set the global orchestrator instance.

    :param orchestrator: OrchestratorSK instance to use
    :type orchestrator: OrchestratorSK
    """
    global _orchestrator
    _orchestrator = orchestrator


def get_chat_conversation_manager() -> Optional[ConversationManager]:
    """Get the global conversation manager instance.

    :returns: ConversationManager instance or None
    :rtype: Optional[ConversationManager]
    """
    return _conversation_manager


def set_chat_conversation_manager(manager: ConversationManager) -> None:
    """Set the global conversation manager instance.

    :param manager: ConversationManager instance to use
    :type manager: ConversationManager
    """
    global _conversation_manager
    _conversation_manager = manager


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    conversation_id: Optional[str] = Query(None, description="Existing conversation ID"),
    user_id: Optional[str] = Query(None, description="User ID for new conversations"),
) -> ChatResponse:
    """Chat endpoint that routes to appropriate agent via orchestrator.

    If conversation_id is provided, loads history from that conversation
    and appends the new message. Otherwise creates a new conversation.

    :param request: Chat request with messages
    :type request: ChatRequest
    :param conversation_id: Optional existing conversation ID
    :type conversation_id: Optional[str]
    :param user_id: User ID for new conversations
    :type user_id: Optional[str]
    :returns: Chat response from agent
    :rtype: ChatResponse
    """
    if _orchestrator is None or _conversation_manager is None:
        return ChatResponse(
            messages=[ChatMessage(role="assistant", content="Service not initialized")],
            correlation_id=request.correlation_id,
            reasoning_trace=None,
        )

    correlation_id = set_correlation_id(request.correlation_id)
    logger.info(f"Received chat request with {len(request.messages)} messages")
    turn_index = 0
    active_conversation_id = conversation_id

    if conversation_id:
        existing_messages = _conversation_manager.get_chat_history(conversation_id)
        if existing_messages:
            new_user_content = _extract_last_user_message(request.messages)

            if new_user_content:
                chat_history, turn_index = _conversation_manager.process_chat_request(
                    conversation_id=conversation_id,
                    user_message=new_user_content,
                )
                request = ChatRequest(
                    messages=chat_history,
                    correlation_id=correlation_id,
                )
    else:
        conversation = _conversation_manager.create_conversation(user_id=user_id)
        active_conversation_id = str(conversation.id)
        new_user_content = _extract_last_user_message(request.messages)

        if new_user_content:
            chat_history, turn_index = _conversation_manager.process_chat_request(
                conversation_id=active_conversation_id,
                user_message=new_user_content,
            )
            _conversation_manager.generate_title_from_first_message(active_conversation_id)

    response = await _orchestrator.handle_chat(
        request, context={"conversation_id": active_conversation_id}
    )

    if active_conversation_id:
        _conversation_manager.process_chat_response(
            conversation_id=active_conversation_id,
            response=response,
            turn_index=turn_index,
        )

    logger.info(f"Returning response with {len(response.messages)} messages")
    response.correlation_id = correlation_id
    return response


def _extract_last_user_message(messages: list[ChatMessage]) -> str:
    """Extract the last user message content from a list of messages.

    :param messages: List of chat messages
    :type messages: list[ChatMessage]
    :returns: Content of last user message or empty string
    :rtype: str
    """
    for msg in reversed(messages):
        if msg.role == "user":
            return msg.content
    return ""
