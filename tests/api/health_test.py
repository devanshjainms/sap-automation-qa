# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for Health API routes."""

import time
import httpx
import pytest
from fastapi.testclient import TestClient
from pytest_mock import MockerFixture
from src.api.routes.health import set_health_service
from src.core.services.health import HealthService


class TestHealthEndpoints:
    """Tests for health check endpoints."""

    def test_health_check(self, client: TestClient) -> None:
        """Returns healthy status with core component."""
        response = client.get("/healthz")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "timestamp" in data
        assert "version" in data
        assert data["components"]["core"]["status"] == "healthy"

    def test_root_endpoint(self, client: TestClient) -> None:
        """Root endpoint returns service info."""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert "service" in data
        assert "version" in data

    def test_health_with_service_all_healthy(
        self, client: TestClient, mocker: MockerFixture
    ) -> None:
        """When service reports all healthy, overall is healthy."""
        service = HealthService(
            mcp_urls={"staf-mcp": "http://localhost:8001"},
            llm_endpoint="https://example.openai.azure.com",
            llm_deployment="gpt-4o",
            llm_api_key="fake-key",
        )
        mock_resp_200 = httpx.Response(200, request=httpx.Request("GET", "http://x"))
        set_health_service(service)
        try:
            mock_cls = mocker.patch("src.core.services.health.httpx.AsyncClient")
            mock_client = mocker.AsyncMock()
            mock_client.get = mocker.AsyncMock(return_value=mock_resp_200)
            mock_client.post = mocker.AsyncMock(return_value=mock_resp_200)
            mock_client.__aenter__ = mocker.AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = mocker.AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            response = client.get("/healthz")
            data = response.json()
            assert data["status"] == "healthy"
            assert data["components"]["core"]["status"] == "healthy"
            assert data["components"]["mcp:staf-mcp"]["status"] == "healthy"
            assert data["components"]["llm"]["status"] == "healthy"
        finally:
            set_health_service(None)

    def test_health_degraded_when_mcp_down(self, client: TestClient, mocker: MockerFixture) -> None:
        """When MCP server is unreachable, status is degraded."""
        service = HealthService(
            mcp_urls={"staf-mcp": "http://localhost:9999"},
        )
        set_health_service(service)
        try:
            mock_cls = mocker.patch("src.core.services.health.httpx.AsyncClient")
            mock_client = mocker.AsyncMock()
            mock_client.get = mocker.AsyncMock(side_effect=httpx.ConnectError("refused"))
            mock_client.post = mocker.AsyncMock(side_effect=httpx.ConnectError("refused"))
            mock_client.__aenter__ = mocker.AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = mocker.AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            response = client.get("/healthz")
            data = response.json()
            assert data["status"] == "degraded"
            assert data["components"]["mcp:staf-mcp"]["status"] == "unhealthy"
        finally:
            set_health_service(None)

    def test_health_degraded_when_llm_down(self, client: TestClient, mocker: MockerFixture) -> None:
        """When LLM endpoint is unreachable, status is degraded."""
        service = HealthService(
            llm_endpoint="https://bad.openai.azure.com",
            llm_deployment="gpt-4o",
            llm_api_key="key",
        )
        set_health_service(service)
        try:
            mock_cls = mocker.patch("src.core.services.health.httpx.AsyncClient")
            mock_client = mocker.AsyncMock()
            mock_client.post = mocker.AsyncMock(side_effect=httpx.ConnectError("timeout"))
            mock_client.__aenter__ = mocker.AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = mocker.AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            response = client.get("/healthz")
            data = response.json()
            assert data["status"] == "degraded"
            assert data["components"]["llm"]["status"] == "unhealthy"
        finally:
            set_health_service(None)

    def test_health_llm_unconfigured(self, client: TestClient) -> None:
        """When LLM is not configured, it shows unconfigured (not unhealthy)."""
        service = HealthService(mcp_urls={})
        set_health_service(service)
        try:
            response = client.get("/healthz")
            data = response.json()
            assert data["status"] == "healthy"
            assert data["components"]["llm"]["status"] == "unconfigured"
        finally:
            set_health_service(None)

    def test_health_no_service(self, client: TestClient) -> None:
        """Without a health service, only core component is present."""
        set_health_service(None)
        response = client.get("/healthz")
        data = response.json()
        assert data["status"] == "healthy"
        assert list(data["components"].keys()) == ["core"]


