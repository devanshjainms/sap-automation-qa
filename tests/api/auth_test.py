# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for Azure AD authentication module."""

from __future__ import annotations

import time
from typing import Any

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from pytest_mock import MockerFixture
from src.api.auth import (
    AuthMiddleware,
    AuthenticatedUser,
    AuthenticationError,
    AzureADAuthProvider,
    create_auth_provider,
    get_public_paths,
)

_TEST_PRIVATE_KEY = rsa.generate_private_key(
    public_exponent=65537,
    key_size=2048,
)
_TEST_PUBLIC_KEY = _TEST_PRIVATE_KEY.public_key()

_TEST_TENANT_ID = "00000000-0000-0000-0000-000000000001"
_TEST_CLIENT_ID = "00000000-0000-0000-0000-000000000002"
_TEST_ISSUER = f"https://login.microsoftonline.com/{_TEST_TENANT_ID}/v2.0"


def _make_token(
    claims: dict[str, Any] | None = None,
    expired: bool = False,
    wrong_audience: bool = False,
    wrong_tenant: bool = False,
) -> str:
    """Create a signed JWT for testing.

    :param claims: Override claims.
    :param expired: If True, set ``exp`` in the past.
    :param wrong_audience: If True, use a different audience.
    :param wrong_tenant: If True, use a different tenant ID.
    :returns: Encoded JWT string.
    """
    now = int(time.time())
    payload: dict[str, Any] = {
        "iss": _TEST_ISSUER,
        "aud": "wrong-client" if wrong_audience else _TEST_CLIENT_ID,
        "exp": now - 3600 if expired else now + 3600,
        "nbf": now - 60,
        "iat": now,
        "oid": "user-oid-123",
        "tid": "bad-tenant" if wrong_tenant else _TEST_TENANT_ID,
        "name": "Test User",
        "preferred_username": "test@contoso.com",
        "roles": ["Admin"],
    }
    if claims:
        payload.update(claims)

    private_pem = _TEST_PRIVATE_KEY.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return pyjwt.encode(payload, private_pem, algorithm="RS256")


def _mock_jwks_client(mocker: MockerFixture) -> Any:
    """Create a mock PyJWKClient that returns our test public key.

    :param mocker: pytest-mock fixture.
    :returns: Mocked PyJWKClient instance.
    """
    mock_signing_key = mocker.MagicMock()
    mock_signing_key.key = _TEST_PUBLIC_KEY

    mock_client = mocker.MagicMock()
    mock_client.get_signing_key_from_jwt.return_value = mock_signing_key
    return mock_client


def _create_provider(
    dev_mode: bool = False,
    jwks_mock: Any | None = None,
) -> AzureADAuthProvider:
    """Create a provider with optional mocked JWKS client.

    :param dev_mode: Enable dev mode (skip verification).
    :param jwks_mock: Mock PyJWKClient to inject.
    :returns: Configured provider.
    """
    provider = AzureADAuthProvider(
        tenant_id=_TEST_TENANT_ID,
        client_id=_TEST_CLIENT_ID,
        dev_mode=dev_mode,
    )
    if jwks_mock is not None:
        provider._jwks_client = jwks_mock
    return provider


def _create_test_app(provider: AzureADAuthProvider) -> FastAPI:
    """Build a minimal FastAPI app with auth middleware for testing.

    :param provider: Auth provider to use.
    :returns: FastAPI application with auth middleware and test routes.
    """
    app = FastAPI()

    @app.get("/healthz")
    async def healthz() -> dict:
        return {"status": "ok"}

    @app.get("/auth/config")
    async def auth_config() -> dict:
        return {"client_id": _TEST_CLIENT_ID}

    @app.get("/")
    async def root() -> dict:
        return {"page": "home"}

    @app.get("/api/v1/protected")
    async def protected(request: Request) -> dict:
        user = getattr(request.state, "user", None)
        if user:
            return {"user": user.name, "oid": user.oid}
        return {"user": "anonymous"}

    app.add_middleware(
        AuthMiddleware,
        auth_provider=provider,
        public_paths=get_public_paths(),
    )
    return app


# ─── AzureADAuthProvider unit tests ───────────────────────────────


