# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for chat API routes (conversation CRUD only).

Agent execution tests live in the AG-UI / agent layer.
These tests verify conversation persistence endpoints.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.routes.chat import (
    router as chat_router,
    set_conversation_store,
    get_conversation_store,
    _extract_parts,
)
from src.core.models.conversation import Message, MessageRole
from src.core.storage.conversation_store import ConversationStore


@pytest.fixture
def chat_client(tmp_path):
    """Provide a test client with chat routes and a fresh ConversationStore."""
    store = ConversationStore(db_path=tmp_path / "test_conversations.db")
    set_conversation_store(store)

    app = FastAPI()
    app.include_router(chat_router, prefix="/api/v1")

    with TestClient(app) as client:
        yield client

    store.close()


class TestCreateConversation:
    """Tests for POST /api/v1/chat."""

    def test_create_conversation(self, chat_client):
        resp = chat_client.post(
            "/api/v1/chat",
            json={"workspace_id": "TEST-WS"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["workspace_id"] == "TEST-WS"
        assert data["status"] == "active"
        assert data["message_count"] == 0


class TestListConversations:
    """Tests for GET /api/v1/chat."""

    def test_list_empty(self, chat_client):
        resp = chat_client.get("/api/v1/chat?workspace_id=EMPTY")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    def test_list_filters_by_workspace(self, chat_client):
        chat_client.post("/api/v1/chat", json={"workspace_id": "WS-A"})
        chat_client.post("/api/v1/chat", json={"workspace_id": "WS-B"})

        resp = chat_client.get("/api/v1/chat?workspace_id=WS-A")
        data = resp.json()
        assert data["total"] == 1
        assert data["conversations"][0]["workspace_id"] == "WS-A"


class TestGetConversation:
    """Tests for GET /api/v1/chat/{id}."""

    def test_get_conversation(self, chat_client):
        create_resp = chat_client.post("/api/v1/chat", json={"workspace_id": "WS"})
        conv_id = create_resp.json()["id"]

        resp = chat_client.get(f"/api/v1/chat/{conv_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == conv_id
        assert data["messages"] == []

    def test_get_not_found(self, chat_client):
        resp = chat_client.get("/api/v1/chat/nonexistent-id")
        assert resp.status_code == 404


class TestGetMessages:
    """Tests for GET /api/v1/chat/{id}/messages."""

    def test_get_messages_empty(self, chat_client):
        create_resp = chat_client.post("/api/v1/chat", json={"workspace_id": "WS"})
        conv_id = create_resp.json()["id"]

        resp = chat_client.get(f"/api/v1/chat/{conv_id}/messages")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_get_messages_returns_stored(self, chat_client):
        create_resp = chat_client.post("/api/v1/chat", json={"workspace_id": "WS"})
        conv_id = create_resp.json()["id"]

        store = get_conversation_store()
        store.add_message(conv_id, Message(role=MessageRole.USER, content="hello"))
        store.add_message(
            conv_id,
            Message(role=MessageRole.ASSISTANT, content="hi there"),
        )

        resp = chat_client.get(f"/api/v1/chat/{conv_id}/messages")
        assert resp.status_code == 200
        messages = resp.json()
        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "hello"
        assert messages[1]["role"] == "assistant"

    def test_get_messages_not_found(self, chat_client):
        resp = chat_client.get("/api/v1/chat/nonexistent/messages")
        assert resp.status_code == 404


class TestArchiveConversation:
    """Tests for POST /api/v1/chat/{id}/archive."""

    def test_archive_conversation(self, chat_client):
        create_resp = chat_client.post("/api/v1/chat", json={"workspace_id": "WS"})
        conv_id = create_resp.json()["id"]

        resp = chat_client.post(f"/api/v1/chat/{conv_id}/archive")
        assert resp.status_code == 200
        assert resp.json()["status"] == "archived"

        detail = chat_client.get(f"/api/v1/chat/{conv_id}").json()
        assert detail["status"] == "archived"

    def test_archive_not_found(self, chat_client):
        resp = chat_client.post("/api/v1/chat/nonexistent/archive")
        assert resp.status_code == 404

    def test_archive_already_archived(self, chat_client):
        create_resp = chat_client.post("/api/v1/chat", json={"workspace_id": "WS"})
        conv_id = create_resp.json()["id"]
        chat_client.post(f"/api/v1/chat/{conv_id}/archive")

        resp = chat_client.post(f"/api/v1/chat/{conv_id}/archive")
        assert resp.status_code == 400


class TestToolCallsOnReload:
    """Tests that tool calls from af_messages metadata appear on reload."""

    def test_tool_calls_appear_on_reload(self, chat_client):
        """Tool calls from af_messages metadata show on GET /chat/{id}."""
        create_resp = chat_client.post("/api/v1/chat", json={"workspace_id": "WS"})
        conv_id = create_resp.json()["id"]

        store = get_conversation_store()
        store.add_message(
            conv_id,
            Message(role=MessageRole.USER, content="check cluster"),
        )
        store.add_message(
            conv_id,
            Message(
                role=MessageRole.ASSISTANT,
                content="Cluster looks good.",
                metadata={
                    "af_messages": [
                        {
                            "type": "message",
                            "role": "assistant",
                            "contents": [
                                {
                                    "type": "function_call",
                                    "call_id": "c1",
                                    "name": "run_evidence_collector",
                                    "arguments": '{"definition_id":"EC-CLUSTER-MON-0001"}',
                                }
                            ],
                        },
                        {
                            "type": "message",
                            "role": "tool",
                            "contents": [
                                {
                                    "type": "function_result",
                                    "call_id": "c1",
                                    "result": "OK",
                                }
                            ],
                        },
                    ]
                },
            ),
        )

        resp = chat_client.get(f"/api/v1/chat/{conv_id}")
        assert resp.status_code == 200
        msgs = resp.json()["messages"]

        assistant_msgs = [m for m in msgs if m["role"] == "assistant"]
        assert len(assistant_msgs) == 1
        assert "toolCalls" in assistant_msgs[0]
        assert assistant_msgs[0]["toolCalls"][0]["name"] == "run_evidence_collector"
        assert assistant_msgs[0]["toolCalls"][0]["result"] == "OK"
        assert "parts" in assistant_msgs[0]
        parts = assistant_msgs[0]["parts"]
        assert any(p["type"] == "tool_call" for p in parts)


class TestExtractParts:
    """Tests for _extract_parts helper - interleaved text + tool calls."""

    def test_empty_metadata(self):
        assert _extract_parts({}) == []
        assert _extract_parts(None) == []

    def test_text_then_tool_then_text(self):
        metadata = {
            "af_messages": [
                {
                    "type": "message",
                    "role": "assistant",
                    "contents": [
                        {"type": "text", "text": "Let me check."},
                        {
                            "type": "function_call",
                            "call_id": "c1",
                            "name": "list_workspaces",
                            "arguments": "{}",
                        },
                    ],
                },
                {
                    "type": "message",
                    "role": "tool",
                    "contents": [
                        {
                            "type": "function_result",
                            "call_id": "c1",
                            "result": "done",
                        }
                    ],
                },
                {
                    "type": "message",
                    "role": "assistant",
                    "contents": [
                        {"type": "text", "text": "Here are the results."},
                    ],
                },
            ]
        }
        parts = _extract_parts(metadata)
        assert len(parts) == 3
        assert parts[0] == {"type": "text", "content": "Let me check."}
        assert parts[1]["type"] == "tool_call"
        assert parts[1]["toolCall"]["name"] == "list_workspaces"
        assert parts[1]["toolCall"]["result"] == "done"
        assert parts[2] == {"type": "text", "content": "Here are the results."}

    def test_skips_tool_role_messages(self):
        """Tool role messages produce results but not parts themselves."""
        metadata = {
            "af_messages": [
                {
                    "type": "message",
                    "role": "tool",
                    "contents": [
                        {
                            "type": "function_result",
                            "call_id": "c1",
                            "result": "data",
                        }
                    ],
                },
            ]
        }
        parts = _extract_parts(metadata)
        assert parts == []
