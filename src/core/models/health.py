# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Health check models."""

from typing import Dict, Optional

from pydantic import BaseModel, Field


class ComponentHealth(BaseModel):
    """Health status of a single component.

    :param status: ``healthy``, ``unhealthy``, or ``unconfigured``.
    :param latency_ms: Round-trip probe latency in milliseconds.
    :param detail: Human-readable detail (error message, tool count, etc.).
    """

    status: str
    latency_ms: Optional[float] = None
    detail: str = ""


class HealthResponse(BaseModel):
    """Aggregated health check response.

    :param status: ``healthy`` if all configured components are up,
        ``degraded`` if any optional component is down,
        ``unhealthy`` if the core server is down.
    :param timestamp: ISO-8601 UTC timestamp.
    :param version: API version string.
    :param services: Legacy per-service boolean flags.
    :param components: Detailed per-component health.
    """

    status: str
    timestamp: str
    version: str
    services: Dict[str, bool] = Field(default_factory=dict)
    components: Dict[str, ComponentHealth] = Field(default_factory=dict)
