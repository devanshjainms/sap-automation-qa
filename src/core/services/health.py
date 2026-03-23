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
    :param timeout: HTTP timeout in seconds for each probe.
    """

    def __init__(
        self,
        mcp_urls: Optional[Dict[str, str]] = None,
        llm_endpoint: str = "",
        llm_deployment: str = "",
        llm_api_key: str = "",
        llm_api_version: str = "2024-12-01-preview",
        timeout: float = 5.0,
    ) -> None:
        self._mcp_urls = mcp_urls or {}
        self._llm_endpoint = llm_endpoint.rstrip("/")
        self._llm_deployment = llm_deployment
        self._llm_api_key = llm_api_key
        self._llm_api_version = llm_api_version
        self._timeout = timeout

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

        Sends a tiny prompt (``max_tokens=1``) to verify connectivity
        without burning tokens.

        :returns: Component health result.
        """
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
            "max_completion_tokens": 1,
        }

        start = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(url, json=body, headers=headers)
                latency = (time.monotonic() - start) * 1000
                if resp.status_code == 200:
                    return ComponentHealth(
                        status="healthy",
                        latency_ms=round(latency, 1),
                        detail=f"deployment={self._llm_deployment}",
                    )
                return ComponentHealth(
                    status="unhealthy",
                    latency_ms=round(latency, 1),
                    detail=f"HTTP {resp.status_code}",
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

        results: Dict[str, ComponentHealth] = {}
        gathered = await asyncio.gather(*tasks.values(), return_exceptions=True)
        for key, result in zip(tasks.keys(), gathered):
            if isinstance(result, BaseException):
                results[key] = ComponentHealth(status="unhealthy", detail=str(result))
            else:
                results[key] = result
        return results
