# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""FastAPI application with health check endpoints."""

import logging
from fastapi import FastAPI
import uvicorn

from src.agents.models.chat import ChatRequest, ChatResponse
from src.agents.agents.base import create_default_agent_registry
from src.agents.agents.orchestrator import OrchestratorSK
from src.agents.sk_kernel import create_kernel
from src.agents.logging_config import initialize_logging, get_logger, set_correlation_id

initialize_logging(level=logging.INFO)

logger = get_logger(__name__)
kernel = create_kernel()
agent_registry = create_default_agent_registry()
orchestrator = OrchestratorSK(registry=agent_registry, kernel=kernel)

app = FastAPI()


@app.get("/")
async def root():
    """Root endpoint returning status."""
    return {"status": "ok"}


@app.get("/healthz")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


@app.get("/agents")
async def list_agents():
    """List available agents and their descriptions."""
    agents = agent_registry.list_agents()
    return {"agents": agents}


@app.get("/debug/env")
async def debug_env():
    """Debug endpoint to check environment variables."""
    import os

    return {
        "AZURE_OPENAI_ENDPOINT": os.getenv("AZURE_OPENAI_ENDPOINT", "NOT SET"),
        "AZURE_OPENAI_DEPLOYMENT": os.getenv("AZURE_OPENAI_DEPLOYMENT", "NOT SET"),
        "AZURE_OPENAI_API_KEY": "***" if os.getenv("AZURE_OPENAI_API_KEY") else "NOT SET",
    }


@app.post("/chat")
async def chat(request: ChatRequest) -> ChatResponse:
    """Chat endpoint that routes to appropriate agent via orchestrator."""
    correlation_id = set_correlation_id(request.correlation_id)

    logger.info(f"Received chat request with {len(request.messages)} messages")
    response = await orchestrator.handle_chat(request, context={})
    logger.info(f"Returning response with {len(response.messages)} messages")
    response.correlation_id = correlation_id
    return response


if __name__ == "__main__":
    uvicorn.run("src.api.app:app", host="0.0.0.0", port=8000, reload=True)
