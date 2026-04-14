# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
SAP token verifier — implements the MCP SDK's ``TokenVerifier`` protocol.

Configuration via environment variables:
- ``MCP_AUTH_MODE``: ``none`` (default), ``api_key``, ``bearer``, ``mi``
- ``MCP_API_KEY``: Required when mode is ``api_key``
- ``MCP_BEARER_TOKEN``: Required when mode is ``bearer``
- ``AZURE_TENANT_ID`` / ``AZURE_CLIENT_ID``: Required when mode is ``azure_ad``
"""

from __future__ import annotations
import hashlib
import hmac
import logging
import os
from mcp.server.auth.provider import AccessToken
from src.api.auth import (
    AzureADAuthProvider,
    AuthenticationError,
)

logger = logging.getLogger(__name__)


class SapTokenVerifier:
    """Token verifier for SAP MCP server.

    :param auth_mode: ``api_key``, ``bearer``, ``azure_ad``, or ``none``.
    :param api_key: Expected API key (for ``api_key`` mode).
    :param bearer_token: Expected bearer token (for ``bearer`` mode).
    :param azure_ad_provider: Shared Azure AD auth provider (for ``azure_ad`` mode).
    """

    def __init__(
        self,
        auth_mode: str = "none",
        api_key: str = "",
        bearer_token: str = "",
        azure_ad_provider: AzureADAuthProvider | None = None,
    ) -> None:
        self._auth_mode = auth_mode.lower()
        self._api_key = api_key
        self._bearer_token = bearer_token
        self._azure_ad_provider = azure_ad_provider

        if self._auth_mode == "api_key" and not self._api_key:
            raise ValueError("MCP_API_KEY required when auth mode is 'api_key'")
        if self._auth_mode == "bearer" and not self._bearer_token:
            raise ValueError("MCP_BEARER_TOKEN required when auth mode is 'bearer'")
        if self._auth_mode == "azure_ad" and not self._azure_ad_provider:
            raise ValueError("AzureADAuthProvider required when auth mode is 'azure_ad'")

    async def verify_token(self, token: str) -> AccessToken | None:
        """Verify a bearer token and return access info if valid.

        :param token: The raw bearer token from the Authorization header.
        :returns: ``AccessToken`` on success, ``None`` on failure.
        """
        if self._auth_mode == "api_key":
            return self._check_api_key(token)

        if self._auth_mode == "bearer":
            return self._check_bearer(token)

        if self._auth_mode == "azure_ad":
            return self._check_azure_ad(token)

        return None

    def _check_api_key(self, token: str) -> AccessToken | None:
        """Validate a static API key using timing-safe comparison.

        :param token: Candidate API key.
        :returns: AccessToken on match, None otherwise.
        """
        if not token or not hmac.compare_digest(token, self._api_key):
            return None
        return AccessToken(
            token=token,
            client_id=f"apikey-{hashlib.sha256(token.encode()).hexdigest()[:12]}",
            scopes=["mcp:tools"],
        )

    def _check_bearer(self, token: str) -> AccessToken | None:
        """Validate a static bearer token using timing-safe comparison.

        :param token: Candidate bearer token.
        :returns: AccessToken on match, None otherwise.
        """
        if not token or not hmac.compare_digest(token, self._bearer_token):
            return None
        return AccessToken(
            token=token,
            client_id=f"bearer-{hashlib.sha256(token.encode()).hexdigest()[:12]}",
            scopes=["mcp:tools"],
        )

    def _check_azure_ad(self, token: str) -> AccessToken | None:
        """Validate an Azure AD JWT using shared JWKS provider.

        :param token: JWT bearer token.
        :returns: AccessToken on success, None on failure.
        """
        if not token or not self._azure_ad_provider:
            return None
        try:
            user = self._azure_ad_provider.validate_token(token)
            return AccessToken(
                token=token,
                client_id=f"aad-{user.oid}",
                scopes=["mcp:tools"],
            )
        except AuthenticationError as exc:
            logger.warning("Azure AD token validation failed: %s", exc.detail)
            return None


def create_token_verifier() -> SapTokenVerifier | None:
    """Factory that reads auth config from environment variables.

    :returns: Configured verifier, or ``None`` when auth is disabled.
    """
    auth_mode = os.environ.get("MCP_AUTH_MODE", "none").lower()
    if auth_mode == "none":
        return None

    azure_ad_provider: AzureADAuthProvider | None = None
    if auth_mode == "azure_ad":
        tenant_id = os.environ.get("AZURE_TENANT_ID", "").strip()
        client_id = os.environ.get("AZURE_CLIENT_ID", "").strip()
        dev_mode = os.environ.get("AUTH_DEV_MODE", "").lower() == "true"

        if not dev_mode and (not tenant_id or not client_id):
            raise ValueError(
                "AZURE_TENANT_ID and AZURE_CLIENT_ID are required "
                "when MCP_AUTH_MODE is 'azure_ad' and AUTH_DEV_MODE "
                "is not enabled."
            )

        azure_ad_provider = AzureADAuthProvider(
            tenant_id=tenant_id or "dev-tenant",
            client_id=client_id or "dev-client",
            dev_mode=dev_mode,
        )

    return SapTokenVerifier(
        auth_mode=auth_mode,
        api_key=os.environ.get("MCP_API_KEY", ""),
        bearer_token=os.environ.get("MCP_BEARER_TOKEN", ""),
        azure_ad_provider=azure_ad_provider,
    )
