# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Chat API routes — conversation CRUD and message exchange."""

import logging
from typing import Any, Optional
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from src.core.services.chat import ChatService
from src.core.models.conversation import (
    Conversation,
    CreateConversationRequest,
    Message,
    MessageRole,
    SendMessageRequest,
)
from src.core.storage.conversation_store import ConversationStore

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chat", tags=["chat"])

_conversation_store: Optional[ConversationStore] = None
_chat_service: Optional[ChatService] = None


def set_conversation_store(store: ConversationStore) -> None:
    """Inject the conversation store (called from lifespan).

    :param store: ConversationStore instance.
    """
    global _conversation_store
    _conversation_store = store


def set_chat_service(service: ChatService) -> None:
    """Inject the chat service (called from lifespan).

    :param service: ChatService instance wired with an agent factory.
    """
    global _chat_service
    _chat_service = service


def get_conversation_store() -> ConversationStore:
    """Get the conversation store.

    :returns: Configured ConversationStore.
    :raises HTTPException: If not initialized (503).
    """
    if _conversation_store is None:
        raise HTTPException(
            status_code=503,
            detail="Conversation store not initialized",
        )
    return _conversation_store


def get_chat_service() -> Optional[ChatService]:
    """Get the chat service, or None if not configured.

    :returns: ChatService if agent is wired, else None.
    """
    return _chat_service


def _summarize(conv: Conversation) -> dict[str, Any]:
    """Serialize a Conversation to a JSON-safe summary dict."""
    data = conv.model_dump(mode="json", exclude={"messages", "metadata"})
    data["message_count"] = conv.message_count
    return data


def _detail(conv: Conversation) -> dict[str, Any]:
    """Serialize a Conversation with full message history."""
    return conv.model_dump(mode="json", exclude={"metadata"})


@router.post("", status_code=201)
async def create_conversation(
    request: CreateConversationRequest,
) -> dict[str, Any]:
    """Create a new conversation for a workspace.

    :param request: Workspace ID for the conversation.
    :returns: Created conversation metadata.
    """
    conv = Conversation(workspace_id=request.workspace_id)
    get_conversation_store().create(conv)
    logger.info("Created conversation %s for workspace %s", conv.id, conv.workspace_id)
    return _summarize(conv)


@router.get("")
async def list_conversations(
    workspace_id: str = Query(..., description="Filter by workspace"),
    include_archived: bool = Query(False, description="Include archived"),
    limit: int = Query(50, ge=1, le=200, description="Max results"),
) -> dict[str, Any]:
    """List conversations for a workspace.

    :param workspace_id: Workspace to list conversations for.
    :param include_archived: Whether to include archived conversations.
    :param limit: Maximum results.
    :returns: List of conversations.
    """
    conversations = get_conversation_store().list_conversations(
        workspace_id=workspace_id,
        include_archived=include_archived,
        limit=limit,
    )
    return {
        "conversations": [_summarize(c) for c in conversations],
        "total": len(conversations),
    }


@router.get("/{conversation_id}")
async def get_conversation(conversation_id: str) -> dict[str, Any]:
    """Get a conversation with full message history.

    :param conversation_id: Conversation ID.
    :returns: Conversation with all messages.
    """
    conv = get_conversation_store().get(conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return _detail(conv)


@router.get("/{conversation_id}/messages")
async def get_messages(
    conversation_id: str,
    limit: Optional[int] = Query(None, ge=1, le=500, description="Max messages"),
) -> list[dict[str, Any]]:
    """Get messages for a conversation.

    :param conversation_id: Conversation ID.
    :param limit: Optional message limit.
    :returns: Ordered list of messages.
    """
    store = get_conversation_store()
    conv = store.get(conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    messages = store.get_history(conversation_id, limit=limit)
    return [m.model_dump(mode="json", exclude={"metadata"}) for m in messages]


@router.post("/{conversation_id}/messages", status_code=201)
async def send_message(
    conversation_id: str,
    request: SendMessageRequest,
) -> dict[str, Any]:
    """Send a user message and get the assistant response.

    When the ``ChatService`` is configured (agent factory wired), the
    message is processed by the Agent Framework.  Otherwise a
    placeholder response is returned.

    :param conversation_id: Conversation to send the message in.
    :param request: Message content.
    :returns: The assistant response message.
    """
    store = get_conversation_store()
    conv = store.get(conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if conv.is_archived:
        raise HTTPException(
            status_code=400,
            detail="Cannot add messages to an archived conversation",
        )

    service = get_chat_service()
    if service is not None:
        assistant_msg = await service.send_message(conversation_id, request.message)
        return assistant_msg.model_dump(mode="json", exclude={"metadata"})

    store.add_message(conversation_id, Message(role=MessageRole.USER, content=request.message))
    assistant_msg = Message(
        role=MessageRole.ASSISTANT,
        content=(
            "Chat service is not configured. Set AZURE_OPENAI_ENDPOINT "
            "and AZURE_OPENAI_DEPLOYMENT to enable agent-driven responses."
        ),
        metadata={"phase": "unconfigured"},
    )
    store.add_message(conversation_id, assistant_msg)
    return assistant_msg.model_dump(mode="json", exclude={"metadata"})


@router.post("/{conversation_id}/messages/stream")
async def stream_message(
    conversation_id: str,
    request: SendMessageRequest,
) -> StreamingResponse:
    """Stream the assistant response as Server-Sent Events.

    :param conversation_id: Conversation to stream in.
    :param request: Message content.
    :returns: SSE streaming response.
    """
    conv = get_conversation_store().get(conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if conv.is_archived:
        raise HTTPException(
            status_code=400,
            detail="Cannot add messages to an archived conversation",
        )

    service = get_chat_service()
    if service is None:
        raise HTTPException(
            status_code=503,
            detail="Chat service not configured — agent is unavailable",
        )

    async def event_generator():
        async for event in service.stream_response(conversation_id, request.message):
            yield event.to_sse()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/{conversation_id}/archive")
async def archive_conversation(conversation_id: str) -> dict[str, str]:
    """Archive a conversation.

    :param conversation_id: Conversation to archive.
    :returns: Confirmation dict.
    """
    store = get_conversation_store()
    try:
        success = store.archive(conversation_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not success:
        raise HTTPException(status_code=404, detail="Conversation not found")

    return {"status": "archived", "conversation_id": conversation_id}
