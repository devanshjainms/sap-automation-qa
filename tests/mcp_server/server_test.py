# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for the MCP server built on the official MCP Python SDK.

Uses the SDK's ``ClientSession`` with ``streamable_http_client`` for
integration tests that exercise the real MCP protocol over HTTP.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.core.models.evidence import CollectorType
from mcp.server.fastmcp.exceptions import ToolError
from src.mcp_server.server import SapContext, mcp
from src.mcp_server.validation import InputValidator

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_workspaces(tmp_path: Path) -> Path:
    """Create a fake WORKSPACES/SYSTEM directory with two workspaces."""
    base = tmp_path / "WORKSPACES" / "SYSTEM"

    # Workspace A
    ws_a = base / "WS_A"
    ws_a.mkdir(parents=True)
    (ws_a / "sap-parameters.yaml").write_text("sap_sid: HA1\n")
    (ws_a / "hosts.yaml").write_text("all:\n  hosts:\n    node1:\n")

    # Workspace B
    ws_b = base / "WS_B"
    ws_b.mkdir(parents=True)
    (ws_b / "sap-parameters.yaml").write_text("sap_sid: HA2\ndatabase_high_availability: true\n")
    (ws_b / "hosts.yaml").write_text("all:\n  hosts:\n    node2:\n")

    return base


@pytest.fixture()
def mock_job_store() -> MagicMock:
    """Job store that returns a canned job."""
    store = MagicMock()
    job = MagicMock()
    job.id = "job-001"
    job.status = "completed"
    job.workspace_id = "WS_A"
    job.test_group = "ConfigurationChecks"
    job.is_terminal = True
    job.result = {"passed": 5, "failed": 0, "exit_code": 0}
    job.events = []
    job.created_at = None
    job.started_at = None
    job.completed_at = None
    store.get.return_value = job
    return store


@pytest.fixture()
def mock_knowledge_store() -> MagicMock:
    """Knowledge store with empty data."""
    store = MagicMock()
    store.load_rules.return_value = []
    store.load_playbooks.return_value = []
    store.close.return_value = None
    return store


@pytest.fixture()
def sap_context(
    tmp_path: Path,
    tmp_workspaces: Path,
    mock_job_store: MagicMock,
    mock_knowledge_store: MagicMock,
) -> SapContext:
    """Build a SapContext with mocked services."""
    from src.core.analyzer.analyzer import Analyzer
    from src.core.execution.command_allow_list import CommandAllowList
    from src.core.execution.evidence_collector import EvidenceCollector
    from src.core.execution.ssh_provider import SshCredentialProvider
    from src.core.execution.triage_executor import ArtifactWriter, TriageExecutor

    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    allow_list = CommandAllowList()
    evidence_collector = EvidenceCollector(allow_list=allow_list)
    artifact_writer = ArtifactWriter(base_dir=artifact_dir)
    triage_executor = TriageExecutor(
        collector=evidence_collector,
        artifact_writer=artifact_writer,
    )
    ssh_provider = SshCredentialProvider(workspaces_base=tmp_workspaces)
    triage_sessions: dict = {}
    validator = InputValidator(
        workspaces_base=tmp_workspaces,
        sessions=triage_sessions,
        job_store=mock_job_store,
    )
    return SapContext(
        job_store=mock_job_store,
        knowledge_store=mock_knowledge_store,
        schedule_store=MagicMock(),
        scheduler_service=None,
        analyzer=Analyzer(),
        triage_executor=triage_executor,
        triage_sessions=triage_sessions,
        workspaces_base=tmp_workspaces,
        core_api_url="http://localhost:8000",
        ssh_provider=ssh_provider,
        validator=validator,
        formatter=MagicMock(),
        retriever=MagicMock(),
        learning_pipeline=MagicMock(),
    )


# ---------------------------------------------------------------------------
# Server introspection tests
# ---------------------------------------------------------------------------


