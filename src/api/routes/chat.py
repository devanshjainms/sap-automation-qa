# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Chat API routes — conversation CRUD only.

Agent execution happens exclusively through the AG-UI endpoint
(``/ag-ui``).  These routes provide the persistence layer:
create, list, get, and archive conversations.
"""

import json
import logging
from typing import Any, Optional
from fastapi import APIRouter, HTTPException, Query
from src.core.models.conversation import (
    Conversation,
    CreateConversationRequest,
    MessageRole,
)
from src.core.storage.conversation_store import ConversationStore
from src.mcp_server.server import mcp

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chat", tags=["chat"])

_conversation_store: Optional[ConversationStore] = None


def set_conversation_store(store: ConversationStore) -> None:
    """Inject the conversation store (called from lifespan).

    :param store: ConversationStore instance.
    """
    global _conversation_store
    _conversation_store = store


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


def _summarize(conv: Conversation) -> dict[str, Any]:
    """Serialize a Conversation to a JSON-safe summary dict."""
    data = conv.model_dump(mode="json", exclude={"messages", "metadata"})
    data["message_count"] = conv.message_count
    return data


def _detail(conv: Conversation) -> dict[str, Any]:
    """Serialize a Conversation with full message history.

    Extracts interleaved ``parts`` (text + tool calls in order) from
    ``metadata.af_messages`` so the frontend can render them one after
    the other — similar to GitHub Copilot's sequential tool display.
    """
    data = conv.model_dump(mode="json", exclude={"metadata"})
    for msg in data.get("messages", []):
        msg.pop("metadata", None)
    for conv_msg, api_msg in zip(conv.messages, data.get("messages", [])):
        if conv_msg.role != MessageRole.ASSISTANT:
            continue
        parts = _extract_parts(conv_msg.metadata)
        if parts:
            api_msg["parts"] = parts
            api_msg["toolCalls"] = [p["toolCall"] for p in parts if p["type"] == "tool_call"]
    data["tools"] = _get_tool_metadata()
    return data


def _get_tool_metadata() -> list[dict[str, Any]]:
    """Read MCP tool metadata — single source of truth from decorators.

    Includes the full JSON Schema ``parameters`` so the frontend can
    render parameter names, types, and required indicators without
    duplicating any tool knowledge.

    :returns: List of tool metadata dicts sorted by name,
        or empty list if the MCP server is not loaded.
    """
    try:
        tools = mcp._tool_manager.list_tools()
        result = []
        for t in sorted(tools, key=lambda x: x.name):
            annotations = None
            if t.annotations:
                annotations = {
                    "readOnlyHint": t.annotations.readOnlyHint,
                    "destructiveHint": t.annotations.destructiveHint,
                    "idempotentHint": t.annotations.idempotentHint,
                    "openWorldHint": t.annotations.openWorldHint,
                }
            icons = []
            if t.icons:
                icons = [{"src": icon.src} for icon in t.icons]
            result.append(
                {
                    "name": t.name,
                    "title": t.title or t.name,
                    "description": t.description or "",
                    "parameters": t.parameters or {},
                    "annotations": annotations,
                    "icons": icons,
                }
            )
        return result
    except Exception:
        logger.debug("Could not load MCP tool metadata", exc_info=True)
        return []


def _extract_parts(metadata: dict) -> list[dict[str, Any]]:
    """Build an interleaved list of text and tool-call parts from af_messages.

    :param metadata: Message metadata dict.
    :returns: Ordered list of parts the frontend renders sequentially.
    """
    if not metadata:
        return []
    af_msgs = metadata.get("af_messages", [])
    if not af_msgs:
        return []

    results_by_id: dict[str, str] = {}
    for m in af_msgs:
        for c in m.get("contents", []):
            if c.get("type") == "function_result" and c.get("call_id"):
                result = c.get("result", "")
                if isinstance(result, dict):
                    result = json.dumps(result, indent=2)
                results_by_id[c["call_id"]] = str(result)[:2000]

    parts: list[dict[str, Any]] = []
    for m in af_msgs:
        if m.get("role") != "assistant":
            continue
        for c in m.get("contents", []):
            ctype = c.get("type")
            if ctype == "text":
                text = c.get("text", "").strip()
                if text:
                    parts.append({"type": "text", "content": text})
            elif ctype == "function_call":
                call_id = c.get("call_id", "")
                parts.append(
                    {
                        "type": "tool_call",
                        "toolCall": {
                            "name": c.get("name", ""),
                            "args": c.get("arguments", ""),
                            "result": results_by_id.get(call_id, ""),
                        },
                    }
                )
    return parts


@router.get("/tools")
async def get_tools() -> list[dict[str, Any]]:
    """Return MCP tool metadata — single source of truth for the UI.

    :returns: Sorted list of ``{name, title, description, annotations, icons}``.
    """
    return _get_tool_metadata()


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
    workspace_id: str = Query(None, description="Filter by workspace"),
    include_archived: bool = Query(False, description="Include archived"),
    limit: int = Query(50, ge=1, le=200, description="Max results"),
) -> dict[str, Any]:
    """List conversations for a workspace.

    :param workspace_id: Workspace to list conversations for.
    :param include_archived: Whether to include archived conversations.
    :param limit: Maximum results.
    :returns: Paginated response with total count and conversations.
    """
    if workspace_id is None:
        conversations = get_conversation_store().list_all(
            include_archived=include_archived,
            limit=limit,
        )
    else:
        conversations = get_conversation_store().list_conversations(
            workspace_id=workspace_id,
            include_archived=include_archived,
            limit=limit,
        )
    items = [_summarize(c) for c in conversations]
    return {"total": len(items), "conversations": items}


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