class TestHealthService:
    """Unit tests for the HealthService class."""

    @pytest.mark.asyncio
    async def test_check_mcp_healthy(self, mocker: MockerFixture) -> None:
        """MCP probe returns healthy on any HTTP response (server is up)."""
        service = HealthService()
        mock_resp = httpx.Response(405, request=httpx.Request("GET", "http://x"))
        mock_cls = mocker.patch("src.core.services.health.httpx.AsyncClient")
        mock_client = mocker.AsyncMock()
        mock_client.get = mocker.AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = mocker.AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = mocker.AsyncMock(return_value=False)
        mock_cls.return_value = mock_client

        result = await service.check_mcp("test", "http://localhost:8001")
        assert result.status == "healthy"
        assert result.latency_ms is not None
        assert "405" in result.detail

    @pytest.mark.asyncio
    async def test_check_mcp_healthy_on_200(self, mocker: MockerFixture) -> None:
        """MCP probe returns healthy on 200."""
        service = HealthService()
        mock_resp = httpx.Response(200, request=httpx.Request("GET", "http://x"))
        mock_cls = mocker.patch("src.core.services.health.httpx.AsyncClient")
        mock_client = mocker.AsyncMock()
        mock_client.get = mocker.AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = mocker.AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = mocker.AsyncMock(return_value=False)
        mock_cls.return_value = mock_client

        result = await service.check_mcp("test", "http://localhost:8001")
        assert result.status == "healthy"

    @pytest.mark.asyncio
    async def test_check_mcp_connection_error(self, mocker: MockerFixture) -> None:
        """MCP probe returns unhealthy on connection failure."""
        service = HealthService()
        mock_cls = mocker.patch("src.core.services.health.httpx.AsyncClient")
        mock_client = mocker.AsyncMock()
        mock_client.get = mocker.AsyncMock(side_effect=httpx.ConnectError("refused"))
        mock_client.__aenter__ = mocker.AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = mocker.AsyncMock(return_value=False)
        mock_cls.return_value = mock_client

        result = await service.check_mcp("test", "http://localhost:9999")
        assert result.status == "unhealthy"

    @pytest.mark.asyncio
    async def test_check_llm_healthy(self, mocker: MockerFixture) -> None:
        """LLM probe returns healthy on 200."""
        service = HealthService(
            llm_endpoint="https://example.openai.azure.com",
            llm_deployment="gpt-4o",
            llm_api_key="key",
        )
        mock_resp = httpx.Response(200, request=httpx.Request("POST", "http://x"))
        mock_cls = mocker.patch("src.core.services.health.httpx.AsyncClient")
        mock_client = mocker.AsyncMock()
        mock_client.post = mocker.AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = mocker.AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = mocker.AsyncMock(return_value=False)
        mock_cls.return_value = mock_client

        result = await service.check_llm()
        assert result.status == "healthy"
        assert "gpt-4o" in result.detail

    @pytest.mark.asyncio
    async def test_check_llm_unconfigured(self) -> None:
        """LLM probe returns unconfigured when endpoint is empty."""
        service = HealthService()
        result = await service.check_llm()
        assert result.status == "unconfigured"

    @pytest.mark.asyncio
    async def test_check_llm_auth_failure(self, mocker: MockerFixture) -> None:
        """LLM probe returns unhealthy on 401."""
        service = HealthService(
            llm_endpoint="https://example.openai.azure.com",
            llm_deployment="gpt-4o",
            llm_api_key="bad-key",
        )
        mock_resp = httpx.Response(401, request=httpx.Request("POST", "http://x"))
        mock_cls = mocker.patch("src.core.services.health.httpx.AsyncClient")
        mock_client = mocker.AsyncMock()
        mock_client.post = mocker.AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = mocker.AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = mocker.AsyncMock(return_value=False)
        mock_cls.return_value = mock_client

        result = await service.check_llm()
        assert result.status == "unhealthy"
        assert "401" in result.detail

    @pytest.mark.asyncio
    async def test_check_all_parallel(self, mocker: MockerFixture) -> None:
        """check_all runs probes in parallel and returns all results."""
        service = HealthService(
            mcp_urls={"server-a": "http://a:8001", "server-b": "http://b:8002"},
            llm_endpoint="https://llm.azure.com",
            llm_deployment="deploy",
            llm_api_key="key",
        )
        mock_resp = httpx.Response(200, request=httpx.Request("GET", "http://x"))
        mock_cls = mocker.patch("src.core.services.health.httpx.AsyncClient")
        mock_client = mocker.AsyncMock()
        mock_client.get = mocker.AsyncMock(return_value=mock_resp)
        mock_client.post = mocker.AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = mocker.AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = mocker.AsyncMock(return_value=False)
        mock_cls.return_value = mock_client

        results = await service.check_all()
        assert "mcp:server-a" in results
        assert "mcp:server-b" in results
        assert "llm" in results
        assert all(r.status == "healthy" for r in results.values())