class TestServerRegistration:
    """Verify that tools, resources, and prompts register correctly."""

    def test_all_tools_registered(self):
        tools = mcp._tool_manager.list_tools()
        names = sorted(t.name for t in tools)
        assert names == [
            "cancel_job",
            "collect_evidence",
            "create_schedule",
            "delete_schedule",
            "get_job_events",
            "get_job_log",
            "get_job_results",
            "get_job_status",
            "get_schedule",
            "get_schedule_jobs",
            "get_triage_report",
            "get_workspace",
            "list_jobs",
            "list_schedules",
            "list_workspaces",
            "query_knowledge",
            "run_analysis",
            "run_staf_test",
            "trigger_schedule",
            "update_schedule",
        ]

    def test_tools_have_descriptions(self):
        for tool in mcp._tool_manager.list_tools():
            assert tool.description, f"Tool {tool.name} has no description"

    def test_tools_have_input_schemas(self):
        for tool in mcp._tool_manager.list_tools():
            schema = tool.parameters
            assert schema.get("type") == "object", f"Tool {tool.name} missing object schema"

    def test_resource_templates_registered(self):
        templates = mcp._resource_manager.list_templates()
        uris = sorted(t.uri_template for t in templates)
        assert "workspace://{workspace_id}/config" in uris
        assert "workspace://{workspace_id}/hosts" in uris
        assert "knowledge://rules" in uris
        assert "knowledge://playbooks" in uris

    def test_prompts_registered(self):
        prompts = mcp._prompt_manager.list_prompts()
        names = sorted(p.name for p in prompts)
        assert names == [
            "investigate_sap_note",
            "run_ha_test_suite",
            "triage_sap_cluster",
        ]

    def test_server_name_and_instructions(self):
        assert mcp.name == "SAP STAF"
        assert mcp.instructions is not None
        assert "triage" in mcp.instructions.lower()


# ---------------------------------------------------------------------------
# Tool logic tests (mock Context)
# ---------------------------------------------------------------------------


def _make_ctx(sap_context: SapContext) -> MagicMock:
    """Build a minimal mock Context with the lifespan context."""
    from unittest.mock import AsyncMock

    ctx = MagicMock()
    ctx.request_context.lifespan_context = sap_context
    ctx.info = AsyncMock()
    ctx.debug = AsyncMock()
    ctx.warning = AsyncMock()
    ctx.report_progress = AsyncMock()
    return ctx


class TestListWorkspacesTool:
    """Test list_workspaces tool."""

    @pytest.mark.asyncio
    async def test_lists_workspaces_from_directory(self, sap_context: SapContext):
        from src.mcp_server.tools.triage import list_workspaces

        ctx = _make_ctx(sap_context)
        result = await list_workspaces(ctx=ctx)

        assert result["total"] == 2
        ids = sorted(ws["id"] for ws in result["workspaces"])
        assert ids == ["WS_A", "WS_B"]

    @pytest.mark.asyncio
    async def test_empty_directory(self, sap_context: SapContext, tmp_path: Path):
        from src.mcp_server.tools.triage import list_workspaces

        sap_context.workspaces_base = tmp_path / "nonexistent"
        ctx = _make_ctx(sap_context)
        result = await list_workspaces(ctx=ctx)

        assert result["total"] == 0
        assert result["workspaces"] == []


class TestGetJobStatusTool:
    """Test get_job_status tool."""

    @pytest.mark.asyncio
    async def test_returns_job_status(self, sap_context: SapContext):
        from src.mcp_server.tools.staf import get_job_status

        ctx = _make_ctx(sap_context)
        result = await get_job_status(job_id="job-001", ctx=ctx)

        assert result["job_id"] == "job-001"
        assert result["status"] == "completed"
        assert result["is_terminal"] is True

    @pytest.mark.asyncio
    async def test_missing_job_raises(self, sap_context: SapContext):
        from src.mcp_server.tools.staf import get_job_status

        sap_context.job_store.get.return_value = None  # type: ignore[union-attr]
        ctx = _make_ctx(sap_context)

        with pytest.raises(ToolError, match="not found"):
            await get_job_status(job_id="missing", ctx=ctx)