class TestAzureADAuthProvider:
    """Unit tests for token validation logic."""

    def test_valid_token(self, mocker: MockerFixture) -> None:
        """A correctly signed token with valid claims succeeds."""
        jwks_mock = mocker.MagicMock()
        signing_key = mocker.MagicMock()
        signing_key.key = _TEST_PUBLIC_KEY
        jwks_mock.get_signing_key_from_jwt.return_value = signing_key

        provider = _create_provider(jwks_mock=jwks_mock)
        token = _make_token()
        user = provider.validate_token(token)

        assert isinstance(user, AuthenticatedUser)
        assert user.oid == "user-oid-123"
        assert user.name == "Test User"
        assert user.email == "test@contoso.com"
        assert user.tenant_id == _TEST_TENANT_ID
        assert "Admin" in user.roles

    def test_expired_token(self, mocker: MockerFixture) -> None:
        """An expired token raises AuthenticationError."""
        provider = _create_provider(jwks_mock=_mock_jwks_client(mocker))
        token = _make_token(expired=True)

        with pytest.raises(AuthenticationError, match="expired"):
            provider.validate_token(token)

    def test_wrong_audience(self, mocker: MockerFixture) -> None:
        """A token with wrong audience raises AuthenticationError."""
        provider = _create_provider(jwks_mock=_mock_jwks_client(mocker))
        token = _make_token(wrong_audience=True)

        with pytest.raises(AuthenticationError, match="audience"):
            provider.validate_token(token)

    def test_wrong_tenant(self, mocker: MockerFixture) -> None:
        """A token from a different tenant raises AuthenticationError."""
        provider = _create_provider(jwks_mock=_mock_jwks_client(mocker))
        token = _make_token(wrong_tenant=True)

        with pytest.raises(AuthenticationError, match="tenant"):
            provider.validate_token(token)

    def test_malformed_token(self, mocker: MockerFixture) -> None:
        """A completely invalid token string raises AuthenticationError."""
        provider = _create_provider(jwks_mock=_mock_jwks_client(mocker))

        with pytest.raises(AuthenticationError):
            provider.validate_token("not-a-jwt")

    def test_missing_oid_claim(self, mocker: MockerFixture) -> None:
        """A token without required 'oid' claim raises AuthenticationError."""
        provider = _create_provider(jwks_mock=_mock_jwks_client(mocker))
        token = _make_token(claims={"oid": None})

        with pytest.raises(AuthenticationError):
            provider.validate_token(token)

    def test_jwks_connection_error(self, mocker: MockerFixture) -> None:
        """JWKS endpoint failure returns 503."""
        jwks_mock = mocker.MagicMock()
        jwks_mock.get_signing_key_from_jwt.side_effect = pyjwt.PyJWKClientConnectionError(
            "unreachable"
        )
        provider = _create_provider(jwks_mock=jwks_mock)
        token = _make_token()

        with pytest.raises(AuthenticationError) as exc_info:
            provider.validate_token(token)
        assert exc_info.value.status_code == 503

    def test_dev_mode_accepts_any_token(self) -> None:
        """Dev mode accepts tokens without signature verification."""
        provider = _create_provider(dev_mode=True)
        token = _make_token()
        user = provider.validate_token(token)

        assert user.oid == "user-oid-123"
        assert user.name == "Test User"

    def test_dev_mode_rejects_garbage(self) -> None:
        """Dev mode still rejects completely malformed tokens."""
        provider = _create_provider(dev_mode=True)

        with pytest.raises(AuthenticationError, match="Malformed"):
            provider.validate_token("not-a-jwt-at-all")

    def test_authenticated_user_is_frozen(self) -> None:
        """AuthenticatedUser is immutable."""
        user = AuthenticatedUser(
            oid="x",
            name="n",
            email="e",
            tenant_id="t",
            roles=(),
            raw_claims={},
        )
        with pytest.raises(AttributeError):
            user.name = "changed"  # type: ignore[misc]


# ─── AuthMiddleware integration tests ─────────────────────────────


