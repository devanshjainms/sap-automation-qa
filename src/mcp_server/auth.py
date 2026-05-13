# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""SAP token verifier for MCP server authentication.

Configuration via environment variables:

- ``MCP_AUTH_MODE``: ``none`` (default), ``api_key``, ``bearer``
- ``MCP_API_KEY``: Required when mode is ``api_key``
- ``MCP_BEARER_TOKEN``: Required when mode is ``bearer``
"""

from __future__ import annotations
import hashlib
import hmac
import logging
import os
from mcp.server.auth.provider import AccessToken

logger = logging.getLogger(__name__)


class SapTokenVerifier:
    """Token verifier for SAP MCP server.

    :param auth_mode: ``api_key``, ``bearer``, or ``none``.
    :param api_key: Expected API key (for ``api_key`` mode).
    :param bearer_token: Expected bearer token (for ``bearer`` mode).
    """

    def __init__(
        self,
        auth_mode: str = "none",
        api_key: str = "",
        bearer_token: str = "",
    ) -> None:
        self._auth_mode = auth_mode.lower()
        self._api_key = api_key
        self._bearer_token = bearer_token

        if self._auth_mode == "api_key" and not self._api_key:
            raise ValueError("MCP_API_KEY required when auth mode is 'api_key'")
        if self._auth_mode == "bearer" and not self._bearer_token:
            raise ValueError("MCP_BEARER_TOKEN required when auth mode is 'bearer'")

    async def verify_token(self, token: str) -> AccessToken | None:
        """Verify a bearer token and return access info if valid.

        :param token: The raw bearer token from the Authorization header.
        :returns: ``AccessToken`` on success, ``None`` on failure.
        """
        if self._auth_mode == "api_key":
            return self._check_api_key(token)
        if self._auth_mode == "bearer":
            return self._check_bearer(token)
        return None

    def _check_api_key(self, token: str) -> AccessToken | None:
        """Validate a static API key using timing-safe comparison."""
        if not token or not hmac.compare_digest(token, self._api_key):
            return None
        return AccessToken(
            token=token,
            client_id=f"apikey-{hashlib.sha256(token.encode()).hexdigest()[:12]}",
            scopes=["mcp:tools"],
        )

    def _check_bearer(self, token: str) -> AccessToken | None:
        """Validate a static bearer token using timing-safe comparison."""
        if not token or not hmac.compare_digest(token, self._bearer_token):
            return None
        return AccessToken(
            token=token,
            client_id=f"bearer-{hashlib.sha256(token.encode()).hexdigest()[:12]}",
            scopes=["mcp:tools"],
        )


def create_token_verifier() -> SapTokenVerifier | None:
    """Factory that reads auth config from environment variables.

    :returns: Configured verifier, or ``None`` when auth is disabled.
    """
    auth_mode = os.environ.get("MCP_AUTH_MODE", "none").lower()
    if auth_mode == "none":
        return None

    return SapTokenVerifier(
        auth_mode=auth_mode,
        api_key=os.environ.get("MCP_API_KEY", ""),
        bearer_token=os.environ.get("MCP_BEARER_TOKEN", ""),
    )
