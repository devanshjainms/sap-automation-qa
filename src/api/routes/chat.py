# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Chat API routes for agent interaction."""

import asyncio
import json
from typing import AsyncGenerator, Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse
from semantic_kernel import Kernel
from semantic_kernel.contents import ChatHistory

from src.agents.models import ChatMessage, ChatRequest, ChatResponse
from src.agents.models.streaming import (
    StreamEvent,
    StreamEventType,
    set_stream_callback,
)
from src.agents.agents.orchestrator import OrchestratorSK
from src.agents.persistence import ConversationManager
from src.agents.observability import get_logger, set_correlation_id, get_correlation_id

logger = get_logger(__name__)

router = APIRouter(tags=["chat"])
_orchestrator: Optional[OrchestratorSK] = None
_conversation_manager: Optional[ConversationManager] = None
_kernel: Optional[Kernel] = None


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


def set_chat_kernel(kernel: Kernel) -> None:
    """Set the global kernel instance for AI operations.

    :param kernel: Kernel instance to use
    :type kernel: Kernel
    """
    global _kernel
    _kernel = kernel


async def _generate_ai_title(user_message: str) -> str:
    """Generate a concise title for a conversation using AI.

    :param user_message: First user message in the conversation
    :type user_message: str
    :returns: Generated title (max 50 chars)
    :rtype: str
    """
    logger.info(f"_generate_ai_title called, _kernel is None: {_kernel is None}")
    if not _kernel:
        title = user_message[:50]
        if len(user_message) > 50:
            title = title[:47] + "..."
        logger.info(f"Using fallback title (no kernel): {title}")
        return title

    try:
        chat_service = _kernel.get_service(service_id="azure_openai_chat")
        logger.info(f"Got chat service: {chat_service}")
        execution_settings = chat_service.get_prompt_execution_settings_class()(
            max_completion_tokens=100,
        )

        chat_history = ChatHistory()
        chat_history.add_system_message(
            "Generate a very short title (max 6 words) for a conversation that starts with "
            "the following message. Return ONLY the title, no quotes or punctuation."
        )
        chat_history.add_user_message(user_message)
        response = await chat_service.get_chat_message_content(
            chat_history=chat_history,
            settings=execution_settings,
            kernel=_kernel,
        )

        title = str(response.content).strip() if response.content else user_message[:50]
        if len(title) > 60:
            title = title[:57] + "..."
        logger.info(f"AI generated title: {title}")
        return title

    except Exception as e:
        logger.warning(f"AI title generation failed, using fallback: {e}")
        title = user_message[:50]
        if len(user_message) > 50:
            title = title[:47] + "..."
        return title