class TestGetJobResultsTool:
    """Test get_job_results tool."""

    @pytest.mark.asyncio
    async def test_returns_results(self, sap_context: SapContext):
        from src.mcp_server.tools.staf import get_job_results

        ctx = _make_ctx(sap_context)
        result = await get_job_results(job_id="job-001", ctx=ctx)

        assert result["exit_code"] == 0
        assert result["result"] == {"passed": 5, "failed": 0, "exit_code": 0}


class TestQueryKnowledgeTool:
    """Test query_knowledge tool."""

    @pytest.mark.asyncio
    async def test_returns_empty_on_no_match(self, sap_context: SapContext):
        from src.mcp_server.tools.triage import query_knowledge

        ctx = _make_ctx(sap_context)
        result = await query_knowledge(query="nonexistent", ctx=ctx)

        assert result["total_rules"] == 0
        assert result["total_playbooks"] == 0


class TestGetTriageReportTool:
    """Test get_triage_report tool."""

    @pytest.mark.asyncio
    async def test_missing_session_raises(self, sap_context: SapContext):
        from src.mcp_server.tools.triage import get_triage_report

        ctx = _make_ctx(sap_context)
        with pytest.raises(ToolError, match="not found"):
            await get_triage_report(session_id="missing", ctx=ctx)

    @pytest.mark.asyncio
    async def test_session_without_report(self, sap_context: SapContext):
        from src.core.models.triage import TriageSession
        from src.mcp_server.tools.triage import get_triage_report

        session = TriageSession(workspace_id="WS_A")
        sid = str(session.id)
        sap_context.triage_sessions[sid] = session

        ctx = _make_ctx(sap_context)
        result = await get_triage_report(session_id=sid, ctx=ctx)

        assert result["report"] is None
        assert "not yet complete" in result["message"]


class TestCollectEvidenceTool:
    """Test collect_evidence tool."""

    @pytest.mark.asyncio
    async def test_returns_session_id_with_host_and_credentials(
        self, sap_context: SapContext, tmp_workspaces: Path
    ):
        from src.mcp_server.tools.triage import collect_evidence

        # Place a fake SSH key so credential provisioning succeeds.
        (tmp_workspaces / "WS_A" / "ssh_key.ppk").write_text("fake-key")

        # Mock the triage executor to avoid real SSH execution.
        sap_context.triage_executor = MagicMock()
        sap_context.triage_executor.collect.return_value = []

        ctx = _make_ctx(sap_context)
        result = await collect_evidence(workspace_id="WS_A", ctx=ctx)

        assert "session_id" in result
        assert result["session_id"] in sap_context.triage_sessions
        assert result["target_host"] == "node1"
        assert result["hosts_discovered"] == ["node1"]

    @pytest.mark.asyncio
    async def test_fails_when_no_hosts(self, sap_context: SapContext, tmp_path: Path):
        from src.mcp_server.tools.triage import collect_evidence

        # Create a workspace with no hosts.yaml.
        empty_ws = sap_context.workspaces_base / "EMPTY"
        empty_ws.mkdir(parents=True)
        (empty_ws / "sap-parameters.yaml").write_text("sap_sid: TST\n")

        ctx = _make_ctx(sap_context)
        with pytest.raises(ToolError, match="No hosts found"):
            await collect_evidence(workspace_id="EMPTY", ctx=ctx)

    @pytest.mark.asyncio
    async def test_fails_when_no_ssh_credentials(
        self, sap_context: SapContext, tmp_workspaces: Path
    ):
        from src.mcp_server.tools.triage import collect_evidence

        # WS_A has hosts.yaml but no ssh_key — should fail gracefully.
        ctx = _make_ctx(sap_context)
        with pytest.raises(ToolError, match="No SSH credentials"):
            await collect_evidence(workspace_id="WS_A", ctx=ctx)

    @pytest.mark.asyncio
    async def test_handles_collection_failure(
        self, sap_context: SapContext, tmp_workspaces: Path
    ):
        from src.mcp_server.tools.triage import collect_evidence

        (tmp_workspaces / "WS_A" / "ssh_key.ppk").write_text("fake-key")
        sap_context.triage_executor = MagicMock()
        sap_context.triage_executor.collect.side_effect = RuntimeError("SSH failed")

        ctx = _make_ctx(sap_context)
        with pytest.raises(ToolError, match="SSH failed"):
            await collect_evidence(workspace_id="WS_A", ctx=ctx)

    @pytest.mark.asyncio
    async def test_builds_evidence_definitions_with_host(
        self, sap_context: SapContext, tmp_workspaces: Path
    ):
        from src.core.models.knowledge import EvidenceCollectorDef
        from src.mcp_server.tools.triage import collect_evidence

        (tmp_workspaces / "WS_A" / "ssh_key.ppk").write_text("fake-key")
        sap_context.triage_executor = MagicMock()
        sap_context.triage_executor.collect.return_value = []
        sap_context.knowledge_store.load_evidence_definitions.return_value = [  # type: ignore[union-attr]
            EvidenceCollectorDef(
                id="cluster-status",
                name="Cluster Status",
                command="crm_mon -1rR",
                description="Pacemaker cluster status",
            ),
        ]

        ctx = _make_ctx(sap_context)
        await collect_evidence(workspace_id="WS_A", ctx=ctx)

        # Verify the executor received definitions with actual host set.
        call_args = sap_context.triage_executor.collect.call_args
        defs = call_args[0][1]  # second positional arg = evidence_defs
        assert len(defs) > 0
        for d in defs:
            assert d.host == "node1"
            assert d.command
            assert d.collector_type == CollectorType.SSH


