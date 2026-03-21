# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Health check endpoints with deep checks for MCP servers and LLM."""

from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import Dict, Optional
from fastapi import APIRouter
from src.core.models.health import ComponentHealth, HealthResponse
from src.core.services.health import HealthService

logger = logging.getLogger(__name__)
router = APIRouter(tags=["health"])

_service_status: Dict[str, bool] = {}
_health_service: Optional[HealthService] = None


def set_service_status(name: str, running: bool) -> None:
    """Set a service's status for health check.

    :param name: Service name (e.g., "scheduler", "worker").
    :param running: Whether the service is running.
    """
    _service_status[name] = running


def set_health_service(service: Optional[HealthService]) -> None:
    """Inject the health service (called from lifespan).

    :param service: HealthService instance, or None to disable deep checks.
    """
    global _health_service
    _health_service = service


@router.get("/healthz", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Check API health status including MCP servers and LLM.

    :returns: Health status with per-component detail.
    :rtype: HealthResponse
    """
    components: Dict[str, ComponentHealth] = {
        "core": ComponentHealth(status="healthy", detail="API responding"),
    }

    if _health_service is not None:
        deep = await _health_service.check_all()
        components.update(deep)

    all_statuses = [c.status for c in components.values()]
    if all(s in ("healthy", "unconfigured") for s in all_statuses):
        overall = "healthy"
    else:
        overall = "degraded"

    return HealthResponse(
        status=overall,
        timestamp=datetime.now(timezone.utc).isoformat(),
        version="1.0.0",
        services=_service_status.copy(),
        components=components,
    )


@router.get("/")
async def root() -> dict:
    """Root endpoint.

    :returns: Service information and documentation link.
    :rtype: dict
    """
    return {
        "service": "SAP QA Scheduler API",
        "version": "1.0.0",
        "docs": "/docs",
    }
