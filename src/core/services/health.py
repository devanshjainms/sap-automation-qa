# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Health service for probing MCP servers and LLM connectivity."""

from __future__ import annotations
import asyncio
import time
from typing import Any, Dict, Optional
import httpx
from src.core.models.health import ComponentHealth


class HealthService:
    """Probes MCP servers and LLM endpoint for health.

    :param mcp_urls: Mapping of server name to base URL.
    :param llm_endpoint: Azure OpenAI endpoint URL (empty = unconfigured).
    :param llm_deployment: Deployment name for the health probe.
    :param llm_api_key: API key (omit for managed-identity).
    :param llm_api_version: Azure OpenAI API version.
    :param ollama_url: Ollama base URL (empty = unconfigured).
    :param azure_mcp_url: Azure MCP server base URL (empty = unconfigured).
    :param timeout: HTTP timeout in seconds for each probe.
    """

    def __init__(
        self,
        mcp_urls: Optional[Dict[str, str]] = None,
        llm_endpoint: str = "",
        llm_deployment: str = "",
        llm_api_key: str = "",
        llm_api_version: str = "2024-12-01-preview",
        ollama_url: str = "",
        azure_mcp_url: str = "",
        timeout: float = 5.0,
    ) -> None:
        self._mcp_urls = mcp_urls or {}
        self._llm_endpoint = llm_endpoint.rstrip("/")
        self._llm_deployment = llm_deployment
        self._llm_api_key = llm_api_key
        self._llm_api_version = llm_api_version
        self._ollama_url = ollama_url.rstrip("/")
        self._azure_mcp_url = azure_mcp_url.rstrip("/")
        self._timeout = timeout
        self._llm_cache: Optional[ComponentHealth] = None
        self._llm_cache_time: float = 0.0
        self._llm_cache_ttl: float = 300.0

    async def check_mcp(self, name: str, url: str) -> ComponentHealth:
        """Probe a single MCP server via its ``/mcp`` endpoint.

        Any HTTP response (including 405/406) means the server is up
        and accepting connections.  Only connection failures are unhealthy.

        :param name: Server display name.
        :param url: Base URL of the MCP server.
        :returns: Component health result.
        """
        start = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(f"{url.rstrip('/')}/mcp")
                latency = (time.monotonic() - start) * 1000
                return ComponentHealth(
                    status="healthy",
                    latency_ms=round(latency, 1),
                    detail=f"{name} reachable (HTTP {resp.status_code})",
                )
        except Exception as exc:
            latency = (time.monotonic() - start) * 1000
            return ComponentHealth(
                status="unhealthy",
                latency_ms=round(latency, 1),
                detail=str(exc),
            )

    async def check_llm(self) -> ComponentHealth:
        """Probe the Azure OpenAI endpoint with a minimal completions call.

        Results are cached for ``_llm_cache_ttl`` seconds to avoid
        burning LLM quota on Docker healthcheck polling.

        :returns: Component health result.
        """
        if (
            self._llm_cache is not None
            and (time.monotonic() - self._llm_cache_time) < self._llm_cache_ttl
        ):
            return self._llm_cache

        if not self._llm_endpoint or not self._llm_deployment:
            return ComponentHealth(status="unconfigured", detail="LLM not configured")

        url = (
            f"{self._llm_endpoint}/openai/deployments/"
            f"{self._llm_deployment}/chat/completions"
            f"?api-version={self._llm_api_version}"
        )
        headers: Dict[str, str] = {"Content-Type": "application/json"}
        if self._llm_api_key:
            headers["api-key"] = self._llm_api_key

        body = {
            "messages": [{"role": "user", "content": "ping"}],
            "max_completion_tokens": 5,
        }

        start = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(url, json=body, headers=headers)
                latency = (time.monotonic() - start) * 1000
                if resp.status_code == 200:
                    result = ComponentHealth(
                        status="healthy",
                        latency_ms=round(latency, 1),
                        detail=f"deployment={self._llm_deployment}",
                    )
                else:
                    result = ComponentHealth(
                        status="unhealthy",
                        latency_ms=round(latency, 1),
                        detail=f"HTTP {resp.status_code}",
                    )
        except Exception as exc:
            latency = (time.monotonic() - start) * 1000
            result = ComponentHealth(
                status="unhealthy",
                latency_ms=round(latency, 1),
                detail=str(exc),
            )

        self._llm_cache = result
        self._llm_cache_time = time.monotonic()
        return result

    async def check_url(
        self,
        url: str,
        path: str = "/",
        label: str = "",
    ) -> ComponentHealth:
        """Probe a URL with a simple GET request.

        Any HTTP response means the service is reachable.

        :param url: Base URL of the service.
        :param path: Path to probe.
        :param label: Display label for the component.
        :returns: Component health result.
        """
        start = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(f"{url}{path}")
                latency = (time.monotonic() - start) * 1000
                return ComponentHealth(
                    status="healthy",
                    latency_ms=round(latency, 1),
                    detail=f"{label} reachable (HTTP {resp.status_code})",
                )
        except Exception as exc:
            latency = (time.monotonic() - start) * 1000
            return ComponentHealth(
                status="unhealthy",
                latency_ms=round(latency, 1),
                detail=str(exc),
            )

    async def check_all(self) -> Dict[str, ComponentHealth]:
        """Run all health probes in parallel.

        :returns: Mapping of component name to health result.
        """
        tasks: Dict[str, Any] = {}
        for name, url in self._mcp_urls.items():
            tasks[f"mcp:{name}"] = self.check_mcp(name, url)
        tasks["llm"] = self.check_llm()
        if self._ollama_url:
            tasks["ollama"] = self.check_url(
                self._ollama_url,
                "/api/tags",
                "Ollama",
            )
        if self._azure_mcp_url:
            tasks["azure_mcp"] = self.check_url(
                self._azure_mcp_url,
                "/mcp",
                "Azure MCP",
            )

        results: Dict[str, ComponentHealth] = {}
        gathered = await asyncio.gather(*tasks.values(), return_exceptions=True)
        for key, result in zip(tasks.keys(), gathered):
            if isinstance(result, BaseException):
                results[key] = ComponentHealth(status="unhealthy", detail=str(result))
            else:
                results[key] = result
        return results
