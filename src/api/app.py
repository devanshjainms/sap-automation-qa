# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
FastAPI application for SAP QA Scheduler.
"""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.staticfiles import StaticFiles
from src.agents.ag_ui import register_ag_ui
from src.core.observability import (
    initialize_logging,
    get_logger,
    ObservabilityMiddleware,
    load_telemetry_config,
)
from src.core.execution.executor import AnsibleExecutor
from src.core.execution.worker import JobWorker
from src.core.services.scheduler import SchedulerService
from src.api.routes import (
    health_router,
    jobs_router,
    schedules_router,
    workspaces_router,
    chat_router,
    set_job_store,
    set_job_worker,
    set_schedule_store,
    set_scheduler_service,
    set_workspace_loader,
    set_conversation_store,
)
from src.api.routes.health import set_service_status, set_health_service
from src.api.auth import (
    AuthMiddleware,
    create_auth_provider,
    get_public_paths,
)
from src.core.services.health import HealthService
from src.api.routes.workspaces import default_workspace_loader
from src.core.storage.staf_store import StafStore
from src.core.knowledge.retrieval import HybridRetriever
from src.core.services.mcp_config_loader import load_mcp_servers_config
from src.mcp_server.server import get_sap_context
from src.agents.agent import SapAgentFactory

API_V1_PREFIX = "/api/v1"
LOG_FORMAT = os.environ.get("LOG_FORMAT", "console")
DATA_DIR = Path(os.environ.get("DATA_DIR", "data"))
WORKSPACES_BASE = Path(os.environ.get("WORKSPACES_BASE", "WORKSPACES/SYSTEM"))
PLAYBOOK_DIR = Path(os.environ.get("PLAYBOOK_DIR", "src"))
SCHEDULER_CHECK_INTERVAL = int(os.environ.get("SCHEDULER_CHECK_INTERVAL", "60"))
CORS_ORIGINS = os.environ.get(
    "CORS_ORIGINS",
    "http://localhost:3000,http://localhost:5173,http://localhost:8000",
).split(",")

AZURE_OPENAI_ENDPOINT = os.environ.get("AZURE_OPENAI_ENDPOINT", "")
AZURE_OPENAI_DEPLOYMENT = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "")
AZURE_OPENAI_API_KEY = os.environ.get("AZURE_OPENAI_API_KEY", "")
AZURE_OPENAI_API_VERSION = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")
STAF_MCP_URL = os.environ.get("STAF_MCP_URL", "http://localhost:8001")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "")
AZURE_MCP_URL = os.environ.get("AZURE_MCP_URL", "")

telemetry_config = load_telemetry_config()
initialize_logging(
    level=logging.INFO,
    log_format=LOG_FORMAT,
    telemetry_config=telemetry_config,
)
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Application lifespan manager for startup/shutdown.

    :param app: FastAPI application instance.
    :type app: FastAPI
    :yields: None
    """
    scheduler_service = None
    job_worker = None
    agent_factory = None
    staf_db = None

    try:
        logger.info("Initializing SAP QA Scheduler...")
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        staf_db = StafStore(DATA_DIR / "staf.db")
        staf_db.init_all()

        workspace_loader = default_workspace_loader
        set_workspace_loader(workspace_loader)
        job_worker = JobWorker(
            job_store=staf_db.jobs,
            executor=AnsibleExecutor(
                playbook_dir=PLAYBOOK_DIR,
                telemetry_config=telemetry_config,
            ),
            workspace_config_loader=workspace_loader,
            workspaces_base=WORKSPACES_BASE,
        )
        job_worker.recover_crashed_jobs()
        scheduler_service = SchedulerService(
            schedule_store=staf_db.schedules,
            job_worker=job_worker,
            check_interval_seconds=SCHEDULER_CHECK_INTERVAL,
        )
        app.state.job_store = staf_db.jobs
        app.state.schedule_store = staf_db.schedules
        app.state.job_worker = job_worker
        app.state.scheduler_service = scheduler_service
        set_job_store(staf_db.jobs)
        set_job_worker(job_worker)
        set_schedule_store(staf_db.schedules)
        set_scheduler_service(scheduler_service)

        set_conversation_store(staf_db.conversations)
        if AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_DEPLOYMENT:
            try:
                agent_factory = await SapAgentFactory.create(
                    mcp_url=STAF_MCP_URL.rstrip("/") + "/mcp",
                    mcp_config=load_mcp_servers_config(),
                    conversation_store=staf_db.conversations,
                    retriever=HybridRetriever(
                        store=staf_db.knowledge, embedding_store=staf_db.embeddings
                    ),
                    sap_context=get_sap_context(),
                    endpoint=AZURE_OPENAI_ENDPOINT,
                    deployment_name=AZURE_OPENAI_DEPLOYMENT,
                    api_key=AZURE_OPENAI_API_KEY or None,
                    api_version=AZURE_OPENAI_API_VERSION,
                )
                logger.info("Agent factory initialized")
                try:
                    register_ag_ui(
                        app,
                        agent_factory,
                        "/ag-ui",
                        allow_origins=CORS_ORIGINS,
                        conversation_store=staf_db.conversations,
                    )
                except Exception:
                    logger.warning(
                        "Failed to register AG-UI endpoint",
                        exc_info=True,
                    )
            except BaseException:
                logger.warning(
                    "Failed to initialize agent chat service — "
                    "chat will return placeholder responses",
                    exc_info=True,
                )
        else:
            logger.info(
                "AZURE_OPENAI_ENDPOINT / AZURE_OPENAI_DEPLOYMENT not set — " "chat service disabled"
            )
        mcp_urls: dict[str, str] = {}
        if STAF_MCP_URL:
            mcp_urls["staf-mcp"] = STAF_MCP_URL
        set_health_service(
            HealthService(
                mcp_urls=mcp_urls,
                llm_endpoint=AZURE_OPENAI_ENDPOINT,
                llm_deployment=AZURE_OPENAI_DEPLOYMENT,
                llm_api_key=AZURE_OPENAI_API_KEY,
                llm_api_version=AZURE_OPENAI_API_VERSION,
                ollama_url=OLLAMA_URL,
                azure_mcp_url=AZURE_MCP_URL,
            )
        )

        await scheduler_service.start()
        set_service_status("scheduler", True)
        logger.info("SAP QA Scheduler initialized successfully")
        yield

    except Exception as e:
        logger.error(f"Failed to initialize SAP QA Scheduler: {e}", exc_info=True)
        raise

    finally:
        logger.info("Shutting down SAP QA Scheduler...")
        set_service_status("scheduler", False)
        set_health_service(None)
        if scheduler_service:
            await scheduler_service.stop()
        if agent_factory:
            await agent_factory.close()
        if job_worker:
            await job_worker.shutdown()
        if staf_db:
            staf_db.close()
        logger.info("SAP QA Scheduler shutdown complete")


