# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for the SAP token verifier (SDK TokenVerifier protocol)."""

from __future__ import annotations
import hashlib
import time
from pytest_mock import MockerFixture
import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from src.api.auth import AzureADAuthProvider
from src.mcp_server.auth import SapTokenVerifier, create_token_verifier

_TEST_PRIVATE_KEY = rsa.generate_private_key(
    public_exponent=65537,
    key_size=2048,
)
_TEST_PUBLIC_KEY = _TEST_PRIVATE_KEY.public_key()
_TEST_TENANT = "00000000-0000-0000-0000-000000000001"
_TEST_CLIENT = "00000000-0000-0000-0000-000000000002"
_TEST_ISSUER = f"https://login.microsoftonline.com/{_TEST_TENANT}/v2.0"


def _make_jwt(expired: bool = False) -> str:
    """Create a signed JWT for Azure AD mode tests."""
    now = int(time.time())
    payload = {
        "iss": _TEST_ISSUER,
        "aud": _TEST_CLIENT,
        "exp": now - 3600 if expired else now + 3600,
        "nbf": now - 60,
        "iat": now,
        "oid": "user-oid-456",
        "tid": _TEST_TENANT,
        "name": "MCP User",
        "preferred_username": "mcp@contoso.com",
        "roles": ["Operator"],
    }
    private_pem = _TEST_PRIVATE_KEY.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return pyjwt.encode(payload, private_pem, algorithm="RS256")


def _mock_azure_ad_provider(mocker: MockerFixture) -> AzureADAuthProvider:
    """Create an AzureADAuthProvider with a mocked JWKS client."""
    provider = AzureADAuthProvider(
        tenant_id=_TEST_TENANT,
        client_id=_TEST_CLIENT,
    )
    mock_signing_key = mocker.MagicMock()
    mock_signing_key.key = _TEST_PUBLIC_KEY
    mock_client = mocker.MagicMock()
    mock_client.get_signing_key_from_jwt.return_value = mock_signing_key
    provider._jwks_client = mock_client
    return provider


class TestConstructorValidation:

    def test_api_key_mode_requires_key(self):
        with pytest.raises(ValueError, match="MCP_API_KEY required"):
            SapTokenVerifier(auth_mode="api_key", api_key="")

    def test_bearer_mode_requires_token(self):
        with pytest.raises(ValueError, match="MCP_BEARER_TOKEN required"):
            SapTokenVerifier(auth_mode="bearer", bearer_token="")

    def test_azure_ad_mode_requires_provider(self):
        with pytest.raises(ValueError, match="AzureADAuthProvider required"):
            SapTokenVerifier(auth_mode="azure_ad")

    def test_none_mode_accepts_empty(self):
        v = SapTokenVerifier(auth_mode="none")
        assert v is not None


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


class TestAzureAdMode:

    @pytest.mark.asyncio
    async def test_valid_jwt_returns_access_token(self, mocker: MockerFixture):
        provider = _mock_azure_ad_provider(mocker)
        v = SapTokenVerifier(auth_mode="azure_ad", azure_ad_provider=provider)
        token = _make_jwt()
        result = await v.verify_token(token)

        assert result is not None
        assert result.client_id == "aad-user-oid-456"
        assert "mcp:tools" in result.scopes

    @pytest.mark.asyncio
    async def test_expired_jwt_returns_none(self, mocker: MockerFixture):
        provider = _mock_azure_ad_provider(mocker)
        v = SapTokenVerifier(auth_mode="azure_ad", azure_ad_provider=provider)
        token = _make_jwt(expired=True)
        result = await v.verify_token(token)
        assert result is None

    @pytest.mark.asyncio
    async def test_empty_token_returns_none(self, mocker: MockerFixture):
        provider = _mock_azure_ad_provider(mocker)
        v = SapTokenVerifier(auth_mode="azure_ad", azure_ad_provider=provider)
        result = await v.verify_token("")
        assert result is None

    @pytest.mark.asyncio
    async def test_malformed_token_returns_none(self, mocker: MockerFixture):
        provider = _mock_azure_ad_provider(mocker)
        v = SapTokenVerifier(auth_mode="azure_ad", azure_ad_provider=provider)
        result = await v.verify_token("not-a-jwt")
        assert result is None


class TestNoneMode:

    @pytest.mark.asyncio
    async def test_returns_none_for_any_token(self):
        v = SapTokenVerifier(auth_mode="none")
        assert await v.verify_token("anything") is None


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

    def test_returns_verifier_for_azure_ad(self, monkeypatch):
        monkeypatch.setenv("MCP_AUTH_MODE", "azure_ad")
        monkeypatch.setenv("AZURE_TENANT_ID", _TEST_TENANT)
        monkeypatch.setenv("AZURE_CLIENT_ID", _TEST_CLIENT)
        v = create_token_verifier()
        assert isinstance(v, SapTokenVerifier)

    def test_azure_ad_missing_env_raises(self, monkeypatch):
        monkeypatch.setenv("MCP_AUTH_MODE", "azure_ad")
        monkeypatch.delenv("AZURE_TENANT_ID", raising=False)
        monkeypatch.delenv("AZURE_CLIENT_ID", raising=False)
        monkeypatch.delenv("AUTH_DEV_MODE", raising=False)
        with pytest.raises(ValueError, match="AZURE_TENANT_ID"):
            create_token_verifier()