async def _generate_title_background(conversation_id: str, user_message: str) -> None:
    """Background task to generate and save AI title.

    :param conversation_id: Conversation ID
    :type conversation_id: str
    :param user_message: First user message
    :type user_message: str
    """
    logger.info(f"Background title generation started for {conversation_id}")
    if not _conversation_manager:
        logger.warning("No conversation manager available for title generation")
        return

    try:
        title = await _generate_ai_title(user_message)
        _conversation_manager.update_conversation_title(conversation_id, title)
        logger.info(f"Generated AI title for conversation {conversation_id}: {title}")
    except Exception as e:
        logger.error(f"Background title generation failed for {conversation_id}: {e}")


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    conversation_id: Optional[str] = Query(None, description="Existing conversation ID"),
    user_id: Optional[str] = Query(None, description="User ID for new conversations"),
) -> ChatResponse:
    """Chat endpoint that routes to appropriate agent via orchestrator.

    If conversation_id is provided, loads history from that conversation
    and appends the new message. Otherwise creates a new conversation.
    For new conversations, an AI-generated title is created in the background.

    :param request: Chat request with messages
    :type request: ChatRequest
    :param background_tasks: FastAPI background tasks
    :type background_tasks: BackgroundTasks
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
            metadata=None,
        )

    # Use request correlation_id if provided, otherwise use middleware-set value
    correlation_id = (
        set_correlation_id(request.correlation_id)
        if request.correlation_id
        else get_correlation_id()
    )
    logger.info(f"Received chat request with {len(request.messages)} messages")
    turn_index = 0
    active_conversation_id = conversation_id
    is_new_conversation = False
    first_user_message = ""

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
                    workspace_ids=request.workspace_ids or [],
                )
    else:
        conversation = _conversation_manager.create_conversation(user_id=user_id)
        active_conversation_id = str(conversation.id)
        first_user_message = _extract_last_user_message(request.messages)
        is_new_conversation = True

        if first_user_message:
            chat_history, turn_index = _conversation_manager.process_chat_request(
                conversation_id=active_conversation_id,
                user_message=first_user_message,
            )

    response = await _orchestrator.handle_chat(
        request,
        context={
            "conversation_id": active_conversation_id,
            "workspace_ids": request.workspace_ids or [],
        },
    )

    if active_conversation_id:
        _conversation_manager.process_chat_response(
            conversation_id=active_conversation_id,
            response=response,
            turn_index=turn_index,
        )

    if is_new_conversation and first_user_message and active_conversation_id:
        logger.info(f"Generating AI title for new conversation {active_conversation_id}")
        try:
            title = await _generate_ai_title(first_user_message)
            _conversation_manager.update_conversation_title(active_conversation_id, title)
            logger.info(f"Set AI-generated title: {title}")
        except Exception as e:
            logger.warning(f"Failed to generate AI title: {e}")

    logger.info(f"Returning response with {len(response.messages)} messages")
    response.correlation_id = correlation_id

    if response.metadata is None:
        response.metadata = {}
    response.metadata["conversation_id"] = active_conversation_id

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


async def _format_sse(event_type: str, data: dict) -> str:
    """Format data as Server-Sent Event.

    :param event_type: SSE event type
    :param data: Data to send
    :returns: Formatted SSE string
    """
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


@router.post("/chat/stream")
async def chat_stream(
    request: ChatRequest,
    http_request: Request,
    conversation_id: Optional[str] = Query(None, description="Existing conversation ID"),
    user_id: Optional[str] = Query(None, description="User ID for new conversations"),
) -> StreamingResponse:
    """Streaming chat endpoint with real-time thinking steps.

    Streams Server-Sent Events (SSE) with:
    - thinking_start: Indicates thinking has begun
    - thinking_step: Individual reasoning steps as they happen
    - thinking_end: Thinking phase complete
    - content: Final response content
    - done: Stream complete with reasoning trace

    :param request: Chat request with messages
    :param http_request: FastAPI request object
    :param conversation_id: Optional existing conversation ID
    :param user_id: User ID for new conversations
    :returns: SSE streaming response
    """
    event_queue: asyncio.Queue[StreamEvent] = asyncio.Queue()

    async def stream_callback(event: StreamEvent) -> None:
        """Callback to receive streaming events."""
        await event_queue.put(event)

    async def generate_events() -> AsyncGenerator[str, None]:
        """Generate SSE events."""
        if _orchestrator is None or _conversation_manager is None:
            yield await _format_sse("error", {"message": "Service not initialized"})
            return

        correlation_id = (
            set_correlation_id(request.correlation_id)
            if request.correlation_id
            else get_correlation_id()
        )

        turn_index = 0
        active_conversation_id = conversation_id
        is_new_conversation = False
        first_user_message = ""
        current_request = request

        if conversation_id:
            existing_messages = _conversation_manager.get_chat_history(conversation_id)
            if existing_messages:
                new_user_content = _extract_last_user_message(request.messages)
                if new_user_content:
                    chat_history, turn_index = _conversation_manager.process_chat_request(
                        conversation_id=conversation_id,
                        user_message=new_user_content,
                    )
                    current_request = ChatRequest(
                        messages=chat_history,
                        correlation_id=correlation_id,
                        workspace_ids=request.workspace_ids or [],
                    )
        else:
            conversation = _conversation_manager.create_conversation(user_id=user_id)
            active_conversation_id = str(conversation.id)
            first_user_message = _extract_last_user_message(request.messages)
            is_new_conversation = True

            if first_user_message:
                chat_history, turn_index = _conversation_manager.process_chat_request(
                    conversation_id=active_conversation_id,
                    user_message=first_user_message,
                )

        set_stream_callback(stream_callback)

        async def run_orchestrator() -> ChatResponse:
            """Run orchestrator in background task."""
            try:
                return await _orchestrator.handle_chat(
                    current_request,
                    context={
                        "conversation_id": active_conversation_id,
                        "workspace_ids": request.workspace_ids or [],
                    },
                )
            finally:
                set_stream_callback(None)
                await event_queue.put(None)

        orchestrator_task = asyncio.create_task(run_orchestrator())

        try:
            while True:
                if await http_request.is_disconnected():
                    orchestrator_task.cancel()
                    break

                try:
                    event = await asyncio.wait_for(event_queue.get(), timeout=0.1)
                except asyncio.TimeoutError:
                    continue

                if event is None:
                    break

                yield await _format_sse(
                    event.type.value,
                    {
                        "timestamp": event.timestamp.isoformat(),
                        **event.data,
                    },
                )

            response = await orchestrator_task

            if active_conversation_id:
                _conversation_manager.process_chat_response(
                    conversation_id=active_conversation_id,
                    response=response,
                    turn_index=turn_index,
                )

            if is_new_conversation and first_user_message and active_conversation_id:
                try:
                    title = await _generate_ai_title(first_user_message)
                    _conversation_manager.update_conversation_title(active_conversation_id, title)
                except Exception as e:
                    logger.warning(f"Failed to generate AI title: {e}")

            content = response.messages[-1].content if response.messages else ""
            yield await _format_sse("content", {"content": content})

            yield await _format_sse(
                "done",
                {
                    "correlation_id": correlation_id,
                    "conversation_id": active_conversation_id,
                },
            )

        except Exception as e:
            logger.error(f"Error in chat stream: {e}", exc_info=e)
            yield await _format_sse("error", {"message": str(e)})

    return StreamingResponse(
        generate_events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
