# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for chat API routes (conversation CRUD + message sending)."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.core.services.chat import ChatService
from src.api.routes.chat import (
    router as chat_router,
    set_chat_service,
    set_conversation_store,
)
from src.core.models.conversation import Message, MessageRole
from src.core.storage.conversation_store import ConversationStore


@pytest.fixture
def chat_client(tmp_path):
    """Provide a test client with chat routes and a fresh ConversationStore."""
    store = ConversationStore(db_path=tmp_path / "test_conversations.db")
    set_conversation_store(store)
    set_chat_service(None)

    app = FastAPI()
    app.include_router(chat_router, prefix="/api/v1")

    with TestClient(app) as client:
        yield client

    store.close()


@pytest.fixture
def agent_chat_client(tmp_path):
    """Provide a test client with a mocked ChatService wired in."""
    store = ConversationStore(db_path=tmp_path / "test_conversations.db")
    set_conversation_store(store)

    mock_service = MagicMock(spec=ChatService)
    mock_service.send_message = AsyncMock(
        return_value=Message(role=MessageRole.ASSISTANT, content="Agent says hello"),
    )
    set_chat_service(mock_service)

    app = FastAPI()
    app.include_router(chat_router, prefix="/api/v1")

    with TestClient(app) as client:
        yield client, mock_service

    set_chat_service(None)
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


class TestSendMessage:
    """Tests for POST /api/v1/chat/{id}/messages."""

    def test_send_fallback_when_no_service(self, chat_client):
        create_resp = chat_client.post("/api/v1/chat", json={"workspace_id": "WS"})
        conv_id = create_resp.json()["id"]

        resp = chat_client.post(
            f"/api/v1/chat/{conv_id}/messages",
            json={"message": "Why is HANA down?"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["role"] == "assistant"
        assert "not configured" in data["content"]

    def test_send_with_agent_service(self, agent_chat_client):
        client, mock_service = agent_chat_client
        create_resp = client.post("/api/v1/chat", json={"workspace_id": "WS"})
        conv_id = create_resp.json()["id"]

        resp = client.post(
            f"/api/v1/chat/{conv_id}/messages",
            json={"message": "Check HANA"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["role"] == "assistant"
        assert data["content"] == "Agent says hello"
        mock_service.send_message.assert_awaited_once_with(conv_id, "Check HANA")

    def test_send_updates_title(self, chat_client):
        create_resp = chat_client.post("/api/v1/chat", json={"workspace_id": "WS"})
        conv_id = create_resp.json()["id"]

        chat_client.post(
            f"/api/v1/chat/{conv_id}/messages",
            json={"message": "First question about HANA"},
        )

        detail = chat_client.get(f"/api/v1/chat/{conv_id}").json()
        assert "First question" in detail["title"]

    def test_send_to_nonexistent_conversation(self, chat_client):
        resp = chat_client.post(
            "/api/v1/chat/nonexistent/messages",
            json={"message": "hello"},
        )
        assert resp.status_code == 404

    def test_send_empty_message_rejected(self, chat_client):
        create_resp = chat_client.post("/api/v1/chat", json={"workspace_id": "WS"})
        conv_id = create_resp.json()["id"]

        resp = chat_client.post(
            f"/api/v1/chat/{conv_id}/messages",
            json={"message": ""},
        )
        assert resp.status_code == 422


class TestGetMessages:
    """Tests for GET /api/v1/chat/{id}/messages."""

    def test_get_messages_ordered(self, chat_client):
        create_resp = chat_client.post("/api/v1/chat", json={"workspace_id": "WS"})
        conv_id = create_resp.json()["id"]

        chat_client.post(
            f"/api/v1/chat/{conv_id}/messages",
            json={"message": "First"},
        )
        chat_client.post(
            f"/api/v1/chat/{conv_id}/messages",
            json={"message": "Second"},
        )

        resp = chat_client.get(f"/api/v1/chat/{conv_id}/messages")
        assert resp.status_code == 200
        messages = resp.json()
        # 2 user + 2 assistant = 4 messages
        assert len(messages) == 4
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "First"


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

    def test_send_to_archived_fails(self, chat_client):
        create_resp = chat_client.post("/api/v1/chat", json={"workspace_id": "WS"})
        conv_id = create_resp.json()["id"]
        chat_client.post(f"/api/v1/chat/{conv_id}/archive")

        resp = chat_client.post(
            f"/api/v1/chat/{conv_id}/messages",
            json={"message": "should fail"},
        )
        assert resp.status_code == 400


class TestStreamMessage:
    """Tests for POST /api/v1/chat/{id}/messages/stream."""

    def test_stream_returns_503_without_service(self, chat_client):
        create_resp = chat_client.post("/api/v1/chat", json={"workspace_id": "WS"})
        conv_id = create_resp.json()["id"]

        resp = chat_client.post(
            f"/api/v1/chat/{conv_id}/messages/stream",
            json={"message": "hello"},
        )
        assert resp.status_code == 503

    def test_stream_not_found(self, chat_client):
        resp = chat_client.post(
            "/api/v1/chat/nonexistent/messages/stream",
            json={"message": "hello"},
        )
        assert resp.status_code == 404

    def test_stream_archived_fails(self, chat_client):
        create_resp = chat_client.post("/api/v1/chat", json={"workspace_id": "WS"})
        conv_id = create_resp.json()["id"]
        chat_client.post(f"/api/v1/chat/{conv_id}/archive")

        resp = chat_client.post(
            f"/api/v1/chat/{conv_id}/messages/stream",
            json={"message": "should fail"},
        )
        assert resp.status_code == 400
