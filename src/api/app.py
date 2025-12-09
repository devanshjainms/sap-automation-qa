# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""FastAPI application with agent orchestration and conversation persistence."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
import uvicorn

from src.agents.agents.base import create_default_agent_registry
from src.agents.agents.orchestrator import OrchestratorSK
from src.agents.sk_kernel import create_kernel
from src.agents.logging_config import initialize_logging, get_logger
from src.agents.persistence import ConversationManager
from src.agents.execution import JobStore, JobWorker
from src.api.routes import (
    agents_router,
    chat_router,
    conversations_router,
    health_router,
    streaming_router,
    set_agent_registry,
    set_chat_conversation_manager,
    set_conversation_manager,
    set_job_worker,
    set_orchestrator,
)

initialize_logging(level=logging.INFO)

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager for startup/shutdown."""
    logger.info("Initializing application...")

    kernel = create_kernel()
    agent_registry = create_default_agent_registry()
    orchestrator = OrchestratorSK(registry=agent_registry, kernel=kernel)

    db_path = Path("data/sap_qa.db")
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conversation_manager = ConversationManager(db_path=db_path)

    from src.agents.agents.test_executor_agent import TestExecutorAgent

    test_executor_base = agent_registry.get("test_executor")
    job_store: JobStore | None = None
    job_worker: JobWorker | None = None

    if test_executor_base and isinstance(test_executor_base, TestExecutorAgent):
        test_executor: TestExecutorAgent = test_executor_base
        job_store = JobStore(db_path=db_path)
        job_worker = JobWorker(job_store=job_store, execution_plugin=test_executor.execution_plugin)

        test_executor.job_store = job_store
        test_executor.job_worker = job_worker
        test_executor._async_enabled = True

        logger.info("Async job execution enabled")
    else:
        logger.warning("Test executor not found - async job execution disabled")

    set_agent_registry(agent_registry)
    set_orchestrator(orchestrator)
    set_conversation_manager(conversation_manager)
    set_chat_conversation_manager(conversation_manager)
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
app.include_router(health_router)
app.include_router(agents_router)
app.include_router(chat_router)
app.include_router(conversations_router)
app.include_router(streaming_router)


if __name__ == "__main__":
    uvicorn.run("src.api.app:app", host="0.0.0.0", port=8000, reload=True)
