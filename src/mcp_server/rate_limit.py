# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Per-client token-bucket rate limiter for MCP requests.

Configuration via environment variables:

- ``MCP_RATE_LIMIT_RPM``: Requests per minute (default: 60).
- ``MCP_RATE_LIMIT_BURST``: Burst size (default: 10).
"""

from __future__ import annotations
import logging
import time
from dataclasses import dataclass, field
from typing import Callable
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = logging.getLogger(__name__)


@dataclass
class _TokenBucket:
    """Simple token-bucket rate limiter.

    :param rate: Tokens added per second.
    :param burst: Maximum tokens (bucket size).
    """

    rate: float
    burst: int
    tokens: float = field(init=False)
    last_refill: float = field(init=False)

    def __post_init__(self) -> None:
        self.tokens = float(self.burst)
        self.last_refill = time.monotonic()

    def consume(self) -> bool:
        """Try to consume one token.

        :returns: True if a token was available, False if rate-limited.
        """
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.burst, self.tokens + elapsed * self.rate)
        self.last_refill = now

        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return True
        return False

    @property
    def retry_after(self) -> float:
        """Seconds until a token becomes available."""
        if self.tokens >= 1.0:
            return 0.0
        deficit = 1.0 - self.tokens
        return deficit / self.rate if self.rate > 0 else 60.0


class McpRateLimiter(BaseHTTPMiddleware):
    """ASGI middleware for per-client rate limiting.

    :param app: The ASGI application to wrap.
    :param requests_per_minute: Default rate limit (RPM).
    :param burst: Maximum burst size.
    """

    def __init__(
        self,
        app: Callable,
        requests_per_minute: int = 60,
        burst: int = 10,
    ) -> None:
        super().__init__(app)
        self._rpm = requests_per_minute
        self._rate = requests_per_minute / 60.0
        self._burst = burst
        self._buckets: dict[str, _TokenBucket] = {}

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Check rate limit before forwarding the request."""
        client_id = getattr(
            getattr(request, "state", None),
            "client_identity",
            None,
        )
        if client_id is not None:
            key = client_id.client_id
        else:
            key = request.client.host if request.client else "unknown"

        bucket = self._buckets.get(key)
        if bucket is None:
            bucket = _TokenBucket(rate=self._rate, burst=self._burst)
            self._buckets[key] = bucket

        if not bucket.consume():
            retry_after = max(1.0, bucket.retry_after)
            logger.warning("Rate limit exceeded for client %s", key)
            return JSONResponse(
                status_code=429,
                content={
                    "status": "error",
                    "error": {
                        "code": "rate_limit_exceeded",
                        "message": (
                            f"Rate limit exceeded ({self._rpm} requests/minute). "
                            f"Retry after {retry_after:.0f} seconds."
                        ),
                        "retryable": True,
                    },
                },
                headers={"Retry-After": str(int(retry_after))},
            )

        return await call_next(request)
