# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for CoreApiClient error mapping (CoreApiError/CoreApiUnavailableError)."""

from typing import Callable, Optional
import httpx
import pytest
from src.api.mcp_server.core_client import CoreApiClient
from src.api.mcp_server.errors import CoreApiError, CoreApiUnavailableError


def _client_returning(
    status_code: int, *, json: Optional[dict] = None, text: Optional[str] = None
) -> CoreApiClient:
    """Build a CoreApiClient whose mocked transport always returns a fixed response.

    :param status_code: HTTP status code to return for every request.
    :type status_code: int
    :param json: JSON body to return, or ``None`` for a non-JSON/empty body.
    :type json: Optional[dict]
    :param text: Plain-text body to return when ``json`` is not given.
    :type text: Optional[str]
    :return: Client injected with an ``httpx.AsyncClient`` using the mock transport.
    :rtype: CoreApiClient
    """

    def handler(request: httpx.Request) -> httpx.Response:
        """Return the fixed response configured for this client.

        :param request: Captured outgoing HTTP request (unused).
        :type request: httpx.Request
        :return: The fixed response for this test.
        :rtype: httpx.Response
        """
        del request
        if json is not None:
            return httpx.Response(status_code, json=json)
        return httpx.Response(status_code, text=text or "")

    async_client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://test")
    return CoreApiClient(client=async_client)


def _client_raising(exc_factory: Callable[[httpx.Request], Exception]) -> CoreApiClient:
    """Build a CoreApiClient whose mocked transport always raises a transport error.

    :param exc_factory: Builds the exception to raise from the captured request.
    :type exc_factory: Callable[[httpx.Request], Exception]
    :return: Client injected with an ``httpx.AsyncClient`` using the mock transport.
    :rtype: CoreApiClient
    """

    def handler(request: httpx.Request) -> httpx.Response:
        """Raise the configured transport error instead of returning a response.

        :param request: Captured outgoing HTTP request.
        :type request: httpx.Request
        :return: Never returns; always raises.
        :rtype: httpx.Response
        """
        raise exc_factory(request)

    async_client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://test")
    return CoreApiClient(client=async_client)


class TestCoreApiClientErrors:
    """Tests for non-2xx and transport-failure error mapping."""

    async def test_4xx_response_raises_core_api_error_with_status_and_detail(self) -> None:
        """A 404 JSON ``{"detail": ...}`` response raises CoreApiError."""
        client = _client_returning(404, json={"detail": "Job abc not found"})

        with pytest.raises(CoreApiError) as exc_info:
            await client.get_job("abc")

        assert exc_info.value.status_code == 404
        assert "Job abc not found" in exc_info.value.detail

    async def test_5xx_response_raises_core_api_error_with_status_and_detail(self) -> None:
        """A 500 JSON response raises CoreApiError carrying the status code."""
        client = _client_returning(500, json={"detail": "Internal error"})

        with pytest.raises(CoreApiError) as exc_info:
            await client.get_job("abc")

        assert exc_info.value.status_code == 500
        assert "Internal error" in exc_info.value.detail

    async def test_non_json_error_body_is_sanitized_and_bounded(self) -> None:
        """A non-JSON error body still raises CoreApiError with a bounded detail."""
        client = _client_returning(502, text="x" * 5000)

        with pytest.raises(CoreApiError) as exc_info:
            await client.get_job("abc")

        assert exc_info.value.status_code == 502
        assert len(exc_info.value.detail) <= 500

    async def test_connection_error_raises_core_api_unavailable_error_with_chaining(self) -> None:
        """A transport connection failure raises CoreApiUnavailableError, chained."""
        client = _client_raising(
            lambda request: httpx.ConnectError("connection refused", request=request)
        )

        with pytest.raises(CoreApiUnavailableError) as exc_info:
            await client.get_job("abc")

        assert isinstance(exc_info.value.__cause__, httpx.ConnectError)

    async def test_timeout_raises_core_api_unavailable_error_with_chaining(self) -> None:
        """A transport timeout raises CoreApiUnavailableError, chained."""
        client = _client_raising(lambda request: httpx.ReadTimeout("timed out", request=request))

        with pytest.raises(CoreApiUnavailableError) as exc_info:
            await client.get_job("abc")

        assert isinstance(exc_info.value.__cause__, httpx.ReadTimeout)
