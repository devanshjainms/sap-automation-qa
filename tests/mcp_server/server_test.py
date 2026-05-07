# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for the MCP server built on the official MCP Python SDK.

Uses the SDK's ``ClientSession`` with ``streamable_http_client`` for
integration tests that exercise the real MCP protocol over HTTP.
"""

from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import pytest
from pytest_mock import MockerFixture
from src.core.models.evidence import CollectorType
from mcp.server.fastmcp.exceptions import ToolError
from src.core.services.workspace_backend import FilesystemBackend
from src.core.services.workspace_discovery import set_workspace_backend
from src.mcp_server.server import SapContext, mcp
from src.mcp_server.ttl_dict import TtlDict
from src.mcp_server.validation import InputValidator


@pytest.fixture()
def tmp_workspaces(mocker: MockerFixture, tmp_path: Path) -> Path:
    """Create a fake WORKSPACES/SYSTEM directory with two workspaces."""
    base = tmp_path / "WORKSPACES" / "SYSTEM"

    ws_a = base / "WS_A"
    ws_a.mkdir(parents=True)
    (ws_a / "sap-parameters.yaml").write_text("sap_sid: HA1\n")
    (ws_a / "hosts.yaml").write_text("all:\n  hosts:\n    node1:\n")

    ws_b = base / "WS_B"
    ws_b.mkdir(parents=True)
    (ws_b / "sap-parameters.yaml").write_text("sap_sid: HA2\ndatabase_high_availability: true\n")
    (ws_b / "hosts.yaml").write_text("all:\n  hosts:\n    node2:\n")

    set_workspace_backend(FilesystemBackend(base_dir=str(base)))
    return base


@pytest.fixture()
def mock_job_store(mocker: MockerFixture):
    """Job store that returns a canned job."""
    store = mocker.MagicMock()
    job = mocker.MagicMock()
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
def mock_knowledge_store(mocker: MockerFixture):
    """Knowledge store with empty data."""
    from src.core.models.knowledge import EvidenceCollectorDef

    store = mocker.MagicMock()
    store.load_rules.return_value = []
    store.load_playbooks.return_value = []
    store.load_evidence_definitions.return_value = [
        EvidenceCollectorDef(
            id="EC-OS-RELEASE-0001",
            name="OS Release",
            command="cat /etc/os-release",
            description="OS release identification",
            tags=["os", "version"],
        ),
    ]
    store.close.return_value = None
    return store


@pytest.fixture()
def mock_ssh_cache(mocker: MockerFixture):
    return mocker.MagicMock()


@pytest.fixture()
def sap_context(
    mocker: MockerFixture,
    tmp_path: Path,
    tmp_workspaces: Path,
    mock_job_store,
    mock_knowledge_store,
    mock_ssh_cache,
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
    triage_sessions: TtlDict = TtlDict()
    validator = InputValidator(
        workspaces_base=tmp_workspaces,
        sessions=triage_sessions,
        job_store=mock_job_store,
    )
    return SapContext(
        job_store=mock_job_store,
        job_worker=mocker.MagicMock(),
        knowledge_store=mock_knowledge_store,
        schedule_store=mocker.MagicMock(),
        scheduler_service=None,
        analyzer=Analyzer(),
        triage_executor=triage_executor,
        triage_sessions=triage_sessions,
        workspaces_base=tmp_workspaces,
        ssh_provider=ssh_provider,
        ssh_cache=mock_ssh_cache,
        validator=validator,
        formatter=mocker.MagicMock(),
        retriever=mocker.MagicMock(),
        learning_pipeline=mocker.MagicMock(),
    )


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
            "get_evidence_output",
            "get_job_events",
            "get_job_log",
            "get_job_results",
            "get_job_status",
            "get_schedule",
            "get_schedule_jobs",
            "get_triage_report",
            "get_workspace",
            "list_evidence_catalog",
            "list_jobs",
            "list_schedules",
            "list_workspaces",
            "query_knowledge",
            "record_investigation_outcome",
            "run_analysis",
            "run_evidence_collector",
            "run_staf_test",
            "search_logs",
            "trigger_schedule",
            "update_schedule",
        ]

    def test_tools_have_descriptions(self):
        for tool in mcp._tool_manager.list_tools():
            assert tool.description, f"Tool {tool.name} has no description"

    def test_tools_have_titles(self):
        for tool in mcp._tool_manager.list_tools():
            assert tool.title, f"Tool {tool.name} has no title"

    def test_tools_have_annotations(self):
        for tool in mcp._tool_manager.list_tools():
            ann = tool.annotations
            assert ann is not None, f"Tool {tool.name} has no annotations"
            assert ann.readOnlyHint is not None, f"Tool {tool.name} missing readOnlyHint"
            assert ann.destructiveHint is not None, f"Tool {tool.name} missing destructiveHint"
            assert ann.idempotentHint is not None, f"Tool {tool.name} missing idempotentHint"
            assert ann.openWorldHint is not None, f"Tool {tool.name} missing openWorldHint"

    def test_tools_have_icons(self):
        for tool in mcp._tool_manager.list_tools():
            assert tool.icons, f"Tool {tool.name} has no icons"

    def test_tools_have_input_schemas(self):
        for tool in mcp._tool_manager.list_tools():
            schema = tool.parameters
            assert schema.get("type") == "object", f"Tool {tool.name} missing object schema"

    def test_resource_templates_registered(self, mocker: MockerFixture):
        templates = mcp._resource_manager.list_templates()
        uris = sorted(t.uri_template for t in templates)
        assert "workspace://{workspace_id}/config" in uris
        assert "workspace://{workspace_id}/hosts" in uris
        assert "knowledge://rules" in uris
        assert "knowledge://playbooks" in uris

    def test_prompts_registered(self, mocker: MockerFixture):
        prompts = mcp._prompt_manager.list_prompts()
        names = sorted(p.name for p in prompts)
        assert names == [
            "investigate_sap_note",
            "run_ha_test_suite",
            "triage_sap_cluster",
        ]

    def test_server_name_and_instructions(self, mocker: MockerFixture):
        assert mcp.name == "SAP STAF"
        assert mcp.instructions is not None
        assert "triage" in mcp.instructions.lower()


@pytest.fixture()
def ctx(mocker: MockerFixture, sap_context: SapContext):
    """Build a minimal mock Context with the lifespan context."""
    mock_ctx = mocker.MagicMock()
    mock_ctx.request_context.lifespan_context = sap_context
    mock_ctx.info = mocker.AsyncMock()
    mock_ctx.debug = mocker.AsyncMock()
    mock_ctx.warning = mocker.AsyncMock()
    mock_ctx.report_progress = mocker.AsyncMock()
    return mock_ctx


class TestListWorkspacesTool:
    """Test list_workspaces tool."""

    @pytest.mark.asyncio
    async def test_lists_workspaces_from_directory(
        self, sap_context: SapContext, ctx, mock_job_store
    ):
        from src.mcp_server.tools.workspace_ops import list_workspaces, get_workspace

        result = await list_workspaces(ctx=ctx)

        assert result["total"] == 2
        ids = sorted(ws["id"] for ws in result["workspaces"])
        assert ids == ["WS_A", "WS_B"]

    @pytest.mark.asyncio
    async def test_empty_directory(
        self, sap_context: SapContext, ctx, tmp_path: Path, mock_job_store
    ):
        from src.mcp_server.tools.workspace_ops import list_workspaces, get_workspace

        sap_context.workspaces_base = tmp_path / "nonexistent"
        result = await list_workspaces(ctx=ctx)

        assert result["total"] == 0
        assert result["workspaces"] == []


class TestGetJobStatusTool:
    """Test get_job_status tool."""

    @pytest.mark.asyncio
    async def test_returns_job_status(self, sap_context: SapContext, ctx, mock_job_store):
        from src.mcp_server.tools.jobs_ops import get_job_status, get_job_results, list_jobs

        result = await get_job_status(job_id="job-001", ctx=ctx)

        assert result["job_id"] == "job-001"
        assert result["status"] == "completed"
        assert result["is_terminal"] is True

    @pytest.mark.asyncio
    async def test_missing_job_raises(self, sap_context: SapContext, ctx, mock_job_store):
        from src.mcp_server.tools.jobs_ops import get_job_status, get_job_results, list_jobs

        mock_job_store.get.return_value = None

        with pytest.raises(ToolError, match="not found"):
            await get_job_status(job_id="missing", ctx=ctx)


class TestGetJobResultsTool:
    """Test get_job_results tool."""

    @pytest.mark.asyncio
    async def test_returns_results(self, sap_context: SapContext, ctx):
        from src.mcp_server.tools.jobs_ops import get_job_status, get_job_results, list_jobs

        result = await get_job_results(job_id="job-001", ctx=ctx)

        assert result["exit_code"] == 0
        assert result["result"] == {"passed": 5, "failed": 0, "exit_code": 0}


class TestQueryKnowledgeTool:
    """Test query_knowledge tool."""

    @pytest.mark.asyncio
    async def test_returns_empty_on_no_match(self, sap_context: SapContext, ctx):
        from src.mcp_server.tools.retrieval import query_knowledge

        result = await query_knowledge(query="nonexistent", ctx=ctx)

        assert result["total_rules"] == 0
        assert result["total_playbooks"] == 0


class TestGetTriageReportTool:
    """Test get_triage_report tool."""

    @pytest.mark.asyncio
    async def test_missing_session_raises(self, sap_context: SapContext, ctx):
        from src.mcp_server.tools.triage_evidence import collect_evidence
        from src.mcp_server.tools.triage_analysis import run_analysis, get_triage_report

        with pytest.raises(ToolError, match="not found"):
            await get_triage_report(session_id="missing", ctx=ctx)

    @pytest.mark.asyncio
    async def test_session_without_report(
        self, mocker: MockerFixture, sap_context: SapContext, ctx
    ):
        from src.core.models.triage import TriageSession
        from src.mcp_server.tools.triage_evidence import collect_evidence
        from src.mcp_server.tools.triage_analysis import run_analysis, get_triage_report

        session = TriageSession(workspace_id="WS_A")
        sid = str(session.id)
        sap_context.triage_sessions[sid] = session

        result = await get_triage_report(session_id=sid, ctx=ctx)

        assert result["report"] is None
        assert "not yet complete" in result["message"]


class TestCollectEvidenceTool:
    """Test collect_evidence tool."""

    @pytest.mark.asyncio
    async def test_returns_session_id_with_host_and_credentials(
        self,
        mocker: MockerFixture,
        sap_context: SapContext,
        ctx,
        tmp_workspaces: Path,
        mock_ssh_cache,
    ):
        from src.mcp_server.tools.triage_evidence import collect_evidence

        (tmp_workspaces / "WS_A" / "ssh_key.ppk").write_text("fake-key")
        sap_context.triage_executor = mocker.MagicMock()
        sap_context.triage_executor.collect.return_value = []

        result = await collect_evidence(workspace_id="WS_A", ctx=ctx)

        assert "session_id" in result
        assert result["session_id"] in sap_context.triage_sessions
        assert "node1" in result["hosts_targeted"]

    @pytest.mark.asyncio
    async def test_fails_when_no_hosts(
        self, mocker: MockerFixture, sap_context: SapContext, tmp_path: Path, ctx, mock_ssh_cache
    ):
        from src.mcp_server.tools.triage_evidence import collect_evidence

        empty_ws = sap_context.workspaces_base / "EMPTY"
        empty_ws.mkdir(parents=True)
        (empty_ws / "sap-parameters.yaml").write_text("sap_sid: TST\n")

        with pytest.raises(ToolError, match="No hosts found"):
            await collect_evidence(workspace_id="EMPTY", ctx=ctx)

    @pytest.mark.asyncio
    async def test_fails_when_no_ssh_credentials(
        self,
        mocker: MockerFixture,
        sap_context: SapContext,
        tmp_workspaces: Path,
        ctx,
        mock_knowledge_store,
        mock_ssh_cache,
    ):
        from src.mcp_server.tools.triage_evidence import collect_evidence
        from src.mcp_server.tools.triage_analysis import run_analysis, get_triage_report

        mock_ssh_cache.provision.return_value = None
        with pytest.raises(ToolError, match="No SSH credentials"):
            await collect_evidence(workspace_id="WS_A", ctx=ctx)

    @pytest.mark.asyncio
    async def test_handles_collection_failure(
        self,
        mocker: MockerFixture,
        sap_context: SapContext,
        tmp_workspaces: Path,
        ctx,
        mock_knowledge_store,
    ):
        from src.mcp_server.tools.triage_evidence import collect_evidence
        from src.mcp_server.tools.triage_analysis import run_analysis, get_triage_report

        (tmp_workspaces / "WS_A" / "ssh_key.ppk").write_text("fake-key")
        sap_context.triage_executor = mocker.MagicMock()
        sap_context.triage_executor.collect.side_effect = RuntimeError("SSH failed")

        with pytest.raises(ToolError, match="SSH failed"):
            await collect_evidence(workspace_id="WS_A", ctx=ctx)

    @pytest.mark.asyncio
    async def test_builds_evidence_definitions_with_host(
        self,
        mocker: MockerFixture,
        sap_context: SapContext,
        tmp_workspaces: Path,
        ctx,
        mock_knowledge_store,
    ):
        from src.core.models.knowledge import EvidenceCollectorDef
        from src.mcp_server.tools.triage_evidence import collect_evidence
        from src.mcp_server.tools.triage_analysis import run_analysis, get_triage_report

        (tmp_workspaces / "WS_A" / "ssh_key.ppk").write_text("fake-key")
        sap_context.triage_executor = mocker.MagicMock()
        sap_context.triage_executor.collect.return_value = []
        mock_knowledge_store.load_evidence_definitions.return_value = [
            EvidenceCollectorDef(
                id="cluster-status",
                name="Cluster Status",
                command="crm_mon -1rR",
                description="Pacemaker cluster status",
            ),
        ]

        await collect_evidence(workspace_id="WS_A", ctx=ctx)

        call_args = sap_context.triage_executor.collect.call_args
        defs = call_args[0][1]
        assert len(defs) > 0
        for d in defs:
            assert d.host == "node1"
            assert d.command
            assert d.collector_type == CollectorType.SSH

    @pytest.mark.asyncio
    async def test_filters_ha_definitions_for_non_ha_workspace(
        self,
        mocker: MockerFixture,
        sap_context: SapContext,
        ctx,
        tmp_workspaces: Path,
        mock_knowledge_store,
    ):
        """When workspace has no HA, definitions with requires_ha are filtered."""
        from src.core.models.knowledge import EvidenceCollectorDef
        from src.mcp_server.tools.triage_evidence import collect_evidence
        from src.mcp_server.tools.triage_analysis import run_analysis, get_triage_report

        (tmp_workspaces / "WS_A" / "ssh_key.ppk").write_text("fake-key")
        sap_context.triage_executor = mocker.MagicMock()
        sap_context.triage_executor.collect.return_value = []

        ha_def = EvidenceCollectorDef(
            id="EC-CLUSTER-MON-0001",
            name="Cluster Status",
            command="crm_mon -1rR",
            description="Pacemaker cluster status",
            tags=["pacemaker", "cluster", "ha"],
            requires_ha=True,
        )
        os_def = EvidenceCollectorDef(
            id="EC-OS-RELEASE-0001",
            name="OS Release",
            command="cat /etc/os-release",
            description="OS release identification",
            tags=["os", "version"],
        )
        mock_knowledge_store.load_evidence_definitions.return_value = [ha_def, os_def]

        await collect_evidence(workspace_id="WS_A", ctx=ctx)

        call_args = sap_context.triage_executor.collect.call_args
        defs = call_args[0][1]
        commands = [d.command for d in defs]
        assert "cat /etc/os-release" in commands
        assert "crm_mon -1rR" not in commands

    @pytest.mark.asyncio
    async def test_keeps_ha_definitions_for_ha_workspace(
        self,
        mocker: MockerFixture,
        sap_context: SapContext,
        ctx,
        tmp_workspaces: Path,
        mock_knowledge_store,
    ):
        """When workspace has HA enabled, HA definitions are kept."""
        from src.core.models.knowledge import EvidenceCollectorDef
        from src.mcp_server.tools.triage_evidence import collect_evidence
        from src.mcp_server.tools.triage_analysis import run_analysis, get_triage_report

        (tmp_workspaces / "WS_B" / "ssh_key.ppk").write_text("fake-key")
        sap_context.triage_executor = mocker.MagicMock()
        sap_context.triage_executor.collect.return_value = []

        ha_def = EvidenceCollectorDef(
            id="EC-CLUSTER-MON-0001",
            name="Cluster Status",
            command="crm_mon -1rR",
            description="Pacemaker cluster status",
            tags=["pacemaker", "cluster", "ha"],
            requires_ha=True,
        )
        os_def = EvidenceCollectorDef(
            id="EC-OS-RELEASE-0001",
            name="OS Release",
            command="cat /etc/os-release",
            description="OS release identification",
            tags=["os", "version"],
        )
        mock_knowledge_store.load_evidence_definitions.return_value = [ha_def, os_def]

        await collect_evidence(workspace_id="WS_B", ctx=ctx)

        call_args = sap_context.triage_executor.collect.call_args
        defs = call_args[0][1]
        commands = [d.command for d in defs]
        assert "crm_mon -1rR" in commands
        assert "cat /etc/os-release" in commands

    @pytest.mark.asyncio
    async def test_explicit_definitions_bypass_ha_filter(
        self,
        mocker: MockerFixture,
        sap_context: SapContext,
        ctx,
        tmp_workspaces: Path,
        mock_knowledge_store,
    ):
        """Explicit definitions param bypasses topology filtering."""
        from src.core.models.knowledge import EvidenceCollectorDef
        from src.mcp_server.tools.triage_evidence import collect_evidence
        from src.mcp_server.tools.triage_analysis import run_analysis, get_triage_report

        (tmp_workspaces / "WS_A" / "ssh_key.ppk").write_text("fake-key")
        sap_context.triage_executor = mocker.MagicMock()
        sap_context.triage_executor.collect.return_value = []

        ha_def = EvidenceCollectorDef(
            id="EC-CLUSTER-MON-0001",
            name="Cluster Status",
            command="crm_mon -1rR",
            description="Pacemaker cluster status",
            tags=["pacemaker", "cluster", "ha"],
            requires_ha=True,
        )
        mock_knowledge_store.load_evidence_definitions.return_value = [ha_def]

        await collect_evidence(
            workspace_id="WS_A",
            definitions=["EC-CLUSTER-MON-0001"],
            ctx=ctx,
        )

        call_args = sap_context.triage_executor.collect.call_args
        defs = call_args[0][1]
        assert any(d.command == "crm_mon -1rR" for d in defs)


class TestRunAnalysisTool:
    """Test run_analysis tool."""

    @pytest.mark.asyncio
    async def test_missing_session_raises(self, sap_context: SapContext, ctx):
        from src.mcp_server.tools.triage_evidence import collect_evidence
        from src.mcp_server.tools.triage_analysis import run_analysis, get_triage_report

        with pytest.raises(ToolError, match="not found"):
            await run_analysis(session_id="missing", ctx=ctx)


class TestWorkspaceHelpers:
    """Test _load_workspace_hosts and _load_workspace_params."""

    def test_load_hosts_all_wrapper(self, tmp_workspaces: Path):
        from src.mcp_server.tools._helpers import load_workspace_hosts

        hosts = load_workspace_hosts(tmp_workspaces, "WS_A")
        assert hosts == ["node1"]

    def test_load_hosts_flat_ansible_inventory(self, tmp_path: Path):
        """Flat Ansible inventory without 'all:' wrapper (production format)."""
        from src.mcp_server.tools._helpers import load_workspace_hosts

        base = tmp_path / "SYSTEM"
        ws = base / "FLAT"
        ws.mkdir(parents=True)
        (ws / "hosts.yaml").write_text(
            "R11_DB:\n"
            "  hosts:\n"
            "    r11dhdb00l030:\n"
            "      ansible_host: 172.235.1.12\n"
            "      ansible_user: azureadm\n"
            "    r11dhdb00l130:\n"
            "      ansible_host: 172.235.1.13\n"
            "      ansible_user: azureadm\n"
            "R11_SCS:\n"
            "  hosts:\n"
            "    r11scs00l306:\n"
            "      ansible_host: 172.235.2.19\n"
        )
        hosts = load_workspace_hosts(base, "FLAT")
        assert sorted(hosts) == [
            "172.235.1.12",
            "172.235.1.13",
            "172.235.2.19",
        ]

    def test_load_host_details_flat_inventory(self, tmp_path: Path):
        """Host details include ansible_host, ansible_user, become_user, and name."""
        from src.mcp_server.tools._helpers import load_workspace_host_details

        base = tmp_path / "SYSTEM"
        ws = base / "DETAIL"
        ws.mkdir(parents=True)
        (ws / "hosts.yaml").write_text(
            "DB:\n"
            "  hosts:\n"
            "    dbhost:\n"
            "      ansible_host: 10.0.0.1\n"
            "      ansible_user: azureadm\n"
            "      become_user: root\n"
            "  vars:\n"
            "    node_tier: hana\n"
        )
        details = load_workspace_host_details(base, "DETAIL")
        assert len(details) == 1
        assert details[0]["name"] == "dbhost"
        assert details[0]["ansible_host"] == "10.0.0.1"
        assert details[0]["ansible_user"] == "azureadm"
        assert details[0]["become_user"] == "root"
        assert details[0]["node_tier"] == "hana"

    def test_load_host_details_multi_tier(self, tmp_path: Path):
        """Multiple groups with different node_tiers."""
        from src.mcp_server.tools._helpers import load_workspace_host_details

        base = tmp_path / "SYSTEM"
        ws = base / "MULTI"
        ws.mkdir(parents=True)
        (ws / "hosts.yaml").write_text(
            "DB:\n"
            "  hosts:\n"
            "    db1:\n"
            "      ansible_host: 10.0.0.1\n"
            "    db2:\n"
            "      ansible_host: 10.0.0.2\n"
            "  vars:\n"
            "    node_tier: hana\n"
            "SCS:\n"
            "  hosts:\n"
            "    scs1:\n"
            "      ansible_host: 10.0.0.3\n"
            "  vars:\n"
            "    node_tier: scs\n"
            "ERS:\n"
            "  hosts:\n"
            "    ers1:\n"
            "      ansible_host: 10.0.0.4\n"
            "  vars:\n"
            "    node_tier: ers\n"
        )
        details = load_workspace_host_details(base, "MULTI")
        assert len(details) == 4
        tiers = [d["node_tier"] for d in details]
        assert tiers == ["hana", "hana", "scs", "ers"]
        db_hosts = [d for d in details if d["node_tier"] == "hana"]
        assert len(db_hosts) == 2
        scs_hosts = [d for d in details if d["node_tier"] in ("scs", "ers")]
        assert len(scs_hosts) == 2

    def test_load_hosts_falls_back_to_key_name(self, tmp_path: Path):
        """When no ansible_host is set, the inventory key is used."""
        from src.mcp_server.tools._helpers import load_workspace_hosts

        base = tmp_path / "SYSTEM"
        ws = base / "NOIP"
        ws.mkdir(parents=True)
        (ws / "hosts.yaml").write_text("G:\n  hosts:\n    myhost:\n")
        hosts = load_workspace_hosts(base, "NOIP")
        assert hosts == ["myhost"]

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
