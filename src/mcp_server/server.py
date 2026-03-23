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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from pydantic import AnyHttpUrl
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from src.agents.formatter import ReportFormatter
from agent_framework.azure import AzureOpenAIEmbeddingClient
from agent_framework.openai import OpenAIEmbeddingClient
from src.core.analyzer.analyzer import Analyzer
from src.core.execution.command_allow_list import CommandAllowList
from src.core.execution.evidence_collector import EvidenceCollector
from src.core.execution.ssh_provider import SshCredentialProvider
from src.core.execution.triage_executor import ArtifactWriter, TriageExecutor
from src.core.knowledge.learning import LearningPipeline
from src.core.knowledge.loader import JsonlLoader
from src.core.knowledge.retrieval import HybridRetriever
from src.core.models.embedding import EmbeddingProvider
from src.core.models.knowledge import EvidenceCollectorDef
from src.core.models.triage import TriageSession
from src.core.services.scheduler import SchedulerService
from src.core.storage.embedding_store import EmbeddingStore
from src.core.storage.job_store import JobStore
from src.core.storage.knowledge_graph import KnowledgeGraph
from src.core.storage.knowledge_store import KnowledgeStore
from src.core.storage.schedule_store import ScheduleStore
from src.mcp_server.auth import create_token_verifier
from src.mcp_server.validation import InputValidator
from src.mcp_server.rate_limit import McpRateLimiter
from src.agents.providers.embedding_adapter import EmbeddingAdapter

logger = logging.getLogger(__name__)


MCP_PORT = int(os.environ.get("MCP_PORT", "8001"))


def _embed_seed_knowledge(
    store: KnowledgeStore,
    embedding_store: EmbeddingStore,
    provider: EmbeddingProvider,
) -> None:
    """One-time embedding of seed rules and playbooks.

    Skips items that already have an embedding stored.

    :param store: Knowledge store to read rules/playbooks from.
    :param embedding_store: Vector store to write embeddings to.
    :param provider: Embedding provider for text→vector conversion.
    """
    rules = store.load_rules()
    playbooks = store.load_playbooks()

    to_embed: list[tuple[str, str, str]] = []
    for rule in rules:
        if not embedding_store.has(rule.id, "rule"):
            text = f"{rule.name} {rule.description} {' '.join(rule.tags)}"
            to_embed.append((rule.id, "rule", text))
    for pb in playbooks:
        if not embedding_store.has(pb.id, "playbook"):
            text = f"{pb.name} {pb.description} " f"{' '.join(pb.symptoms)} {' '.join(pb.tags)}"
            to_embed.append((pb.id, "playbook", text))

    if not to_embed:
        return

    texts = [t[2] for t in to_embed]
    try:
        vectors = provider.embed_batch(texts)
    except Exception:
        logger.warning("Seed embedding failed; vector search will use keyword fallback")
        return

    for (item_id, item_type, _), vec in zip(to_embed, vectors):
        embedding_store.store(item_id, item_type, vec)
    logger.info("Embedded %d seed items (rules + playbooks)", len(to_embed))


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
    triage_sessions: dict[str, TriageSession]
    workspaces_base: Path
    core_api_url: str
    ssh_provider: SshCredentialProvider
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