app = FastAPI(
    title="SAP QA Scheduler API",
    description="REST API for SAP Testing Automation Service",
    version="1.0.0",
    lifespan=lifespan,
)
app.add_middleware(ObservabilityMiddleware)
try:
    _auth_provider = create_auth_provider()
    app.add_middleware(
        AuthMiddleware,
        auth_provider=_auth_provider,
        public_paths=get_public_paths(),
    )
    logger.info("Azure AD authentication enabled")
except ValueError as _auth_err:
    logger.error("Auth initialization failed: %s", _auth_err)
    raise

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "X-Correlation-ID"],
)
app.include_router(health_router)
app.include_router(jobs_router, prefix=API_V1_PREFIX)
app.include_router(schedules_router, prefix=API_V1_PREFIX)
app.include_router(workspaces_router, prefix=API_V1_PREFIX)
app.include_router(chat_router, prefix=API_V1_PREFIX)


@app.get("/auth/config")
async def auth_config() -> dict:
    """Return auth configuration for frontend clients.

    This endpoint is public (no auth required) and returns only
    non-sensitive configuration needed by the frontend to acquire tokens.

    :returns: Auth configuration dictionary.
    :rtype: dict
    """
    client_id = os.environ.get("AZURE_CLIENT_ID", "")
    api_scope = os.environ.get("AZURE_API_SCOPE", "")
    if not api_scope and client_id:
        api_scope = f"api://{client_id}/access_as_user"
    scopes = [api_scope] if api_scope else []
    return {
        "tenant_id": os.environ.get("AZURE_TENANT_ID", ""),
        "client_id": client_id,
        "authority": f"https://login.microsoftonline.com/"
        f"{os.environ.get('AZURE_TENANT_ID', '')}",
        "scopes": scopes,
    }


_static_dir = Path(__file__).resolve().parent.parent.parent / "static"
if _static_dir.is_dir():
    app.mount("/", StaticFiles(directory=str(_static_dir), html=True), name="static")
