# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Health service for probing MCP servers."""

from __future__ import annotations
import asyncio
import time
from typing import Any, Dict, Optional
import httpx
from src.core.models.health import ComponentHealth


class HealthService:
    """Probes MCP servers for health.

    :param mcp_urls: Mapping of server name to base URL.
    :param azure_mcp_url: Azure MCP server base URL (empty = unconfigured).
    :param timeout: HTTP timeout in seconds for each probe.
    """

    def __init__(
        self,
        mcp_urls: Optional[Dict[str, str]] = None,
        azure_mcp_url: str = "",
        timeout: float = 5.0,
    ) -> None:
        self._mcp_urls = mcp_urls or {}
        self._azure_mcp_url = azure_mcp_url.rstrip("/")
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
