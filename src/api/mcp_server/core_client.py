# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Typed HTTP adapter from FastMCP to the FastAPI job routes (RD-021/CON-011).
"""

import os
from typing import Any, Optional, Type, TypeVar
import httpx
from pydantic import BaseModel, ValidationError
from src.core.models.job import (
    CancelJobRequest,
    CreateJobRequest,
    Job,
    JobListResponse,
)
from src.core.models.mcp import CancelJobResult, JobEventsResponse
from src.api.mcp_server.errors import CoreApiError, CoreApiUnavailableError

DEFAULT_CORE_API_URL = "http://localhost:8000"
_JOBS_PATH = "/api/v1/jobs"
_DETAIL_MAX_LENGTH = 500

_ModelT = TypeVar("_ModelT", bound=BaseModel)


class CoreApiClient:
    """
    Typed async HTTP adapter over the FastAPI job routes.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        *,
        client: Optional[httpx.AsyncClient] = None,
        timeout: float = 10.0,
    ) -> None:
        """Create the adapter.

        :param base_url: Base URL of the Core API. Defaults to the
            ``CORE_API_URL`` environment variable, or
            :data:`DEFAULT_CORE_API_URL` if that variable is unset. A
            trailing slash is stripped. Ignored when ``client`` is supplied,
            since the injected client owns its own base URL.
        :type base_url: Optional[str]
        :param client: Pre-configured ``httpx.AsyncClient`` to use, e.g. for
            tests. When supplied, this adapter never closes it.
        :type client: Optional[httpx.AsyncClient]
        :param timeout: Request timeout in seconds, applied only when this
            adapter creates its own client.
        :type timeout: float
        """
        self._owns_client = client is None
        if client is not None:
            self._client = client
        else:
            resolved_base_url = (
                base_url or os.environ.get("CORE_API_URL", DEFAULT_CORE_API_URL)
            ).rstrip("/")
            self._client = httpx.AsyncClient(base_url=resolved_base_url, timeout=timeout)

    async def aclose(self) -> None:
        """Close the underlying HTTP client, but only if this adapter created it."""
        if self._owns_client:
            await self._client.aclose()

    async def submit_job(self, request: CreateJobRequest) -> Job:
        """Submit a new job (``POST /jobs``).

        :param request: Job creation request.
        :type request: CreateJobRequest
        :return: The created job.
        :rtype: Job
        :raises CoreApiError: If the Core API rejects the request or returns
            a malformed success payload.
        :raises CoreApiUnavailableError: If the Core API cannot be reached.
        """
        response = await self._request("POST", _JOBS_PATH, json=request.model_dump(mode="json"))
        return self._parse_model(response, Job)

    async def get_job(self, job_id: str) -> Job:
        """Get a job by ID (``GET /jobs/{job_id}``).

        :param job_id: Unique identifier of the job.
        :type job_id: str
        :return: The requested job.
        :rtype: Job
        :raises CoreApiError: If the job is not found or the Core API
            returns a malformed success payload.
        :raises CoreApiUnavailableError: If the Core API cannot be reached.
        """
        response = await self._request("GET", f"{_JOBS_PATH}/{job_id}")
        return self._parse_model(response, Job)

    async def list_jobs(
        self,
        workspace_id: Optional[str] = None,
        status: Optional[str] = None,
        active_only: bool = False,
        limit: int = 50,
    ) -> JobListResponse:
        """List jobs (``GET /jobs``).

        :param workspace_id: Filter jobs by workspace ID.
        :type workspace_id: Optional[str]
        :param status: Filter jobs by status.
        :type status: Optional[str]
        :param active_only: If ``True``, only return active (non-terminal) jobs.
        :type active_only: bool
        :param limit: Maximum number of jobs to return.
        :type limit: int
        :return: Response containing the list of jobs and total count.
        :rtype: JobListResponse
        :raises CoreApiError: If the Core API rejects the request or returns
            a malformed success payload.
        :raises CoreApiUnavailableError: If the Core API cannot be reached.
        """
        params: dict[str, object] = {"active_only": active_only, "limit": limit}
        if workspace_id is not None:
            params["workspace_id"] = workspace_id
        if status is not None:
            params["status"] = status
        response = await self._request("GET", _JOBS_PATH, params=params)
        return self._parse_model(response, JobListResponse)

    async def cancel_job(self, job_id: str, reason: str = "Cancelled by user") -> CancelJobResult:
        """Cancel a running job (``POST /jobs/{job_id}/cancel``).

        :param job_id: ID of the job to cancel.
        :type job_id: str
        :param reason: Human-readable cancellation reason.
        :type reason: str
        :return: Minimal cancellation result.
        :rtype: CancelJobResult
        :raises CoreApiError: If the job is not found/not running, or the
            Core API returns a malformed success payload.
        :raises CoreApiUnavailableError: If the Core API cannot be reached.
        """
        request = CancelJobRequest(reason=reason)
        response = await self._request(
            "POST",
            f"{_JOBS_PATH}/{job_id}/cancel",
            json=request.model_dump(mode="json"),
        )
        return self._parse_model(response, CancelJobResult)

    async def get_job_events(self, job_id: str) -> JobEventsResponse:
        """Get the events recorded for a job (``GET /jobs/{job_id}/events``).

        :param job_id: Identifier of the job.
        :type job_id: str
        :return: Job ID and its recorded events.
        :rtype: JobEventsResponse
        :raises CoreApiError: If the job is not found or the Core API
            returns a malformed success payload.
        :raises CoreApiUnavailableError: If the Core API cannot be reached.
        """
        response = await self._request("GET", f"{_JOBS_PATH}/{job_id}/events")
        return self._parse_model(response, JobEventsResponse)

    async def get_job_log(self, job_id: str, tail: Optional[int] = None) -> str:
        """Get the Ansible process log for a job (``GET /jobs/{job_id}/log``).

        :param job_id: ID of the job.
        :type job_id: str
        :param tail: If given, return only the last N lines.
        :type tail: Optional[int]
        :return: Plain-text log content.
        :rtype: str
        :raises CoreApiError: If the job or log file is not found.
        :raises CoreApiUnavailableError: If the Core API cannot be reached.
        """
        params = {"tail": tail} if tail is not None else None
        response = await self._request("GET", f"{_JOBS_PATH}/{job_id}/log", params=params)
        return response.text

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        """Send a request, mapping transport failures and non-2xx responses.

        :param method: HTTP method, e.g. ``"GET"``.
        :type method: str
        :param path: Request path relative to the client's base URL.
        :type path: str
        :param kwargs: Extra arguments forwarded to ``httpx.AsyncClient.request``.
        :type kwargs: Any
        :return: The successful (2xx) HTTP response.
        :rtype: httpx.Response
        :raises CoreApiError: If the response status is not 2xx.
        :raises CoreApiUnavailableError: If a connection or timeout failure occurs.
        """
        try:
            response = await self._client.request(method, path, **kwargs)
        except httpx.TransportError as exc:
            raise CoreApiUnavailableError(f"{method} {path} failed: {exc}") from exc
        if not response.is_success:
            raise CoreApiError(
                status_code=response.status_code,
                detail=self._extract_detail(response),
            )
        return response

    @staticmethod
    def _extract_detail(response: httpx.Response) -> str:
        """Extract a bounded, sanitized error detail from a non-2xx response.

        :param response: Non-2xx HTTP response.
        :type response: httpx.Response
        :return: Error detail truncated to :data:`_DETAIL_MAX_LENGTH` characters.
        :rtype: str
        """
        try:
            payload = response.json()
        except ValueError:
            text = response.text or response.reason_phrase
            return text[:_DETAIL_MAX_LENGTH]
        if isinstance(payload, dict) and isinstance(payload.get("detail"), str):
            return payload["detail"][:_DETAIL_MAX_LENGTH]
        return str(payload)[:_DETAIL_MAX_LENGTH]

    @staticmethod
    def _parse_model(response: httpx.Response, model: Type[_ModelT]) -> _ModelT:
        """Parse a successful response body into a Pydantic model.

        :param response: Successful (2xx) HTTP response.
        :type response: httpx.Response
        :param model: Pydantic model type to validate the payload against.
        :type model: Type[_ModelT]
        :return: The validated model instance.
        :rtype: _ModelT
        :raises CoreApiError: If the payload is not valid JSON or does not
            match ``model``.
        """
        try:
            payload = response.json()
            return model.model_validate(payload)
        except (ValueError, ValidationError) as exc:
            raise CoreApiError(
                status_code=response.status_code,
                detail=f"Malformed response from Core API: {exc}",
            ) from exc
