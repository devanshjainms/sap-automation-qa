# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
SAP STAF MCP server — built on the official MCP Python SDK.
"""

from __future__ import annotations
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse
from src.core.execution.command_allow_list import CommandAllowList
from src.core.execution.evidence_collector import EvidenceCollector
from src.core.execution.ssh_provider import SshCredentialProvider
from src.core.execution.ssh_cache import SshCredentialCache
from src.core.execution.triage_executor import ArtifactWriter, TriageExecutor
from src.core.execution.worker import JobWorker
from src.core.execution.executor import AnsibleExecutor
from src.core.knowledge.base import KnowledgeBase
from src.core.knowledge.retrieval import HybridRetriever
from src.core.services.embedding import LocalEmbeddingProvider
from src.core.services.workspace_backend import create_workspace_config_loader
from src.core.services.workspace_discovery import get_workspace_backend
from src.mcp_server.ttl_dict import TtlDict
from src.core.services.scheduler import SchedulerService
from src.core.storage.factory import create_job_store, create_schedule_store
from src.mcp_server.auth import create_token_verifier
from src.mcp_server.validation import InputValidator
from src.core.execution.workspace_lock import WorkspaceLockManager
from src.core.execution.ssh_collector import SshCollectorStrategy
from src.core.models.evidence import CollectorType
from src.core.observability import initialize_logging, get_logger

_LOG_FORMAT = os.environ.get("LOG_FORMAT", "json")
_LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
initialize_logging(
    level=getattr(logging, _LOG_LEVEL.upper(), logging.INFO),
    log_format=_LOG_FORMAT,
)
logger = get_logger(__name__)


MCP_PORT = int(os.environ.get("MCP_PORT", "8001"))


MCP_HOST = os.environ.get("MCP_HOST", "0.0.0.0")
DATA_DIR = Path(os.environ.get("DATA_DIR", "data"))
WORKSPACES_BASE = Path(os.environ.get("WORKSPACES_BASE", "WORKSPACES/SYSTEM"))
PLAYBOOK_DIR = Path(os.environ.get("PLAYBOOK_DIR", "src"))
SEED_DIR = Path(
    os.environ.get(
        "KNOWLEDGE_SEED_DIR",
        str(Path(__file__).resolve().parent.parent / "core" / "knowledge" / "seed"),
    )
)


@dataclass
class SapContext:
    """Shared application context injected via ``FastMCP`` lifespan.

    Access inside tools with ``ctx.request_context.lifespan_context``.
    """

    job_store: Any
    job_worker: JobWorker
    knowledge_store: KnowledgeBase
    schedule_store: Any
    scheduler_service: SchedulerService | None
    triage_executor: TriageExecutor
    triage_sessions: TtlDict
    workspaces_base: Path
    ssh_provider: SshCredentialProvider
    ssh_cache: SshCredentialCache
    validator: InputValidator
    retriever: HybridRetriever
    workspace_lock: WorkspaceLockManager


_shared_context: SapContext | None = None


def get_sap_context() -> SapContext | None:
    """Return the shared ``SapContext`` if initialized, else ``None``.

    This accessor is safe to call from any module in the same process.
    The context is lazily created during the MCP server lifespan.
    """
    return _shared_context


def _check_startup_dependencies() -> None:
    """Test Azure connectivity at startup and log clear messages."""
    checks = []

    blob_url = os.environ.get("BLOB_ACCOUNT_URL", "").strip()
    if blob_url:
        try:
            from azure.storage.blob import BlobServiceClient
            from azure.identity import DefaultAzureCredential

            client = BlobServiceClient(blob_url, credential=DefaultAzureCredential())
            client.get_account_information()
            checks.append(("Azure Blob Storage", "OK"))
        except Exception as exc:
            checks.append(("Azure Blob Storage", f"FAILED: {exc}"))
            logger.error(
                "Azure Blob Storage connectivity failed: %s. "
                "Check managed identity has 'Storage Blob Data Contributor' role "
                "on %s",
                exc,
                blob_url,
            )

    table_url = os.environ.get("AZURE_TABLE_ENDPOINT", "").strip()
    if table_url:
        try:
            from azure.data.tables import TableServiceClient
            from azure.identity import DefaultAzureCredential

            client = TableServiceClient(
                endpoint=table_url,
                credential=DefaultAzureCredential(),
            )
            list(client.list_tables())
            checks.append(("Azure Table Storage", "OK"))
        except Exception as exc:
            checks.append(("Azure Table Storage", f"FAILED: {exc}"))
            logger.error(
                "Azure Table Storage connectivity failed: %s. "
                "Check managed identity has 'Storage Table Data Contributor' role "
                "on %s",
                exc,
                table_url,
            )

    if not WORKSPACES_BASE.exists() and not blob_url:
        checks.append(("Workspaces", f"FAILED: {WORKSPACES_BASE} not found"))
        logger.error(
            "Workspace directory %s not found and BLOB_ACCOUNT_URL not set. "
            "Workspace tools will return empty results.",
            WORKSPACES_BASE,
        )
    else:
        checks.append(("Workspaces", "OK"))

    for name, status in checks:
        logger.info("Startup check: %-25s %s", name, status)


def _init_shared_context() -> SapContext:
    """Build the shared SapContext once (called at import time)."""
    logger.info("MCP server starting — initializing services...")
    _check_startup_dependencies()

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    artifact_dir = DATA_DIR / "artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)

    job_store = create_job_store(DATA_DIR)
    schedule_store = create_schedule_store(DATA_DIR)

    knowledge_base = KnowledgeBase(seed_dir=SEED_DIR)

    embedding_model = os.environ.get("EMBEDDING_MODEL", "microsoft/harrier-oss-v1-270m")
    try:
        embedding_provider = LocalEmbeddingProvider(model_name=embedding_model)
        logger.info("Embedding provider: sentence-transformers (%s)", embedding_model)
    except Exception:
        logger.warning("Embedding provider init failed; using keyword fallback", exc_info=True)
        embedding_provider = None

    retriever = HybridRetriever(
        store=knowledge_base,
        embedding_provider=embedding_provider,
    )
    triage_sessions: TtlDict = TtlDict(ttl_seconds=3600, max_size=100)

    evidence_collector = EvidenceCollector(allow_list=CommandAllowList.default())
    evidence_collector.register_strategy(CollectorType.SSH, SshCollectorStrategy())

    ssh_provider = SshCredentialProvider(workspaces_base=WORKSPACES_BASE)

    executor = AnsibleExecutor(playbook_dir=PLAYBOOK_DIR)
    workspace_config_loader = create_workspace_config_loader(get_workspace_backend)
    job_worker = JobWorker(
        job_store=job_store,
        executor=executor,
        workspace_config_loader=workspace_config_loader,
        workspaces_base=WORKSPACES_BASE,
        ssh_provider=ssh_provider,
    )

    ctx = SapContext(
        job_store=job_store,
        job_worker=job_worker,
        knowledge_store=knowledge_base,
        schedule_store=schedule_store,
        scheduler_service=None,
        triage_executor=TriageExecutor(
            collector=evidence_collector,
            artifact_writer=ArtifactWriter(base_dir=artifact_dir),
        ),
        triage_sessions=triage_sessions,
        workspaces_base=WORKSPACES_BASE,
        ssh_provider=ssh_provider,
        ssh_cache=SshCredentialCache(ssh_provider),
        validator=InputValidator(
            workspaces_base=WORKSPACES_BASE,
            sessions=triage_sessions,
            job_store=job_store,
        ),
        retriever=retriever,
        workspace_lock=WorkspaceLockManager(),
    )
    logger.info("MCP server initialized successfully")
    return ctx


@asynccontextmanager
async def sap_lifespan(server: FastMCP) -> AsyncIterator[SapContext]:
    """Initialize shared services on startup, yield context per request.

    In ``stateless_http=True`` mode the MCP SDK calls the lifespan
    **once per HTTP request**, so we cache the ``SapContext`` in the
    module-level ``_shared_context`` to ensure triage sessions, SSH
    caches, and knowledge stores are shared across tool calls.

    :param server: The ``FastMCP`` server instance.
    :yields: The shared :class:`SapContext`.
    """
    global _shared_context
    if _shared_context is None:
        _shared_context = _init_shared_context()
        src.mcp_server.resources.set_sap_context(_shared_context)
    yield _shared_context


_token_verifier = create_token_verifier()

if _token_verifier is not None:
    logger.info("MCP auth enabled (mode: %s)", os.environ.get("MCP_AUTH_MODE", "none"))

mcp = FastMCP(
    "SAP STAF",
    instructions=(
        "SAP Testing Automation Framework MCP server. "
        "Provides tools for HA triage (collect evidence → analyze → report) "
        "and STAF test execution (run test → poll status → get results). "
        "Use list_workspaces to discover available SAP systems."
    ),
    lifespan=sap_lifespan,
    stateless_http=False,
    json_response=False,
    host=MCP_HOST,
    port=MCP_PORT,
)

import src.mcp_server.tools  # noqa: E402, F401
import src.mcp_server.resources  # noqa: E402
import src.mcp_server.prompts  # noqa: E402

_mcp_asgi = mcp.streamable_http_app()


_HEALTH_PATHS = {"/healthz", "/health", "/ready"}


def _create_auth_middleware(app, verifier):
    """Wrap ASGI app with bearer token authentication."""

    async def middleware(scope, receive, send):
        if scope["type"] == "http":
            request = Request(scope, receive)
            auth_header = request.headers.get("authorization", "")
            if auth_header.startswith("Bearer "):
                token = auth_header[7:]
            else:
                token = ""
            result = await verifier.verify_token(token)
            if result is None:
                response = JSONResponse(
                    {"error": "invalid_token", "error_description": "Authentication required"},
                    status_code=401,
                )
                await response(scope, receive, send)
                return
        await app(scope, receive, send)

    return middleware


if _token_verifier is not None:
    _mcp_asgi = _create_auth_middleware(_mcp_asgi, _token_verifier)

http_app = _mcp_asgi


if __name__ == "__main__":
    transport: Any = os.environ.get("MCP_TRANSPORT", "streamable-http")
    mcp.run(transport=transport)
