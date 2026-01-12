# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""FastAPI application with agent orchestration and conversation persistence."""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from src.agents.agents.base import create_default_agent_registry
from src.agents.agents.orchestrator import OrchestratorSK
from src.agents.sk_kernel import create_kernel
from src.agents.observability import (
    initialize_logging,
    get_logger,
    add_observability_middleware,
)
from src.agents.persistence import ConversationManager
from src.agents.execution import JobStore
from src.agents.execution.worker import JobWorker
from src.api.routes import (
    agents_router,
    chat_router,
    conversations_router,
    health_router,
    streaming_router,
    workspaces_router,
    set_agent_registry,
    set_chat_conversation_manager,
    set_chat_kernel,
    set_conversation_manager,
    set_job_worker,
    set_orchestrator,
)

log_format = os.environ.get("LOG_FORMAT", "json")
initialize_logging(level=logging.INFO, log_format=log_format)

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan manager for startup/shutdown."""
    logger.info("Initializing application...")

    kernel = None
    try:
        kernel = create_kernel()
    except ValueError as e:
        logger.error(
            "Azure OpenAI is not configured; AI chat endpoints will be unavailable.",
            extra={"error": str(e)},
        )

    agent_registry = None
    orchestrator = None
    if kernel is not None:
        agent_registry = create_default_agent_registry(kernel=kernel)
        orchestrator = OrchestratorSK(registry=agent_registry, kernel=kernel)

    db_path = Path("data/sap_qa.db")
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conversation_manager = ConversationManager(db_path=db_path)

    from src.agents.agents.action_executor_agent import ActionExecutorAgent

    job_store: JobStore | None = None
    job_worker: JobWorker | None = None

    action_executor_base = agent_registry.get("action_executor") if agent_registry else None
    if action_executor_base and isinstance(action_executor_base, ActionExecutorAgent):
        action_executor: ActionExecutorAgent = action_executor_base
        job_store = JobStore(db_path=db_path)
        job_worker = JobWorker(
            job_store=job_store, execution_plugin=action_executor.execution_plugin
        )

        object.__setattr__(action_executor, "job_store", job_store)
        object.__setattr__(action_executor, "job_worker", job_worker)
        object.__setattr__(action_executor, "_async_enabled", True)
        # guard_layer may be a normal object; set its job_store safely
        try:
            object.__setattr__(action_executor.guard_layer, "job_store", job_store)
        except Exception:
            # Fallback to direct assignment if guard_layer is not pydantic-managed
            action_executor.guard_layer.job_store = job_store
    else:
        logger.warning("Action executor not found - async job execution disabled")

    if agent_registry is not None:
        set_agent_registry(agent_registry)
    if orchestrator is not None:
        set_orchestrator(orchestrator)
    set_conversation_manager(conversation_manager)
    set_chat_conversation_manager(conversation_manager)
    set_chat_kernel(kernel)
    if job_worker:
        set_job_worker(job_worker)

    logger.info("Application initialized successfully")

    yield

    logger.info("Shutting down application...")

    if job_store:
        job_store.close()
    conversation_manager.close()
    logger.info("Application shutdown complete")


app = FastAPI(
    title="SAP QA Agent API",
    description="REST API for SAP Testing Automation Framework with AI agents",
    version="1.0.0",
    lifespan=lifespan,
)
add_observability_middleware(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3001",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(agents_router)
app.include_router(chat_router)
app.include_router(conversations_router)
app.include_router(streaming_router)
app.include_router(workspaces_router)


if __name__ == "__main__":
    uvicorn.run("src.api.app:app", host="0.0.0.0", port=8000, reload=True)