class TestAuthMiddleware:
    """Integration tests for the ASGI auth middleware."""

    def _get_client(self, dev_mode: bool = False, jwks_mock: Any | None = None) -> TestClient:
        """Build a TestClient with configured auth.

        :param dev_mode: Enable dev mode.
        :param jwks_mock: Mock JWKS client.
        :returns: TestClient for the test app.
        """
        provider = _create_provider(dev_mode=dev_mode, jwks_mock=jwks_mock)
        app = _create_test_app(provider)
        return TestClient(app)

    def test_healthz_no_auth_required(self) -> None:
        """/healthz is accessible without any token."""
        client = self._get_client(dev_mode=True)
        response = client.get("/healthz")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_auth_config_no_auth_required(self) -> None:
        """/auth/config is accessible without any token."""
        client = self._get_client(dev_mode=True)
        response = client.get("/auth/config")
        assert response.status_code == 200
        assert "client_id" in response.json()

    def test_protected_endpoint_missing_token(self) -> None:
        """Protected endpoint returns 401 when no token is provided."""
        client = self._get_client(dev_mode=True)
        response = client.get("/api/v1/protected")
        assert response.status_code == 401
        assert "WWW-Authenticate" in response.headers
        assert response.headers["WWW-Authenticate"] == "Bearer"

    def test_protected_endpoint_valid_token(self, mocker: MockerFixture) -> None:
        """Protected endpoint returns 200 with a valid token."""
        jwks_mock = _mock_jwks_client(mocker)
        client = self._get_client(jwks_mock=jwks_mock)
        token = _make_token()

        response = client.get(
            "/api/v1/protected",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["user"] == "Test User"
        assert data["oid"] == "user-oid-123"

    def test_protected_endpoint_expired_token(self, mocker: MockerFixture) -> None:
        """Protected endpoint returns 401 with an expired token."""
        jwks_mock = _mock_jwks_client(mocker)
        client = self._get_client(jwks_mock=jwks_mock)
        token = _make_token(expired=True)

        response = client.get(
            "/api/v1/protected",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 401
        assert "expired" in response.json()["detail"]

    def test_protected_endpoint_wrong_audience(self, mocker: MockerFixture) -> None:
        """Protected endpoint returns 401 with wrong audience."""
        jwks_mock = _mock_jwks_client(mocker)
        client = self._get_client(jwks_mock=jwks_mock)
        token = _make_token(wrong_audience=True)

        response = client.get(
            "/api/v1/protected",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 401
        assert "audience" in response.json()["detail"]

    def test_protected_endpoint_jwks_unavailable(self, mocker: MockerFixture) -> None:
        """Returns 503 when JWKS endpoint is unreachable."""
        jwks_mock = mocker.MagicMock()
        jwks_mock.get_signing_key_from_jwt.side_effect = pyjwt.PyJWKClientConnectionError("down")
        client = self._get_client(jwks_mock=jwks_mock)
        token = _make_token()

        response = client.get(
            "/api/v1/protected",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 503

    def test_docs_endpoint_no_auth(self) -> None:
        """/docs is accessible without authentication."""
        client = self._get_client(dev_mode=True)
        response = client.get("/docs")
        assert response.status_code == 200

    def test_root_endpoint_no_auth(self) -> None:
        """/ is accessible without authentication."""
        client = self._get_client(dev_mode=True)
        response = client.get("/")
        # FastAPI returns 404 for undefined root if no route, but our
        # public path check should let it through without 401
        assert response.status_code != 401


# ─── Factory function tests ───────────────────────────────────────


class TestCreateAuthProvider:
    """Tests for the create_auth_provider factory."""

    def test_missing_env_vars_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Raises ValueError when required env vars are missing."""
        monkeypatch.setattr("os.environ", {"AUTH_DEV_MODE": "false"})
        with pytest.raises(ValueError, match="AZURE_TENANT_ID"):
            create_auth_provider()

    def test_dev_mode_in_production_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Raises ValueError when dev mode is enabled in production."""
        monkeypatch.setattr("os.environ", {"AUTH_DEV_MODE": "true", "LOG_FORMAT": "json"})
        with pytest.raises(ValueError, match="production safety"):
            create_auth_provider()

    def test_dev_mode_allowed_in_console(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Dev mode is allowed when LOG_FORMAT is console."""
        monkeypatch.setattr(
            "os.environ",
            {"AUTH_DEV_MODE": "true", "LOG_FORMAT": "console"},
        )
        provider = create_auth_provider()
        assert provider._dev_mode is True

    def test_production_mode_with_valid_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Production provider created with valid env vars."""
        monkeypatch.setattr(
            "os.environ",
            {
                "AZURE_TENANT_ID": _TEST_TENANT_ID,
                "AZURE_CLIENT_ID": _TEST_CLIENT_ID,
            },
        )
        provider = create_auth_provider()
        assert provider._dev_mode is False
        assert provider._jwks_client is not None


# ─── Public paths tests ───────────────────────────────────────────


class TestPublicPaths:
    """Tests for get_public_paths."""

    def test_healthz_is_public(self) -> None:
        """Healthz endpoint is always public."""
        assert "/healthz" in get_public_paths()

    def test_auth_config_is_public(self) -> None:
        """Auth config endpoint is always public."""
        assert "/auth/config" in get_public_paths()

    def test_docs_is_public(self) -> None:
        """Swagger docs are public."""
        assert "/docs" in get_public_paths()
