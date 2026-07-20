# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Models for MCP Core API responses
"""

from pydantic import BaseModel
from src.core.models.job import (
    JobEvent,
)

DEFAULT_CORE_API_URL = "http://localhost:8000"


class CancelJobResult(BaseModel):
    """Minimal result of a job cancellation request."""

    status: str
    job_id: str


class JobEventsResponse(BaseModel):
    """Events recorded for a job, as returned by ``GET /jobs/{job_id}/events``."""

    job_id: str
    events: list[JobEvent]
