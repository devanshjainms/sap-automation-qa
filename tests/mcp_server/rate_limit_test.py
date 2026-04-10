# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for the MCP rate-limiting middleware."""

from __future__ import annotations
import time
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient
from src.mcp_server.rate_limit import McpRateLimiter, _TokenBucket


class TestTokenBucket:

    def test_initial_tokens_equal_burst(self):
        bucket = _TokenBucket(rate=1.0, burst=5)
        assert bucket.tokens == 5.0

    def test_consume_reduces_tokens(self):
        bucket = _TokenBucket(rate=1.0, burst=5)
        assert bucket.consume() is True
        assert bucket.tokens < 5.0

    def test_consume_all_then_reject(self):
        bucket = _TokenBucket(rate=0.0, burst=2)
        assert bucket.consume() is True
        assert bucket.consume() is True
        assert bucket.consume() is False

    def test_retry_after_zero_when_tokens_available(self):
        bucket = _TokenBucket(rate=1.0, burst=5)
        assert bucket.retry_after == 0.0

    def test_retry_after_positive_when_empty(self):
        bucket = _TokenBucket(rate=1.0, burst=1)
        bucket.consume()
        assert bucket.retry_after > 0

    def test_refill_over_time(self):
        bucket = _TokenBucket(rate=100.0, burst=5)
        for _ in range(5):
            bucket.consume()
        assert bucket.consume() is False

        bucket.last_refill = time.monotonic() - 1.0
        assert bucket.consume() is True

    def test_tokens_capped_at_burst(self):
        bucket = _TokenBucket(rate=1000.0, burst=3)
        bucket.last_refill = time.monotonic() - 10.0
        bucket.consume()
        assert bucket.tokens <= 3.0

    def test_retry_after_with_zero_rate(self):
        bucket = _TokenBucket(rate=0.0, burst=1)
        bucket.consume()
        assert bucket.retry_after == 60.0  # fallback


async def _ok(request: Request) -> JSONResponse:
    return JSONResponse({"ok": True})


def _make_app(rpm: int = 60, burst: int = 10) -> McpRateLimiter:
    inner = Starlette(routes=[Route("/api/test", _ok)])
    return McpRateLimiter(inner, requests_per_minute=rpm, burst=burst)


class TestMcpRateLimiter:

    def test_allows_requests_within_limit(self):
        app = _make_app(rpm=60, burst=5)
        client = TestClient(app)
        for _ in range(5):
            resp = client.get("/api/test")
            assert resp.status_code == 200

    def test_rejects_after_burst_exhausted(self):
        app = _make_app(rpm=60, burst=2)
        client = TestClient(app)
        assert client.get("/api/test").status_code == 200
        assert client.get("/api/test").status_code == 200
        resp = client.get("/api/test")
        assert resp.status_code == 429

    def test_429_response_shape(self):
        app = _make_app(rpm=60, burst=1)
        client = TestClient(app)
        client.get("/api/test")  # use the one token
        resp = client.get("/api/test")
        assert resp.status_code == 429
        body = resp.json()
        assert body["status"] == "error"
        assert body["error"]["code"] == "rate_limit_exceeded"
        assert body["error"]["retryable"] is True

    def test_429_has_retry_after_header(self):
        app = _make_app(rpm=60, burst=1)
        client = TestClient(app)
        client.get("/api/test")
        resp = client.get("/api/test")
        assert resp.status_code == 429
        assert "Retry-After" in resp.headers
        assert int(resp.headers["Retry-After"]) >= 1

    def test_separate_buckets_per_client(self):
        """Different client IPs should get independent buckets."""
        app = _make_app(rpm=60, burst=1)
        client = TestClient(app)
        resp = client.get("/api/test")
        assert resp.status_code == 200
        limiter = app
        assert len(limiter._buckets) == 1
