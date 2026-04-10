# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for the SAP token verifier (SDK TokenVerifier protocol)."""

from __future__ import annotations

import hashlib

import pytest

from src.mcp_server.auth import SapTokenVerifier, create_token_verifier

# ---------------------------------------------------------------------------
# Constructor validation
# ---------------------------------------------------------------------------


class TestConstructorValidation:

    def test_api_key_mode_requires_key(self):
        with pytest.raises(ValueError, match="MCP_API_KEY required"):
            SapTokenVerifier(auth_mode="api_key", api_key="")

    def test_bearer_mode_requires_token(self):
        with pytest.raises(ValueError, match="MCP_BEARER_TOKEN required"):
            SapTokenVerifier(auth_mode="bearer", bearer_token="")

    def test_none_mode_accepts_empty(self):
        v = SapTokenVerifier(auth_mode="none")
        assert v is not None

    def test_mi_mode_accepts_empty(self):
        v = SapTokenVerifier(auth_mode="mi")
        assert v is not None


# ---------------------------------------------------------------------------
# api_key mode
# ---------------------------------------------------------------------------


class TestApiKeyMode:

    @pytest.mark.asyncio
    async def test_valid_key_returns_access_token(self):
        v = SapTokenVerifier(auth_mode="api_key", api_key="secret123")
        result = await v.verify_token("secret123")

        assert result is not None
        expected_id = hashlib.sha256(b"secret123").hexdigest()[:12]
        assert result.client_id == f"apikey-{expected_id}"
        assert "mcp:tools" in result.scopes

    @pytest.mark.asyncio
    async def test_invalid_key_returns_none(self):
        v = SapTokenVerifier(auth_mode="api_key", api_key="secret123")
        assert await v.verify_token("wrong") is None

    @pytest.mark.asyncio
    async def test_empty_token_returns_none(self):
        v = SapTokenVerifier(auth_mode="api_key", api_key="secret123")
        assert await v.verify_token("") is None


# ---------------------------------------------------------------------------
# bearer mode
# ---------------------------------------------------------------------------


class TestBearerMode:

    @pytest.mark.asyncio
    async def test_valid_token_returns_access_token(self):
        v = SapTokenVerifier(auth_mode="bearer", bearer_token="tok-abc")
        result = await v.verify_token("tok-abc")

        assert result is not None
        expected_id = hashlib.sha256(b"tok-abc").hexdigest()[:12]
        assert result.client_id == f"bearer-{expected_id}"
        assert "mcp:tools" in result.scopes

    @pytest.mark.asyncio
    async def test_invalid_token_returns_none(self):
        v = SapTokenVerifier(auth_mode="bearer", bearer_token="tok-abc")
        assert await v.verify_token("wrong") is None

    @pytest.mark.asyncio
    async def test_empty_token_returns_none(self):
        v = SapTokenVerifier(auth_mode="bearer", bearer_token="tok-abc")
        assert await v.verify_token("") is None


# ---------------------------------------------------------------------------
# mi mode
# ---------------------------------------------------------------------------


class TestManagedIdentityMode:

    @pytest.mark.asyncio
    async def test_any_token_accepted(self):
        v = SapTokenVerifier(auth_mode="mi")
        result = await v.verify_token("any-jwt-value")

        assert result is not None
        expected_id = hashlib.sha256(b"any-jwt-value").hexdigest()[:12]
        assert result.client_id == f"mi-{expected_id}"

    @pytest.mark.asyncio
    async def test_empty_token_returns_none(self):
        v = SapTokenVerifier(auth_mode="mi")
        assert await v.verify_token("") is None


# ---------------------------------------------------------------------------
# none / unknown mode
# ---------------------------------------------------------------------------


class TestNoneMode:

    @pytest.mark.asyncio
    async def test_returns_none_for_any_token(self):
        v = SapTokenVerifier(auth_mode="none")
        assert await v.verify_token("anything") is None


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


class TestCreateTokenVerifier:

    def test_returns_none_when_disabled(self, monkeypatch):
        monkeypatch.setenv("MCP_AUTH_MODE", "none")
        assert create_token_verifier() is None

    def test_returns_none_by_default(self, monkeypatch):
        monkeypatch.delenv("MCP_AUTH_MODE", raising=False)
        assert create_token_verifier() is None

    def test_returns_verifier_for_api_key(self, monkeypatch):
        monkeypatch.setenv("MCP_AUTH_MODE", "api_key")
        monkeypatch.setenv("MCP_API_KEY", "k")
        v = create_token_verifier()
        assert isinstance(v, SapTokenVerifier)

    def test_returns_verifier_for_bearer(self, monkeypatch):
        monkeypatch.setenv("MCP_AUTH_MODE", "bearer")
        monkeypatch.setenv("MCP_BEARER_TOKEN", "t")
        v = create_token_verifier()
        assert isinstance(v, SapTokenVerifier)
