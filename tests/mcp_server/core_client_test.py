# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for CoreApiClient — the typed MCP-to-API HTTP transport (RD-021/CON-011)."""

from typing import Callable, Optional
from urllib.parse import parse_qs
import httpx
import pytest
from src.api.mcp_server.core_client import CoreApiClient
from src.api.mcp_server.errors import CoreApiError
from src.core.models.job import CancelJobRequest, CreateJobRequest, Job, JobListResponse


def _sample_job_payload(job_id: str = "11111111-1111-1111-1111-111111111111") -> dict:
    """Build a minimal JSON payload matching the ``Job`` model.

    :param job_id: UUID string to use for the job's ``id`` field.
    :type job_id: str
    :return: JSON-serializable dict accepted by ``Job.model_validate``.
    :rtype: dict
    """
    return {
        "id": job_id,
        "workspace_id": "WS-01",
        "test_group": "ConfigurationChecks",
        "test_ids": [],
        "status": "pending",
        "created_at": "2026-07-20T00:00:00",
        "events": [],
        "metadata": {},
        "offline": False,
    }


def _recording_handler(
    response: httpx.Response, captured: dict
) -> Callable[[httpx.Request], httpx.Response]:
    """Build a MockTransport handler that records the request and returns ``response``.

    :param response: Fixed response returned for every request.
    :type response: httpx.Response
    :param captured: Dict populated with the request's method, path, query
        params, and body for later assertions.
    :type captured: dict
    :return: Handler suitable for ``httpx.MockTransport``.
    :rtype: Callable[[httpx.Request], httpx.Response]
    """

    def handler(request: httpx.Request) -> httpx.Response:
        """Capture the outgoing request and return the fixed response.

        :param request: Captured outgoing HTTP request.
        :type request: httpx.Request
        :return: The fixed response configured for this handler.
        :rtype: httpx.Response
        """
        captured["method"] = request.method
        captured["path"] = request.url.path
        captured["query"] = parse_qs(request.url.query.decode())
        captured["body"] = request.content
        return response

    return handler


def _client_for(
    response: httpx.Response, captured: Optional[dict] = None
) -> tuple[CoreApiClient, dict]:
    """Build a CoreApiClient backed by a MockTransport returning ``response``.

    :param response: Fixed response returned for every request made by the client.
    :type response: httpx.Response
    :param captured: Dict to populate with request details, or ``None`` to
        create a fresh one.
    :type captured: Optional[dict]
    :return: The client and the (possibly newly created) captured-request dict.
    :rtype: tuple[CoreApiClient, dict]
    """
    captured = {} if captured is None else captured
    async_client = httpx.AsyncClient(
        transport=httpx.MockTransport(_recording_handler(response, captured)),
        base_url="http://test",
    )
    return CoreApiClient(client=async_client), captured


