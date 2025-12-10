# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""API routes for conversation management.

This module provides REST endpoints for:
- Listing user conversations (GET /conversations)
- Getting a specific conversation (GET /conversations/{id})
- Updating conversations (PATCH /conversations/{id})
- Deleting conversations (DELETE /conversations/{id})
- Getting messages from a conversation (GET /conversations/{id}/messages)

Note: To chat and get AI responses, use the /chat endpoint instead.
"""

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from src.agents.models import (
    ConversationDetailResponse,
    ConversationListResponse,
    ConversationResponse,
    MessageListResponse,
    UpdateConversationRequest,
)
from src.agents.persistence import ConversationManager

router = APIRouter(prefix="/conversations", tags=["conversations"])

_conversation_manager: Optional[ConversationManager] = None


def get_conversation_manager() -> ConversationManager:
    """Get the global conversation manager instance.

    :returns: ConversationManager instance
    :rtype: ConversationManager
    :raises RuntimeError: If manager not initialized
    """
    if _conversation_manager is None:
        raise RuntimeError("ConversationManager not initialized")
    return _conversation_manager


def set_conversation_manager(manager: ConversationManager) -> None:
    """Set the global conversation manager instance.

    :param manager: ConversationManager instance to use
    :type manager: ConversationManager
    """
    global _conversation_manager
    _conversation_manager = manager


@router.get("", response_model=ConversationListResponse)
async def list_conversations(
    user_id: Optional[str] = Query(None, description="Filter by user ID"),
    workspace_id: Optional[str] = Query(None, description="Filter by workspace ID"),
    limit: int = Query(50, ge=1, le=100, description="Maximum results to return"),
    offset: int = Query(0, ge=0, description="Number of results to skip"),
) -> ConversationListResponse:
    """List conversations for sidebar display.

    Returns lightweight conversation items with just id, title, and updated_at
    (like GitHub Copilot or M365 Copilot sidebar).

    :param user_id: Optional user ID to filter by
    :type user_id: Optional[str]
    :param workspace_id: Optional workspace ID to filter by
    :type workspace_id: Optional[str]
    :param limit: Maximum number of conversations to return
    :type limit: int
    :param offset: Number of conversations to skip (for pagination)
    :type offset: int
    :returns: List of conversation items with pagination info
    :rtype: ConversationListResponse
    """
    manager = get_conversation_manager()
    conversations = manager.list_conversation_items(
        user_id=user_id,
        workspace_id=workspace_id,
        limit=limit,
        offset=offset,
    )

    total = len(conversations) + offset
    if len(conversations) == limit:
        total = offset + limit + 1

    return ConversationListResponse(
        conversations=conversations,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{conversation_id}", response_model=ConversationDetailResponse)
async def get_conversation(
    conversation_id: str,
    message_limit: int = Query(100, ge=1, le=500, description="Maximum messages to include"),
) -> ConversationDetailResponse:
    """Get a conversation with its messages.

    :param conversation_id: Conversation ID
    :type conversation_id: str
    :param message_limit: Maximum number of messages to include
    :type message_limit: int
    :returns: Conversation with messages
    :rtype: ConversationDetailResponse
    :raises HTTPException: 404 if conversation not found
    """
    manager = get_conversation_manager()
    result = manager.get_conversation_with_messages(
        conversation_id=conversation_id,
        message_limit=message_limit,
    )

    if not result:
        raise HTTPException(status_code=404, detail="Conversation not found")

    return ConversationDetailResponse(
        conversation=result.conversation,
        messages=result.messages,
        message_count=result.message_count,
    )


@router.patch("/{conversation_id}", response_model=ConversationResponse)
async def update_conversation(
    conversation_id: str,
    request: UpdateConversationRequest,
) -> ConversationResponse:
    """Update a conversation's title or workspace.

    :param conversation_id: Conversation ID
    :type conversation_id: str
    :param request: Update request
    :type request: UpdateConversationRequest
    :returns: Updated conversation
    :rtype: ConversationResponse
    :raises HTTPException: 404 if conversation not found
    """
    manager = get_conversation_manager()

    conversation = manager.get_conversation(conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    if request.title is not None:
        manager.update_conversation_title(conversation_id, request.title)

    if request.workspace_id is not None:
        manager.set_workspace(conversation_id, request.workspace_id)

    updated = manager.get_conversation(conversation_id)
    if not updated:
        raise HTTPException(status_code=404, detail="Conversation not found")

    return ConversationResponse(conversation=updated)


@router.delete("/{conversation_id}", status_code=204)
async def delete_conversation(conversation_id: str) -> None:
    """Delete a conversation and all its messages.

    :param conversation_id: Conversation ID
    :type conversation_id: str
    :raises HTTPException: 404 if conversation not found
    """
    manager = get_conversation_manager()
    deleted = manager.delete_conversation(conversation_id)

    if not deleted:
        raise HTTPException(status_code=404, detail="Conversation not found")


@router.get("/{conversation_id}/messages", response_model=MessageListResponse)
async def get_messages(
    conversation_id: str,
    limit: int = Query(100, ge=1, le=500, description="Maximum messages to return"),
) -> MessageListResponse:
    """Get messages from a conversation.

    :param conversation_id: Conversation ID
    :type conversation_id: str
    :param limit: Maximum number of messages to return
    :type limit: int
    :returns: List of messages
    :rtype: MessageListResponse
    :raises HTTPException: 404 if conversation not found
    """
    manager = get_conversation_manager()

    conversation = manager.get_conversation(conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    messages = manager.get_messages(conversation_id, limit=limit)

    return MessageListResponse(
        messages=messages,
        conversation_id=conversation_id,
    )
