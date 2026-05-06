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
from typing import Any, Callable
from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse
from src.core.formatter import ReportFormatter
from src.core.services.embedding import OpenAICompatibleEmbedding
from src.core.analyzer.analyzer import Analyzer
from src.core.execution.command_allow_list import CommandAllowList
from src.core.execution.evidence_collector import EvidenceCollector
from src.core.execution.ssh_provider import SshCredentialProvider
from src.core.execution.ssh_cache import SshCredentialCache
from src.core.execution.triage_executor import ArtifactWriter, TriageExecutor
from src.core.knowledge.learning import LearningPipeline
from src.core.knowledge.loader import JsonlLoader
from src.core.knowledge.retrieval import HybridRetriever
from src.core.models.embedding import EmbeddingProvider
from src.core.models.knowledge import EvidenceCollectorDef
from src.mcp_server.ttl_dict import TtlDict
from src.core.services.scheduler import SchedulerService
from src.core.storage.staf_store import StafStore
from src.core.storage.embedding_store import EmbeddingStore
from src.core.storage.job_store import JobStore
from src.core.storage.knowledge_graph import KnowledgeGraph
from src.core.storage.knowledge_store import KnowledgeStore
from src.core.storage.schedule_store import ScheduleStore
from src.core.models.knowledge import Playbook, Reference, Rule
from src.mcp_server.auth import create_token_verifier
from src.mcp_server.validation import InputValidator
from src.mcp_server.rate_limit import McpRateLimiter
from src.core.execution.ssh_collector import SshCollectorStrategy
from src.core.models.evidence import CollectorType

logger = logging.getLogger(__name__)


MCP_PORT = int(os.environ.get("MCP_PORT", "8001"))


def _sync_embed_seed_knowledge(
    store: KnowledgeStore,
    embedding_store: EmbeddingStore,
    provider: "EmbeddingProvider",
) -> None:
    """
    Synchronous seed embedding — safe to call at module level.
    """
    rules = store.load_rules()
    playbooks = store.load_playbooks()
    evidence_defs = store.load_evidence_definitions()
    references = store.load_references()

    to_embed: list[tuple[str, str, str]] = []
    for rule in rules:
        if not embedding_store.has(rule.id, "rule"):
            text = f"{rule.name} {rule.description} {' '.join(rule.tags)}"
            to_embed.append((rule.id, "rule", text))
    for pb in playbooks:
        if not embedding_store.has(pb.id, "playbook"):
            text = f"{pb.name} {pb.description} " f"{' '.join(pb.symptoms)} {' '.join(pb.tags)}"
            to_embed.append((pb.id, "playbook", text))
    for ed in evidence_defs:
        if not embedding_store.has(ed.id, "evidence"):
            text = f"{ed.name} {ed.description} {ed.command} {' '.join(ed.tags)}"
            to_embed.append((ed.id, "evidence", text))
    for ref in references:
        if not embedding_store.has(ref.id, "reference"):
            text = (
                f"{ref.title} {ref.summary} "
                f"{' '.join(ref.failure_classes)} {' '.join(ref.tags)}"
            )
            to_embed.append((ref.id, "reference", text))

    if not to_embed:
        return

    texts = [t[2] for t in to_embed]
    max_retries = 3
    vectors: list[list[float]] = []
    for attempt in range(1, max_retries + 1):
        try:
            vectors = provider.embed_batch(texts)
            break
        except Exception:
            if attempt < max_retries:
                import time

                logger.info(
                    "Seed embedding attempt %d/%d failed, retrying in %ds...",
                    attempt,
                    max_retries,
                    attempt * 5,
                )
                time.sleep(attempt * 5)
            else:
                logger.warning(
                    "Seed embedding failed after %d attempts; "
                    "vector search will use keyword fallback",
                    max_retries,
                )
                return

    for (item_id, item_type, _), vec in zip(to_embed, vectors):
        embedding_store.store(item_id, item_type, vec)
    logger.info("Embedded %d seed items (rules + playbooks + evidence + references)", len(to_embed))


MCP_HOST = os.environ.get("MCP_HOST", "0.0.0.0")
DATA_DIR = Path(os.environ.get("DATA_DIR", "data"))
WORKSPACES_BASE = Path(os.environ.get("WORKSPACES_BASE", "WORKSPACES/SYSTEM"))
CORE_API_URL = os.environ.get("CORE_API_URL", "http://localhost:8000")
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

    job_store: JobStore
    knowledge_store: KnowledgeStore
    schedule_store: ScheduleStore
    scheduler_service: SchedulerService | None
    analyzer: Analyzer
    triage_executor: TriageExecutor
    triage_sessions: TtlDict
    workspaces_base: Path
    core_api_url: str
    ssh_provider: SshCredentialProvider
    ssh_cache: SshCredentialCache
    validator: InputValidator
    formatter: ReportFormatter
    retriever: HybridRetriever
    learning_pipeline: LearningPipeline
    embedding_provider: EmbeddingProvider | None = None


def create_rate_limiter(app: Callable) -> McpRateLimiter:
    """Factory that reads config from environment variables.

    :param app: The ASGI application to wrap.
    :returns: Configured rate limiter middleware.
    """
    return McpRateLimiter(
        app=app,
        requests_per_minute=int(os.environ.get("MCP_RATE_LIMIT_RPM", "60")),
        burst=int(os.environ.get("MCP_RATE_LIMIT_BURST", "10")),
    )