class TestCoreApiClient:
    """Tests for CoreApiClient success paths, mapping, and lifecycle."""

    async def test_submit_job_posts_body_and_returns_job(self) -> None:
        """submit_job POSTs the request body to /api/v1/jobs and parses a Job."""
        client, captured = _client_for(httpx.Response(201, json=_sample_job_payload()))

        result = await client.submit_job(
            CreateJobRequest(workspace_id="WS-01", test_group="ConfigurationChecks")
        )

        assert isinstance(result, Job)
        assert str(result.id) == "11111111-1111-1111-1111-111111111111"
        assert captured["method"] == "POST"
        assert captured["path"] == "/api/v1/jobs"
        assert b"WS-01" in captured["body"]

    async def test_get_job_returns_job(self) -> None:
        """get_job issues GET /api/v1/jobs/{job_id} and parses a Job."""
        client, captured = _client_for(httpx.Response(200, json=_sample_job_payload()))

        result = await client.get_job("job-42")

        assert isinstance(result, Job)
        assert result.workspace_id == "WS-01"
        assert captured["method"] == "GET"
        assert captured["path"] == "/api/v1/jobs/job-42"

    async def test_list_jobs_maps_filters_to_query_params(self) -> None:
        """list_jobs maps workspace_id/status/active_only/limit to query params."""
        client, captured = _client_for(
            httpx.Response(200, json={"jobs": [_sample_job_payload()], "total": 1})
        )

        result = await client.list_jobs(
            workspace_id="WS-01", status="pending", active_only=True, limit=10
        )

        assert isinstance(result, JobListResponse)
        assert result.total == 1
        assert captured["path"] == "/api/v1/jobs"
        assert captured["query"]["workspace_id"] == ["WS-01"]
        assert captured["query"]["status"] == ["pending"]
        assert captured["query"]["active_only"] == ["true"]
        assert captured["query"]["limit"] == ["10"]

    async def test_list_jobs_omits_unset_optional_filters(self) -> None:
        """list_jobs omits workspace_id/status from the query when not provided."""
        client, captured = _client_for(httpx.Response(200, json={"jobs": [], "total": 0}))

        await client.list_jobs()

        assert "workspace_id" not in captured["query"]
        assert "status" not in captured["query"]

    async def test_cancel_job_posts_reason_and_returns_result(self) -> None:
        """cancel_job POSTs a CancelJobRequest body and returns a typed result."""
        client, captured = _client_for(
            httpx.Response(200, json={"status": "cancelled", "job_id": "job-42"})
        )

        result = await client.cancel_job("job-42", reason="Stopping test run")

        assert captured["path"] == "/api/v1/jobs/job-42/cancel"
        assert b"Stopping test run" in captured["body"]
        assert result.status == "cancelled"
        assert result.job_id == "job-42"

    async def test_cancel_job_default_reason_matches_model_default(self) -> None:
        """cancel_job without a reason sends the CancelJobRequest default reason."""
        client, captured = _client_for(
            httpx.Response(200, json={"status": "cancelled", "job_id": "job-42"})
        )

        await client.cancel_job("job-42")

        assert CancelJobRequest().reason.encode() in captured["body"]

    async def test_get_job_events_returns_typed_events(self) -> None:
        """get_job_events returns a typed model with job_id and event list."""
        client, captured = _client_for(
            httpx.Response(
                200,
                json={
                    "job_id": "job-42",
                    "events": [
                        {
                            "event_type": "created",
                            "timestamp": "2026-07-20T00:00:00",
                            "message": "Job created",
                            "data": None,
                        }
                    ],
                },
            )
        )

        result = await client.get_job_events("job-42")

        assert captured["path"] == "/api/v1/jobs/job-42/events"
        assert result.job_id == "job-42"
        assert len(result.events) == 1
        assert result.events[0].message == "Job created"

    async def test_get_job_log_returns_text_and_maps_tail(self) -> None:
        """get_job_log passes tail as a query param and returns plain text."""
        client, captured = _client_for(httpx.Response(200, text="line1\nline2\n"))

        result = await client.get_job_log("job-42", tail=5)

        assert result == "line1\nline2\n"
        assert captured["query"]["tail"] == ["5"]

    async def test_get_job_log_omits_tail_when_not_given(self) -> None:
        """get_job_log omits the tail query param when not provided."""
        client, captured = _client_for(httpx.Response(200, text="full log"))

        await client.get_job_log("job-42")

        assert "tail" not in captured["query"]

    async def test_malformed_success_payload_raises_core_api_error(self) -> None:
        """A 200 response missing required Job fields raises CoreApiError."""
        client, _ = _client_for(httpx.Response(200, json={"unexpected": "shape"}))

        with pytest.raises(CoreApiError) as exc_info:
            await client.get_job("job-42")

        assert exc_info.value.status_code == 200

    async def test_injected_client_is_not_closed_by_aclose(self) -> None:
        """aclose() never closes a caller-injected httpx.AsyncClient."""
        client, _ = _client_for(httpx.Response(200, json=_sample_job_payload()))
        async_client = client._client  # pylint: disable=protected-access

        await client.aclose()

        assert async_client.is_closed is False
        await async_client.aclose()

    async def test_internally_created_client_is_closed_by_aclose(self) -> None:
        """aclose() closes a client this adapter created itself."""
        client = CoreApiClient(base_url="http://internally-owned.example")

        await client.aclose()

        assert client._client.is_closed is True  # pylint: disable=protected-access

    def test_base_url_trailing_slash_is_normalized(self) -> None:
        """A trailing slash on an explicit base_url is stripped."""
        client = CoreApiClient(base_url="http://example.test:8000/")
        base_url = str(client._client.base_url)  # pylint: disable=protected-access

        assert base_url == "http://example.test:8000"

    def test_default_base_url_used_when_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """CORE_API_URL default matches the local uvicorn port when unset."""
        monkeypatch.delenv("CORE_API_URL", raising=False)
        client = CoreApiClient()
        base_url = str(client._client.base_url)  # pylint: disable=protected-access

        assert base_url == "http://localhost:8000"

    def test_core_api_url_env_var_used_when_base_url_not_passed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CORE_API_URL environment variable is used when base_url is omitted."""
        monkeypatch.setenv("CORE_API_URL", "http://from-env.example:9000/")
        client = CoreApiClient()
        base_url = str(client._client.base_url)  # pylint: disable=protected-access

        assert base_url == "http://from-env.example:9000"

    def test_explicit_base_url_overrides_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An explicit base_url argument takes precedence over CORE_API_URL."""
        monkeypatch.setenv("CORE_API_URL", "http://from-env.example:9000")
        client = CoreApiClient(base_url="http://explicit.example:7000")
        base_url = str(client._client.base_url)  # pylint: disable=protected-access

        assert base_url == "http://explicit.example:7000"