@asynccontextmanager
async def sap_lifespan(server: FastMCP) -> AsyncIterator[SapContext]:
    """Initialize and tear down shared services.

    :param server: The ``FastMCP`` server instance.
    :yields: A :class:`SapContext` accessible in every tool handler.
    """
    logger.info("MCP server starting — initializing services...")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    artifact_dir = DATA_DIR / "artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)

    job_store = JobStore(db_path=DATA_DIR / "scheduler.db")
    knowledge_store = KnowledgeStore(db_path=DATA_DIR / "knowledge.db")
    schedule_store = ScheduleStore(db_path=DATA_DIR / "scheduler.db")
    knowledge_graph = KnowledgeGraph(db_path=DATA_DIR / "knowledge.db")

    loader = JsonlLoader(base_dir=SEED_DIR)
    seed_defs = loader.load_directory("evidence", EvidenceCollectorDef)
    if seed_defs:
        knowledge_store.save_evidence_definitions(seed_defs)
        logger.info("Loaded %d seed evidence definitions", len(seed_defs))

    from src.core.models.knowledge import Playbook, Reference, Rule

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

            af_client = AzureOpenAIEmbeddingClient(
                endpoint=embed_endpoint,
                deployment_name=embed_deployment,
                api_key=os.environ.get("AZURE_OPENAI_EMBEDDING_KEY") or None,
            )
            embedding_provider = EmbeddingAdapter(af_client, dimensions=embed_dims)
            logger.info("Embedding provider: Azure OpenAI (%s)", embed_deployment)
        else:

            af_client = OpenAIEmbeddingClient(
                model_id=ollama_model,
                base_url=ollama_url,
                api_key="ollama",
            )
            embedding_provider = EmbeddingAdapter(af_client, dimensions=embed_dims)
            logger.info("Embedding provider: Ollama (%s @ %s)", ollama_model, ollama_url)

        embedding_store = EmbeddingStore(
            db_path=DATA_DIR / "embeddings.db",
            dimensions=embedding_provider.dimensions,
        )
    except Exception:
        logger.warning("Embedding provider init failed; falling back to keyword search")
        embedding_provider = None
        embedding_store = None

    if embedding_provider is not None and embedding_store is not None:
        _embed_seed_knowledge(knowledge_store, embedding_store, embedding_provider)

    retriever = HybridRetriever(
        store=knowledge_store,
        embedding_store=embedding_store,
        embedding_provider=embedding_provider,
    )
    triage_sessions: dict[str, TriageSession] = {}

    try:
        sap_context = SapContext(
            job_store=job_store,
            knowledge_store=knowledge_store,
            schedule_store=schedule_store,
            scheduler_service=None,
            analyzer=Analyzer(),
            triage_executor=TriageExecutor(
                collector=EvidenceCollector(allow_list=CommandAllowList()),
                artifact_writer=ArtifactWriter(base_dir=artifact_dir),
            ),
            triage_sessions=triage_sessions,
            workspaces_base=WORKSPACES_BASE,
            core_api_url=CORE_API_URL,
            ssh_provider=SshCredentialProvider(workspaces_base=WORKSPACES_BASE),
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
        # Set module-level reference for resource handlers (stateless HTTP mode)
        from src.mcp_server.resources import set_sap_context

        set_sap_context(sap_context)

        yield sap_context
    finally:
        logger.info("MCP server shutting down — releasing resources...")
        if embedding_store is not None:
            embedding_store.close()
        knowledge_graph.close()
        schedule_store.close()
        knowledge_store.close()
        job_store.close()


_token_verifier = create_token_verifier()
_auth_settings: AuthSettings | None = None

if _token_verifier is not None:
    _auth_settings = AuthSettings(
        issuer_url=AnyHttpUrl(f"http://{MCP_HOST}:{MCP_PORT}"),
        resource_server_url=AnyHttpUrl(f"http://{MCP_HOST}:{MCP_PORT}"),
        required_scopes=["mcp:tools"],
    )

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
    auth=_auth_settings,
    token_verifier=_token_verifier,
)

# Register tools, resources, and prompts.
# These imports MUST come after ``mcp`` and ``SapContext`` are defined
# because the decorator modules import them back from this module.
import src.mcp_server.tools  # noqa: E402, F401
import src.mcp_server.resources  # noqa: E402
import src.mcp_server.prompts  # noqa: E402

# Build the HTTP application exposed via uvicorn.
_mcp_asgi = mcp.streamable_http_app()
http_app = create_rate_limiter(_mcp_asgi)


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