_shared_context: SapContext | None = None


def get_sap_context() -> SapContext | None:
    """Return the shared ``SapContext`` if initialized, else ``None``.

    This accessor is safe to call from any module in the same process.
    The context is lazily created during the MCP server lifespan.
    """
    return _shared_context


def _init_shared_context() -> SapContext:
    """Build the shared SapContext once (called at import time)."""
    logger.info("MCP server starting — initializing services...")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    artifact_dir = DATA_DIR / "artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)

    staf_db = StafStore(DATA_DIR / "staf.db")
    job_store = JobStore(db=staf_db)
    schedule_store = ScheduleStore(db=staf_db)
    knowledge_store = KnowledgeStore(db=staf_db)
    knowledge_graph = KnowledgeGraph(db=staf_db)
    staf_db.sync()

    loader = JsonlLoader(base_dir=SEED_DIR)
    seed_defs = loader.load_directory("evidence", EvidenceCollectorDef)
    if seed_defs:
        knowledge_store.save_evidence_definitions(seed_defs)
        logger.info("Loaded %d seed evidence definitions", len(seed_defs))

    seed_rules = loader.load_directory("rules", Rule)
    if seed_rules:
        count = knowledge_store.save_rules(seed_rules)
        logger.info("Loaded %d seed rules", count)

    seed_playbooks = loader.load_directory("playbooks", Playbook)
    if seed_playbooks:
        count = knowledge_store.save_playbooks(seed_playbooks)
        logger.info("Loaded %d seed playbooks", count)

    seed_refs = loader.load_directory("references", Reference)
    if seed_refs:
        count = knowledge_store.save_references(seed_refs)
        logger.info("Loaded %d seed references", count)

    embedding_provider: EmbeddingProvider | None = None
    embedding_store: EmbeddingStore | None = None
    embed_endpoint = os.environ.get("AZURE_OPENAI_EMBEDDING_ENDPOINT", "")
    embed_deployment = os.environ.get("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "")
    ollama_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    ollama_model = os.environ.get("OLLAMA_EMBEDDING_MODEL", "nomic-embed-text")
    embed_dims = int(os.environ.get("EMBEDDING_DIMENSIONS", "768"))

    try:
        if embed_endpoint and embed_deployment:
            embedding_provider = OpenAICompatibleEmbedding(
                base_url=embed_endpoint,
                model=embed_deployment,
                api_key=os.environ.get("AZURE_OPENAI_EMBEDDING_KEY", ""),
                dimensions=embed_dims,
            )
            logger.info("Embedding provider: Azure OpenAI (%s)", embed_deployment)
        elif ollama_url:
            embedding_provider = OpenAICompatibleEmbedding(
                base_url=ollama_url,
                model=ollama_model,
                api_key="ollama",
                dimensions=embed_dims,
            )
            logger.info("Embedding provider: Ollama (%s @ %s)", ollama_model, ollama_url)

        if embedding_provider is not None:
            embedding_store = EmbeddingStore(
                db=staf_db,
                dimensions=embedding_provider.dimensions,
            )
    except Exception:
        logger.warning("Embedding provider init failed; falling back to keyword search")
        embedding_provider = None
        embedding_store = None

    if embedding_provider is not None and embedding_store is not None:
        _sync_embed_seed_knowledge(
            knowledge_store,
            embedding_store,
            embedding_provider,
        )

    retriever = HybridRetriever(
        store=knowledge_store,
        embedding_store=embedding_store,
        embedding_provider=embedding_provider,
    )
    triage_sessions: TtlDict = TtlDict(ttl_seconds=3600, max_size=100)

    evidence_collector = EvidenceCollector(allow_list=CommandAllowList.default())
    evidence_collector.register_strategy(CollectorType.SSH, SshCollectorStrategy())

    ssh_provider = SshCredentialProvider(workspaces_base=WORKSPACES_BASE)

    ctx = SapContext(
        job_store=job_store,
        knowledge_store=knowledge_store,
        schedule_store=schedule_store,
        scheduler_service=None,
        analyzer=Analyzer(),
        triage_executor=TriageExecutor(
            collector=evidence_collector,
            artifact_writer=ArtifactWriter(base_dir=artifact_dir),
        ),
        triage_sessions=triage_sessions,
        workspaces_base=WORKSPACES_BASE,
        core_api_url=CORE_API_URL,
        ssh_provider=ssh_provider,
        ssh_cache=SshCredentialCache(ssh_provider),
        validator=InputValidator(
            workspaces_base=WORKSPACES_BASE,
            sessions=triage_sessions,
            job_store=job_store,
        ),
        formatter=ReportFormatter(),
        retriever=retriever,
        learning_pipeline=LearningPipeline(
            store=knowledge_store,
            graph=knowledge_graph,
            retriever=retriever,
            embedding_store=embedding_store,
            embedding_provider=embedding_provider,
        ),
        embedding_provider=embedding_provider,
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
    stateless_http=True,
    json_response=True,
    host=MCP_HOST,
    port=MCP_PORT,
)

import src.mcp_server.tools  # noqa: E402, F401
import src.mcp_server.resources  # noqa: E402
import src.mcp_server.prompts  # noqa: E402

_mcp_asgi = mcp.streamable_http_app()


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

http_app = create_rate_limiter(_mcp_asgi)


if __name__ == "__main__":
    transport: Any = os.environ.get("MCP_TRANSPORT", "streamable-http")
    mcp.run(transport=transport)
