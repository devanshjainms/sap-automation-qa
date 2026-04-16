# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Azure AD (Entra ID) JWT authentication for the FastAPI application.

Validates bearer tokens issued by Azure AD using JWKS (JSON Web Key Set)
public key verification.
"""

from __future__ import annotations
import os
from typing import Any, Optional
import jwt
from fastapi import Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.responses import JSONResponse
from src.core.models.auth import AuthenticatedUser
from src.core.observability import get_logger

logger = get_logger(__name__)

_OPENID_CONFIG_URL = "https://login.microsoftonline.com/{tenant}/discovery/v2.0/keys"
_ISSUER_V2 = "https://login.microsoftonline.com/{tenant}/v2.0"
_ALGORITHMS = ["RS256"]


class AuthenticationError(Exception):
    """Raised when a request fails authentication."""

    def __init__(self, detail: str, status_code: int = 401) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


class AzureADAuthProvider:
    """Validates Azure AD JWT bearer tokens using JWKS public keys.

    Uses ``PyJWKClient`` from the ``PyJWT`` library which handles key
    fetching, caching, and automatic refresh on signature failure
    (key rotation).

    :param tenant_id: Azure AD tenant ID.
    :param client_id: Azure AD application (client) ID used as audience.
    :param dev_mode: If True, skip signature verification (local dev only).
    """

    def __init__(
        self,
        tenant_id: str,
        client_id: str,
        dev_mode: bool = False,
    ) -> None:
        self._tenant_id = tenant_id
        self._client_id = client_id
        self._dev_mode = dev_mode
        self._issuer = _ISSUER_V2.format(tenant=tenant_id)
        self._jwks_url = _OPENID_CONFIG_URL.format(tenant=tenant_id)
        self._jwks_client: Optional[jwt.PyJWKClient] = None

        if not dev_mode:
            self._jwks_client = jwt.PyJWKClient(
                self._jwks_url,
                cache_keys=True,
                lifespan=86400,
            )

    def validate_token(self, token: str) -> AuthenticatedUser:
        """Validate a JWT bearer token and return the authenticated user.

        :param token: Raw JWT string from the Authorization header.
        :returns: Authenticated user derived from token claims.
        :rtype: AuthenticatedUser
        :raises AuthenticationError: If the token is invalid or expired.
        """
        if self._dev_mode:
            return self._validate_dev_token(token)

        return self._validate_production_token(token)

    def _validate_production_token(self, token: str) -> AuthenticatedUser:
        """Validate token with full JWKS signature verification.

        :param token: Raw JWT string.
        :returns: Authenticated user.
        :raises AuthenticationError: On any validation failure.
        """
        assert self._jwks_client is not None

        try:
            signing_key = self._jwks_client.get_signing_key_from_jwt(token)
        except jwt.PyJWKClientConnectionError as exc:
            logger.error("JWKS endpoint unreachable: %s", exc)
            raise AuthenticationError(
                "Authentication service unavailable", status_code=503
            ) from exc
        except jwt.PyJWKClientError as exc:
            logger.warning("JWKS key resolution failed: %s", exc)
            raise AuthenticationError("Invalid token") from exc

        try:
            accepted_audiences = [
                self._client_id,
                f"api://{self._client_id}",
            ]
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=_ALGORITHMS,
                audience=accepted_audiences,
                issuer=self._issuer,
                options={
                    "require": ["exp", "iss", "aud", "oid"],
                    "verify_exp": True,
                    "verify_iss": True,
                    "verify_aud": True,
                },
            )
        except jwt.ExpiredSignatureError as exc:
            raise AuthenticationError("Token has expired") from exc
        except jwt.InvalidAudienceError as exc:
            raise AuthenticationError("Invalid audience") from exc
        except jwt.InvalidIssuerError as exc:
            raise AuthenticationError("Invalid issuer") from exc
        except jwt.InvalidTokenError as exc:
            logger.warning("JWT validation failed: %s", exc)
            raise AuthenticationError("Invalid token") from exc

        tid = claims.get("tid", "")
        if tid != self._tenant_id:
            raise AuthenticationError("Invalid tenant")

        return self._claims_to_user(claims)

    def _validate_dev_token(self, token: str) -> AuthenticatedUser:
        """Decode token without signature verification (dev mode only).

        :param token: Raw JWT string.
        :returns: Authenticated user from unverified claims.
        :raises AuthenticationError: If the token is malformed.
        """
        try:
            claims = jwt.decode(
                token,
                options={
                    "verify_signature": False,
                    "verify_exp": False,
                    "verify_aud": False,
                    "verify_iss": False,
                },
                algorithms=_ALGORITHMS,
            )
        except jwt.InvalidTokenError as exc:
            logger.warning("Dev-mode token decode failed: %s", exc)
            raise AuthenticationError("Malformed token") from exc

        logger.warning(
            "AUTH_DEV_MODE: token accepted without verification " "(oid=%s)",
            claims.get("oid", "unknown"),
        )
        return self._claims_to_user(claims)

    @staticmethod
    def _claims_to_user(claims: dict[str, Any]) -> AuthenticatedUser:
        """Map decoded JWT claims to an AuthenticatedUser.

        :param claims: Decoded JWT claims dictionary.
        :returns: AuthenticatedUser value object.
        """
        return AuthenticatedUser(
            oid=claims.get("oid", ""),
            name=claims.get("name", ""),
            email=claims.get("preferred_username", claims.get("upn", "")),
            tenant_id=claims.get("tid", ""),
            roles=tuple(claims.get("roles", [])),
            raw_claims=claims,
        )


class AuthMiddleware:
    """ASGI middleware that enforces Azure AD authentication.

    Injects ``AuthenticatedUser`` into ``request.state.user`` for
    downstream route handlers.

    :param app: The ASGI application to wrap.
    :param auth_provider: Configured AzureADAuthProvider instance.
    :param public_paths: Set of paths that do not require authentication.
    """

    def __init__(
        self,
        app: Any,
        auth_provider: AzureADAuthProvider,
        public_paths: Optional[set[str]] = None,
    ) -> None:
        self._app = app
        self._auth_provider = auth_provider
        self._public_paths = public_paths or set()
        self._bearer_scheme = HTTPBearer(auto_error=False)

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        """ASGI interface — intercept HTTP requests for auth.

        :param scope: ASGI connection scope.
        :param receive: ASGI receive callable.
        :param send: ASGI send callable.
        """
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        request = Request(scope, receive, send)
        path = request.url.path.rstrip("/")

        if self._is_public(path):
            await self._app(scope, receive, send)
            return

        credentials = await self._extract_credentials(request)
        if credentials is None:
            response = JSONResponse(
                status_code=401,
                content={"detail": "Missing authentication credentials"},
                headers={"WWW-Authenticate": "Bearer"},
            )
            await response(scope, receive, send)
            return

        try:
            user = self._auth_provider.validate_token(credentials.credentials)
        except AuthenticationError as exc:
            response = JSONResponse(
                status_code=exc.status_code,
                content={"detail": exc.detail},
                headers={"WWW-Authenticate": "Bearer"},
            )
            await response(scope, receive, send)
            return

        scope.setdefault("state", {})
        scope["state"]["user"] = user
        await self._app(scope, receive, send)

    def _is_public(self, path: str) -> bool:
        """Check if a path is in the public (unauthenticated) set.

        :param path: Request path (without trailing slash).
        :returns: True if the path should bypass auth.
        """
        if path in self._public_paths:
            return True
        stripped = path.rstrip("/")
        if stripped in self._public_paths:
            return True
        if not stripped and "/" in self._public_paths:
            return True
        return any(path.startswith(p) for p in self._public_paths if p.endswith("/") and len(p) > 1)

    async def _extract_credentials(
        self, request: Request
    ) -> Optional[HTTPAuthorizationCredentials]:
        """Extract Bearer token from the Authorization header.

        :param request: Incoming HTTP request.
        :returns: Credentials if present, None otherwise.
        """
        return await self._bearer_scheme(request)


_auth_provider: Optional[AzureADAuthProvider] = None


def get_auth_provider() -> Optional[AzureADAuthProvider]:
    """Return the module-level auth provider (for route-level access).

    :returns: The configured provider, or None if not initialized.
    """
    return _auth_provider


def create_auth_provider() -> AzureADAuthProvider:
    """Factory that reads configuration from environment variables.

    Validates that required variables are present and returns a
    configured ``AzureADAuthProvider``.

    :returns: Configured auth provider.
    :raises ValueError: If required environment variables are missing.
    """
    global _auth_provider

    tenant_id = os.environ.get("AZURE_TENANT_ID", "").strip()
    client_id = os.environ.get("AZURE_CLIENT_ID", "").strip()
    auth_dev_mode = os.environ.get("AUTH_DEV_MODE", "").lower() == "true"
    log_format = os.environ.get("LOG_FORMAT", "console").lower()

    if auth_dev_mode and log_format == "json":
        raise ValueError(
            "AUTH_DEV_MODE cannot be enabled when LOG_FORMAT=json "
            "(production safety guard). Remove AUTH_DEV_MODE or set "
            "LOG_FORMAT to a non-production value."
        )

    if not auth_dev_mode and (not tenant_id or not client_id):
        raise ValueError(
            "AZURE_TENANT_ID and AZURE_CLIENT_ID are required when "
            "AUTH_DEV_MODE is not enabled. Set these environment "
            "variables or enable AUTH_DEV_MODE for local development."
        )

    if auth_dev_mode:
        logger.warning(
            "AUTH_DEV_MODE is enabled — tokens will NOT be verified. " "Do not use in production."
        )

    provider = AzureADAuthProvider(
        tenant_id=tenant_id or "dev-tenant",
        client_id=client_id or "dev-client",
        dev_mode=auth_dev_mode,
    )
    _auth_provider = provider
    return provider


def get_public_paths() -> set[str]:
    """Return the set of paths that should bypass authentication.

    :returns: Set of public path prefixes/exact matches.
    """
    return {
        "/healthz",
        "/",
        "/docs",
        "/openapi.json",
        "/redoc",
        "/auth/config",
    }
