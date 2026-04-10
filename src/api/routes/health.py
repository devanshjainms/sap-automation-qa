# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Health check endpoints with deep checks for MCP servers and LLM."""

from __future__ import annotations
import os
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional
import time
import httpx
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


def _read_build_commit() -> str:
    """Read the git commit hash baked into the Docker image at build time."""
    try:
        return Path("/app/GIT_COMMIT").read_text().strip()
    except FileNotFoundError:
        return "unknown"


_remote_cache: dict[str, str | float | None] = {"sha": None, "ts": 0.0}


async def _fetch_remote_commit() -> str:
    """Fetch the latest commit SHA from GitHub (cached for 5 minutes).

    Uses the public GitHub API — no token required for public repos.
    Returns the short (7-char) SHA or ``"unknown"`` on failure.
    """
    github_repo = os.getenv("GITHUB_REPOSITORY", "Azure/sap-automation-qa")
    github_branch = os.getenv("GITHUB_BRANCH", "main")
    github_api = f"https://api.github.com/repos/{github_repo}/commits/{github_branch}"
    cache_ttl = 300

    now = time.monotonic()
    cached_sha = _remote_cache.get("sha")
    cached_ts = float(_remote_cache.get("ts") or 0)
    if cached_sha and (now - cached_ts) < cache_ttl:
        return str(cached_sha)

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(
                github_api,
                headers={"Accept": "application/vnd.github.v3+json"},
            )
            if resp.status_code == 200:
                sha = resp.json().get("sha", "")[:7]
                _remote_cache["sha"] = sha
                _remote_cache["ts"] = now
                return sha
    except Exception:
        logger.debug("GitHub commit check failed", exc_info=True)
    return str(_remote_cache.get("sha") or "unknown")


@router.get("/api/v1/version")
async def get_version() -> dict:
    """Return running version and whether an update is available.

    Compares the build-time commit hash against the latest commit
    on the ``Azure/sap-automation-qa`` GitHub repository.
    """
    build_commit = _read_build_commit()
    latest_commit = await _fetch_remote_commit()
    update_available = (
        build_commit != "unknown" and latest_commit != "unknown" and build_commit != latest_commit
    )
    return {
        "version": "1.0.0",
        "build_commit": build_commit,
        "latest_commit": latest_commit,
        "update_available": update_available,
    }
