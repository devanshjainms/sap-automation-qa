# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for the SAP token verifier."""

from __future__ import annotations
import hashlib
import os
import pytest
from src.mcp_server.auth import SapTokenVerifier, create_token_verifier


class TestSapTokenVerifier:
    """Tests for SapTokenVerifier modes."""

    def test_api_key_requires_key(self):
        with pytest.raises(ValueError, match="MCP_API_KEY required"):
            SapTokenVerifier(auth_mode="api_key")

    def test_bearer_requires_token(self):
        with pytest.raises(ValueError, match="MCP_BEARER_TOKEN required"):
            SapTokenVerifier(auth_mode="bearer")

    @pytest.mark.asyncio
    async def test_api_key_valid(self):
        v = SapTokenVerifier(auth_mode="api_key", api_key="secret-key")
        result = await v.verify_token("secret-key")
        assert result is not None
        assert result.scopes == ["mcp:tools"]
        expected_id = f"apikey-{hashlib.sha256(b'secret-key').hexdigest()[:12]}"
        assert result.client_id == expected_id

    @pytest.mark.asyncio
    async def test_api_key_invalid(self):
        v = SapTokenVerifier(auth_mode="api_key", api_key="secret-key")
        result = await v.verify_token("wrong-key")
        assert result is None

    @pytest.mark.asyncio
    async def test_api_key_empty(self):
        v = SapTokenVerifier(auth_mode="api_key", api_key="secret-key")
        result = await v.verify_token("")
        assert result is None

    @pytest.mark.asyncio
    async def test_bearer_valid(self):
        v = SapTokenVerifier(auth_mode="bearer", bearer_token="my-token")
        result = await v.verify_token("my-token")
        assert result is not None
        assert result.scopes == ["mcp:tools"]

    @pytest.mark.asyncio
    async def test_bearer_invalid(self):
        v = SapTokenVerifier(auth_mode="bearer", bearer_token="my-token")
        result = await v.verify_token("bad-token")
        assert result is None

    @pytest.mark.asyncio
    async def test_none_mode_returns_none(self):
        v = SapTokenVerifier(auth_mode="none")
        result = await v.verify_token("anything")
        assert result is None


class TestCreateTokenVerifier:
    """Tests for the factory function."""

    def test_none_mode_returns_none(self, monkeypatch):
        monkeypatch.setenv("MCP_AUTH_MODE", "none")
        assert create_token_verifier() is None

    def test_default_is_none(self, monkeypatch):
        monkeypatch.delenv("MCP_AUTH_MODE", raising=False)
        assert create_token_verifier() is None

    def test_api_key_mode(self, monkeypatch):
        monkeypatch.setenv("MCP_AUTH_MODE", "api_key")
        monkeypatch.setenv("MCP_API_KEY", "test-key")
        v = create_token_verifier()
        assert v is not None

    def test_bearer_mode(self, monkeypatch):
        monkeypatch.setenv("MCP_AUTH_MODE", "bearer")
        monkeypatch.setenv("MCP_BEARER_TOKEN", "test-token")
        v = create_token_verifier()
        assert v is not None