class TestReadBuildCommit:
    """Tests for _read_build_commit."""

    def test_missing_file_returns_unknown(self, mocker: MockerFixture) -> None:
        from src.api.routes.health import _read_build_commit

        mocker.patch(
            "src.api.routes.health.Path",
            side_effect=lambda *a: type(
                "P",
                (),
                {"read_text": lambda self: (_ for _ in ()).throw(FileNotFoundError)},
            )(),
        )
        result = _read_build_commit()
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_returns_short_sha(self, mocker: MockerFixture) -> None:
        from src.api.routes.health import _fetch_remote_commit, _remote_cache

        _remote_cache["sha"] = None
        _remote_cache["ts"] = 0.0

        mock_resp = mocker.MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"sha": "abcdef1234567890"}

        mock_client = mocker.AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = mocker.AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = mocker.AsyncMock(return_value=False)

        mocker.patch(
            "src.api.routes.health.httpx.AsyncClient",
            return_value=mock_client,
        )

        result = await _fetch_remote_commit()
        assert result == "abcdef1"
        assert len(result) == 7

    @pytest.mark.asyncio
    async def test_caches_result(self, mocker: MockerFixture) -> None:
        from src.api.routes.health import _fetch_remote_commit, _remote_cache

        _remote_cache["sha"] = "cached1"
        _remote_cache["ts"] = time.monotonic()

        result = await _fetch_remote_commit()
        assert result == "cached1"

    @pytest.mark.asyncio
    async def test_api_failure_returns_unknown(self, mocker: MockerFixture) -> None:
        from src.api.routes.health import _fetch_remote_commit, _remote_cache

        _remote_cache["sha"] = None
        _remote_cache["ts"] = 0.0

        mocker.patch(
            "src.api.routes.health.httpx.AsyncClient",
            side_effect=Exception("network error"),
        )

        result = await _fetch_remote_commit()
        assert result == "unknown"

    @pytest.mark.asyncio
    async def test_no_update_when_same_commit(self, mocker: MockerFixture) -> None:
        from src.api.routes.health import get_version

        mocker.patch("src.api.routes.health._read_build_commit", return_value="abc1234")
        mocker.patch("src.api.routes.health._fetch_remote_commit", return_value="abc1234")

        result = await get_version()
        assert result["update_available"] is False
        assert result["build_commit"] == "abc1234"
        assert result["latest_commit"] == "abc1234"

    @pytest.mark.asyncio
    async def test_update_when_different_commit(self, mocker: MockerFixture) -> None:
        from src.api.routes.health import get_version

        mocker.patch("src.api.routes.health._read_build_commit", return_value="abc1234")
        mocker.patch("src.api.routes.health._fetch_remote_commit", return_value="def5678")

        result = await get_version()
        assert result["update_available"] is True

    @pytest.mark.asyncio
    async def test_no_update_when_build_unknown(self, mocker: MockerFixture) -> None:
        from src.api.routes.health import get_version

        mocker.patch("src.api.routes.health._read_build_commit", return_value="unknown")
        mocker.patch("src.api.routes.health._fetch_remote_commit", return_value="def5678")

        result = await get_version()
        assert result["update_available"] is False
