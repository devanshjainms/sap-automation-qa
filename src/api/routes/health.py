# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Health and status API routes."""

import os

from fastapi import APIRouter

from src.agents.models import DebugEnvResponse, HealthResponse, StatusResponse

router = APIRouter(tags=["health"])


@router.get("/", response_model=StatusResponse)
async def root() -> StatusResponse:
    """Root endpoint returning status."""
    return StatusResponse(status="ok")


@router.get("/healthz", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Health check endpoint."""
    return HealthResponse(status="healthy")


@router.get("/debug/env", response_model=DebugEnvResponse)
async def debug_env() -> DebugEnvResponse:
    """Debug endpoint to check environment variables."""
    return DebugEnvResponse(
        AZURE_OPENAI_ENDPOINT=os.getenv("AZURE_OPENAI_ENDPOINT", "NOT SET"),
        AZURE_OPENAI_DEPLOYMENT=os.getenv("AZURE_OPENAI_DEPLOYMENT", "NOT SET"),
        AZURE_OPENAI_API_KEY="***" if os.getenv("AZURE_OPENAI_API_KEY") else "NOT SET",
    )