class TestRunAnalysisTool:
    """Test run_analysis tool."""

    @pytest.mark.asyncio
    async def test_missing_session_raises(self, sap_context: SapContext):
        from src.mcp_server.tools.triage import run_analysis

        ctx = _make_ctx(sap_context)

        with pytest.raises(ToolError, match="not found"):
            await run_analysis(session_id="missing", ctx=ctx)


# ---------------------------------------------------------------------------
# Workspace helper tests
# ---------------------------------------------------------------------------


class TestWorkspaceHelpers:
    """Test _load_workspace_hosts and _load_workspace_params."""

    def test_load_hosts_flat_inventory(self, tmp_workspaces: Path):
        from src.mcp_server.tools._helpers import load_workspace_hosts

        hosts = load_workspace_hosts(tmp_workspaces, "WS_A")
        assert hosts == ["node1"]

    def test_load_hosts_grouped_inventory(self, tmp_path: Path):
        from src.mcp_server.tools._helpers import load_workspace_hosts

        base = tmp_path / "SYSTEM"
        ws = base / "GRP"
        ws.mkdir(parents=True)
        (ws / "hosts.yaml").write_text(
            "all:\n"
            "  children:\n"
            "    db:\n"
            "      hosts:\n"
            "        10.0.0.1:\n"
            "        10.0.0.2:\n"
            "    scs:\n"
            "      hosts:\n"
            "        10.0.0.3:\n"
        )
        hosts = load_workspace_hosts(base, "GRP")
        assert sorted(hosts) == ["10.0.0.1", "10.0.0.2", "10.0.0.3"]

    def test_load_hosts_missing_file(self, tmp_path: Path):
        from src.mcp_server.tools._helpers import load_workspace_hosts

        hosts = load_workspace_hosts(tmp_path, "nonexistent")
        assert hosts == []

    def test_load_params(self, tmp_workspaces: Path):
        from src.mcp_server.tools._helpers import load_workspace_params

        params = load_workspace_params(tmp_workspaces, "WS_B")
        assert params["sap_sid"] == "HA2"
        assert params["database_high_availability"] is True

    def test_load_params_missing_file(self, tmp_path: Path):
        from src.mcp_server.tools._helpers import load_workspace_params

        params = load_workspace_params(tmp_path, "nonexistent")
        assert params == {}
