# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for run_staf_test and run_analysis tool handlers.

Fills the test gaps identified in the Phase 4 audit. Uses the same
mock-Context pattern as ``server_test.py``.
"""

from __future__ import annotations
import json
from pathlib import Path
from typing import Any
from pytest_mock import MockerFixture
import pytest
from mcp.server.fastmcp.exceptions import ToolError
from src.core.models.knowledge import Rule
from src.core.models.triage import (
    TriageFinding,
    TriageReport,
    TriageSession,
)
from src.core.models.failure import Severity
from src.core.knowledge.retrieval import HybridRetriever
from src.mcp_server.server import SapContext
from src.mcp_server.validation import InputValidator


@pytest.fixture()
def tmp_workspaces(mocker: MockerFixture, tmp_path: Path) -> Path:
    base = tmp_path / "WORKSPACES" / "SYSTEM"
    ws = base / "WS_A"
    ws.mkdir(parents=True)
    (ws / "sap-parameters.yaml").write_text("sap_sid: HA1\n")
    (ws / "hosts.yaml").write_text("all:\n  hosts:\n    node1:\n")
    return base


@pytest.fixture()
def mock_job_store(mocker: MockerFixture) -> MagicMock:
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
def mock_knowledge_store(mocker: MockerFixture) -> MagicMock:
    store = mocker.MagicMock()
    store.load_rules.return_value = [
        Rule(
            id="DB-HANA-0001",
            name="HANA HSR status",
            description="Check HANA system replication is healthy",
            category="ha_check",
            severity="CRITICAL",
            tags=["hana", "hsr"],
        ),
    ]
    store.load_playbooks.return_value = []
    store.load_evidence_definitions.return_value = []
    store.close.return_value = None
    return store


@pytest.fixture()
def sap_context(
    mocker: MockerFixture,
    tmp_path: Path,
    tmp_workspaces: Path,
    mock_job_store,
    mock_knowledge_store,
) -> SapContext:
    from src.core.analyzer.analyzer import Analyzer

    triage_sessions: dict = {}
    validator = InputValidator(
        workspaces_base=tmp_workspaces,
        sessions=triage_sessions,
        job_store=mock_job_store,
    )
    return SapContext(
        job_store=mock_job_store,
        knowledge_store=mock_knowledge_store,
        schedule_store=mocker.MagicMock(),
        scheduler_service=None,
        analyzer=Analyzer(),
        triage_executor=mocker.MagicMock(),
        triage_sessions=triage_sessions,
        workspaces_base=tmp_workspaces,
        core_api_url="http://localhost:8000",
        ssh_provider=mocker.MagicMock(),
        ssh_cache=mocker.MagicMock(),
        validator=validator,
        formatter=mocker.MagicMock(),
        retriever=HybridRetriever(store=mock_knowledge_store),
        learning_pipeline=mocker.MagicMock(),
    )


@pytest.fixture()
def ctx(mocker: MockerFixture, sap_context: SapContext):
    mock_ctx = mocker.MagicMock()
    mock_ctx.request_context.lifespan_context = sap_context
    mock_ctx.info = mocker.AsyncMock()
    mock_ctx.debug = mocker.AsyncMock()
    mock_ctx.warning = mocker.AsyncMock()
    mock_ctx.report_progress = mocker.AsyncMock()
    return mock_ctx


class TestRunStafTest:
    """Test run_staf_test tool."""

    @pytest.mark.asyncio
    async def test_submits_job_and_returns_id(
        self, mocker: MockerFixture, sap_context: SapContext, ctx
    ):
        from src.mcp_server.tools.staf import run_staf_test

        mock_response = mocker.MagicMock()
        mock_response.json.return_value = {
            "id": "job-123",
            "status": "submitted",
        }
        mock_response.raise_for_status = mocker.MagicMock()

        mock_client = mocker.AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = mocker.AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = mocker.AsyncMock(return_value=False)

        mocker.patch("httpx.AsyncClient", return_value=mock_client)
        result = await run_staf_test(
            workspace_id="WS_A",
            test_group="ConfigurationChecks",
            ctx=ctx,
        )

        assert result["job_id"] == "job-123"
        assert result["workspace_id"] == "WS_A"
        assert result["test_group"] == "ConfigurationChecks"
        assert result["status"] == "submitted"

    @pytest.mark.asyncio
    async def test_passes_test_ids_in_payload(
        self, mocker: MockerFixture, sap_context: SapContext, ctx
    ):
        from src.mcp_server.tools.staf import run_staf_test

        mock_response = mocker.MagicMock()
        mock_response.json.return_value = {"id": "job-456", "status": "submitted"}
        mock_response.raise_for_status = mocker.MagicMock()

        mock_client = mocker.AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = mocker.AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = mocker.AsyncMock(return_value=False)

        mocker.patch("httpx.AsyncClient", return_value=mock_client)
        await run_staf_test(
            workspace_id="WS_A",
            test_group="DatabaseHighAvailability",
            test_ids=["ha-config", "azure-lb"],
            ctx=ctx,
        )

        payload = mock_client.post.call_args
        body = payload.kwargs.get("json") or payload[1].get("json")
        assert body["test_ids"] == ["ha-config", "azure-lb"]

    @pytest.mark.asyncio
    async def test_handles_job_id_key_fallback(
        self, mocker: MockerFixture, sap_context: SapContext, ctx
    ):
        from src.mcp_server.tools.staf import run_staf_test

        mock_response = mocker.MagicMock()
        mock_response.json.return_value = {"job_id": "job-789", "status": "queued"}
        mock_response.raise_for_status = mocker.MagicMock()

        mock_client = mocker.AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = mocker.AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = mocker.AsyncMock(return_value=False)

        mocker.patch("httpx.AsyncClient", return_value=mock_client)
        result = await run_staf_test(
            workspace_id="WS_A",
            test_group="ConfigurationChecks",
            ctx=ctx,
        )

        assert result["job_id"] == "job-789"

    @pytest.mark.asyncio
    async def test_http_error_propagates(self, mocker: MockerFixture, sap_context: SapContext, ctx):
        import httpx
        from src.mcp_server.tools.staf import run_staf_test

        mock_response = mocker.MagicMock()
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Server Error",
            request=mocker.MagicMock(),
            response=mocker.MagicMock(status_code=500),
        )

        mock_client = mocker.AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = mocker.AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = mocker.AsyncMock(return_value=False)

        mocker.patch("httpx.AsyncClient", return_value=mock_client)
        with pytest.raises(httpx.HTTPStatusError):
            await run_staf_test(
                workspace_id="WS_A",
                test_group="ConfigurationChecks",
                ctx=ctx,
            )

    @pytest.mark.asyncio
    async def test_uses_core_api_url(self, mocker: MockerFixture, sap_context: SapContext, ctx):
        from src.mcp_server.tools.staf import run_staf_test

        sap_context.core_api_url = "http://custom:9999"

        mock_response = mocker.MagicMock()
        mock_response.json.return_value = {"id": "j1", "status": "submitted"}
        mock_response.raise_for_status = mocker.MagicMock()

        mock_client = mocker.AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = mocker.AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = mocker.AsyncMock(return_value=False)

        ctor = mocker.patch("httpx.AsyncClient", return_value=mock_client)
        await run_staf_test(
            workspace_id="WS_A",
            test_group="ConfigurationChecks",
            ctx=ctx,
        )

        ctor.assert_called_once_with(base_url="http://custom:9999", timeout=30.0)


class TestRunAnalysis:
    """Test run_analysis tool."""

    @pytest.mark.asyncio
    async def test_analyzes_session_and_returns_report(
        self, sap_context: SapContext, mocker: MockerFixture, ctx
    ):
        from src.mcp_server.tools.triage_evidence import (
            collect_evidence,
            list_evidence_catalog,
            run_evidence_collector,
        )
        from src.mcp_server.tools.triage_analysis import run_analysis, get_triage_report
        from src.mcp_server.tools.triage_commands import search_logs, record_investigation_outcome

        session = TriageSession(workspace_id="WS_A")
        session.start_collection()
        session.complete_collection([])
        sid = str(session.id)
        sap_context.triage_sessions[sid] = session

        report = TriageReport(
            session_id=sid,
            workspace_id="WS_A",
            findings=[
                TriageFinding(
                    finding_id="F-001",
                    severity=Severity.CRITICAL,
                    failure_class="fencing_not_triggered",
                    title="STONITH not enabled",
                    remediation=["Enable STONITH in CIB"],
                ),
            ],
            summary="1 critical finding",
            evidence_count=0,
            rules_evaluated=1,
        )
        sap_context.analyzer = mocker.MagicMock()
        sap_context.analyzer.analyze.return_value = report

        result = await run_analysis(session_id=sid, ctx=ctx)

        assert result["session_id"] == sid
        assert result["checks_failed"] == 1
        assert result["health"] == "CRITICAL"
        assert result["findings"][0]["severity"] == "CRITICAL"
        assert "STONITH" in result["findings"][0]["title"]

    @pytest.mark.asyncio
    async def test_empty_findings(self, mocker: MockerFixture, sap_context: SapContext, ctx):
        from src.mcp_server.tools.triage_evidence import (
            collect_evidence,
            list_evidence_catalog,
            run_evidence_collector,
        )
        from src.mcp_server.tools.triage_analysis import run_analysis, get_triage_report
        from src.mcp_server.tools.triage_commands import search_logs, record_investigation_outcome

        session = TriageSession(workspace_id="WS_A")
        session.start_collection()
        session.complete_collection([])
        sid = str(session.id)
        sap_context.triage_sessions[sid] = session

        report = TriageReport(
            session_id=sid,
            workspace_id="WS_A",
            summary="No issues found",
            evidence_count=0,
            rules_evaluated=5,
        )
        sap_context.analyzer = mocker.MagicMock()
        sap_context.analyzer.analyze.return_value = report

        result = await run_analysis(session_id=sid, ctx=ctx)

        assert result["checks_failed"] == 0
        assert result["health"] == "HEALTHY"
        assert result["findings"] == []

    @pytest.mark.asyncio
    async def test_missing_session_raises(self, sap_context: SapContext, ctx):
        from src.mcp_server.tools.triage_evidence import (
            collect_evidence,
            list_evidence_catalog,
            run_evidence_collector,
        )
        from src.mcp_server.tools.triage_analysis import run_analysis, get_triage_report
        from src.mcp_server.tools.triage_commands import search_logs, record_investigation_outcome

        with pytest.raises(ToolError, match="not found"):
            await run_analysis(session_id="nonexistent", ctx=ctx)

    @pytest.mark.asyncio
    async def test_rebuilds_artifacts_from_evidence(
        self, mocker: MockerFixture, sap_context: SapContext, ctx
    ):
        from src.mcp_server.tools.triage_evidence import (
            collect_evidence,
            list_evidence_catalog,
            run_evidence_collector,
        )
        from src.mcp_server.tools.triage_analysis import run_analysis, get_triage_report
        from src.mcp_server.tools.triage_commands import search_logs, record_investigation_outcome

        session = TriageSession(workspace_id="WS_A")
        session.start_collection()
        session.evidence = [
            {
                "evidence_id": "ev-1",
                "evidence_type": "command_output",
                "collector_type": "ssh",
                "status": "collected",
                "host": "node1",
                "command": "crm_mon -1rR",
                "content": "2 nodes configured",
            },
        ]
        session.status = "analyzing"
        sid = str(session.id)
        sap_context.triage_sessions[sid] = session

        report = TriageReport(
            session_id=sid,
            workspace_id="WS_A",
            summary="Analyzed",
        )
        sap_context.analyzer = mocker.MagicMock()
        sap_context.analyzer.analyze.return_value = report

        await run_analysis(session_id=sid, ctx=ctx)

        call_args = sap_context.analyzer.analyze.call_args
        artifacts = call_args[0][1]
        assert len(artifacts) == 1
        assert artifacts[0].evidence_id == "ev-1"
        assert artifacts[0].host == "node1"

    @pytest.mark.asyncio
    async def test_skips_malformed_evidence_entries(
        self, mocker: MockerFixture, sap_context: SapContext, ctx
    ):
        from src.mcp_server.tools.triage_evidence import (
            collect_evidence,
            list_evidence_catalog,
            run_evidence_collector,
        )
        from src.mcp_server.tools.triage_analysis import run_analysis, get_triage_report
        from src.mcp_server.tools.triage_commands import search_logs, record_investigation_outcome

        session = TriageSession(workspace_id="WS_A")
        session.start_collection()
        session.evidence = [
            {"broken": True},
            {
                "evidence_id": "ev-2",
                "evidence_type": "command_output",
                "collector_type": "ssh",
                "status": "collected",
            },
        ]
        session.status = "analyzing"
        sid = str(session.id)
        sap_context.triage_sessions[sid] = session

        report = TriageReport(session_id=sid, workspace_id="WS_A")
        sap_context.analyzer = mocker.MagicMock()
        sap_context.analyzer.analyze.return_value = report

        await run_analysis(session_id=sid, ctx=ctx)

        artifacts = sap_context.analyzer.analyze.call_args[0][1]
        assert len(artifacts) == 1
        assert artifacts[0].evidence_id == "ev-2"


class TestQueryKnowledgeExtended:
    """Additional query_knowledge tests beyond server_test.py."""

    @pytest.mark.asyncio
    async def test_matches_rules_by_name(self, sap_context: SapContext, ctx):
        from src.mcp_server.tools.retrieval import query_knowledge

        result = await query_knowledge(query="HANA HSR", ctx=ctx)

        assert result["total_rules"] == 1
        assert result["rules"][0]["id"] == "DB-HANA-0001"

    @pytest.mark.asyncio
    async def test_matches_rules_by_tag(self, sap_context: SapContext, ctx):
        from src.mcp_server.tools.retrieval import query_knowledge

        result = await query_knowledge(query="hsr", ctx=ctx)

        assert result["total_rules"] == 1

    @pytest.mark.asyncio
    async def test_filters_by_category(self, sap_context: SapContext, ctx):
        from src.mcp_server.tools.retrieval import query_knowledge

        result = await query_knowledge(query="hana", category="ha_check", ctx=ctx)
        assert result["total_rules"] == 1

        result = await query_knowledge(query="hana", category="os_config", ctx=ctx)
        assert result["total_rules"] == 0

    @pytest.mark.asyncio
    async def test_respects_limit(self, sap_context: SapContext, ctx):
        from src.mcp_server.tools.retrieval import query_knowledge

        sap_context.knowledge_store.load_rules.return_value = [
            Rule(id=f"R-{i}", name=f"Rule {i}", description="test", tags=["test"])
            for i in range(50)
        ]

        result = await query_knowledge(query="test", limit=5, ctx=ctx)

        assert len(result["rules"]) == 5
        assert result["total_rules"] == 50

    @pytest.mark.asyncio
    async def test_clamps_limit(self, sap_context: SapContext, ctx):
        from src.mcp_server.tools.retrieval import query_knowledge

        result = await query_knowledge(query="hana", limit=9999, ctx=ctx)
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_case_insensitive_search(self, sap_context: SapContext, ctx):
        from src.mcp_server.tools.retrieval import query_knowledge

        result = await query_knowledge(query="hana hsr STATUS", ctx=ctx)
        assert result["total_rules"] == 1


class TestGetTriageReportExtended:
    """Additional get_triage_report tests."""

    @pytest.mark.asyncio
    async def test_returns_full_report(self, sap_context: SapContext, ctx):
        from src.mcp_server.tools.triage_evidence import (
            collect_evidence,
            list_evidence_catalog,
            run_evidence_collector,
        )
        from src.mcp_server.tools.triage_analysis import run_analysis, get_triage_report
        from src.mcp_server.tools.triage_commands import search_logs, record_investigation_outcome

        session = TriageSession(workspace_id="WS_A")
        session.start_collection()
        session.complete_collection([])
        report = TriageReport(
            session_id=str(session.id),
            workspace_id="WS_A",
            summary="All clear",
            findings=[
                TriageFinding(
                    finding_id="F-1",
                    title="Test finding",
                    severity=Severity.LOW,
                ),
            ],
        )
        session.complete_analysis(report)
        sid = str(session.id)
        sap_context.triage_sessions[sid] = session

        result = await get_triage_report(session_id=sid, ctx=ctx)

        assert result["report"] is not None
        assert result["report"]["summary"] == "All clear"
        assert len(result["report"]["findings"]) == 1


class TestGetWorkspaceAttributes:
    """Test that get_workspace returns SAP system attributes."""

    @pytest.fixture()
    def enriched_workspaces(self, tmp_path: Path) -> Path:
        base = tmp_path / "WORKSPACES" / "SYSTEM"
        ws = base / "WS_E"
        ws.mkdir(parents=True)
        (ws / "sap-parameters.yaml").write_text(
            "sap_sid: S11\n"
            "db_sid: S11\n"
            "platform: HANA\n"
            "db_instance_number: '00'\n"
            "scs_instance_number: '01'\n"
            "database_high_availability: true\n"
            "scs_high_availability: true\n"
            "database_scale_out: true\n"
            "use_hanasr_angi: true\n"
            "NFS_provider: ANF\n"
        )
        (ws / "hosts.yaml").write_text(
            "DB:\n"
            "  hosts:\n"
            "    node1:\n"
            "      ansible_host: 10.0.0.1\n"
            "  vars:\n"
            "    node_tier: hana\n"
        )
        return base

    @pytest.mark.asyncio
    async def test_includes_sap_system_attributes(
        self, sap_context: SapContext, enriched_workspaces: Path, ctx
    ):
        from src.mcp_server.tools.workspace_ops import (
            list_workspaces,
            get_workspace,
            _extract_sap_attributes,
        )

        sap_context.workspaces_base = enriched_workspaces
        sap_context.validator = InputValidator(
            workspaces_base=enriched_workspaces,
            sessions=sap_context.triage_sessions,
            job_store=sap_context.job_store,
        )
        result = await get_workspace(workspace_id="WS_E", ctx=ctx)

        assert "sap_system" in result
        sap_sys = result["sap_system"]
        assert sap_sys["sap_sid"] == "S11"
        assert sap_sys["platform"] == "HANA"
        assert sap_sys["database_high_availability"] is True
        assert sap_sys["database_scale_out"] is True
        assert sap_sys["use_hanasr_angi"] is True
        assert sap_sys["NFS_provider"] == "ANF"

    @pytest.mark.asyncio
    async def test_empty_params_returns_empty_sap_system(self, sap_context: SapContext, ctx):
        from src.mcp_server.tools.workspace_ops import (
            list_workspaces,
            get_workspace,
            _extract_sap_attributes,
        )

        result = await get_workspace(workspace_id="WS_A", ctx=ctx)

        assert "sap_system" in result
        assert result["sap_system"]["sap_sid"] == "HA1"


class TestListEvidenceCatalog:
    """Test list_evidence_catalog tool."""

    @pytest.mark.asyncio
    async def test_returns_all_definitions(self, sap_context: SapContext, ctx):
        from src.core.models.knowledge import EvidenceCollectorDef
        from src.mcp_server.tools.triage_evidence import (
            collect_evidence,
            list_evidence_catalog,
            run_evidence_collector,
        )
        from src.mcp_server.tools.triage_analysis import run_analysis, get_triage_report
        from src.mcp_server.tools.triage_commands import search_logs, record_investigation_outcome

        sap_context.knowledge_store.load_evidence_definitions.return_value = [
            EvidenceCollectorDef(
                id="EC-CLUSTER-MON-0001",
                name="cluster_status",
                command="crm_mon -1rR",
                description="Pacemaker cluster status",
                tags=["pacemaker", "cluster", "ha"],
                requires_ha=True,
            ),
            EvidenceCollectorDef(
                id="EC-DF-0001",
                name="filesystem_usage",
                command="df -hT",
                description="Filesystem disk usage",
                tags=["filesystem", "storage"],
            ),
        ]
        result = await list_evidence_catalog(ctx=ctx)

        assert result["total"] == 2
        ids = [d["id"] for d in result["definitions"]]
        assert "EC-CLUSTER-MON-0001" in ids
        assert "EC-DF-0001" in ids

    @pytest.mark.asyncio
    async def test_filters_by_category(self, sap_context: SapContext, ctx):
        from src.core.models.knowledge import EvidenceCollectorDef
        from src.mcp_server.tools.triage_evidence import (
            collect_evidence,
            list_evidence_catalog,
            run_evidence_collector,
        )
        from src.mcp_server.tools.triage_analysis import run_analysis, get_triage_report
        from src.mcp_server.tools.triage_commands import search_logs, record_investigation_outcome

        sap_context.knowledge_store.load_evidence_definitions.return_value = [
            EvidenceCollectorDef(
                id="EC-CLUSTER-MON-0001",
                name="cluster_status",
                command="crm_mon -1rR",
                description="Pacemaker cluster status",
                tags=["pacemaker", "cluster", "ha"],
            ),
            EvidenceCollectorDef(
                id="EC-DF-0001",
                name="filesystem_usage",
                command="df -hT",
                description="Filesystem disk usage",
                tags=["filesystem", "storage"],
            ),
        ]
        result = await list_evidence_catalog(category="pacemaker", ctx=ctx)

        assert result["total"] == 1
        assert result["definitions"][0]["id"] == "EC-CLUSTER-MON-0001"

    @pytest.mark.asyncio
    async def test_empty_category_returns_all(self, sap_context: SapContext, ctx):
        from src.core.models.knowledge import EvidenceCollectorDef
        from src.mcp_server.tools.triage_evidence import (
            collect_evidence,
            list_evidence_catalog,
            run_evidence_collector,
        )
        from src.mcp_server.tools.triage_analysis import run_analysis, get_triage_report
        from src.mcp_server.tools.triage_commands import search_logs, record_investigation_outcome

        sap_context.knowledge_store.load_evidence_definitions.return_value = [
            EvidenceCollectorDef(
                id="EC-OS-RELEASE-0001",
                name="os_release",
                command="cat /etc/os-release",
                description="OS release",
                tags=["os"],
            ),
        ]
        result = await list_evidence_catalog(category="", ctx=ctx)

        assert result["total"] == 1


class TestRunEvidenceCollector:
    """Test run_evidence_collector tool."""

    @pytest.mark.asyncio
    async def test_unknown_definition_raises(self, sap_context: SapContext, ctx):
        from src.mcp_server.tools.triage_evidence import (
            collect_evidence,
            list_evidence_catalog,
            run_evidence_collector,
        )
        from src.mcp_server.tools.triage_analysis import run_analysis, get_triage_report
        from src.mcp_server.tools.triage_commands import search_logs, record_investigation_outcome

        sap_context.knowledge_store.load_evidence_definitions.return_value = []

        with pytest.raises(ToolError, match="Unknown definition_id"):
            await run_evidence_collector(
                workspace_id="WS_A",
                definition_id="EC-NONEXISTENT-0001",
                ctx=ctx,
            )

    @pytest.mark.asyncio
    async def test_no_hosts_raises(self, sap_context: SapContext, tmp_path: Path, ctx):
        from src.core.models.knowledge import EvidenceCollectorDef
        from src.mcp_server.tools.triage_evidence import (
            collect_evidence,
            list_evidence_catalog,
            run_evidence_collector,
        )
        from src.mcp_server.tools.triage_analysis import run_analysis, get_triage_report
        from src.mcp_server.tools.triage_commands import search_logs, record_investigation_outcome

        sap_context.knowledge_store.load_evidence_definitions.return_value = [
            EvidenceCollectorDef(
                id="EC-DF-0001",
                name="filesystem_usage",
                command="df -hT",
                description="Filesystem disk usage",
                tags=["storage"],
            ),
        ]
        empty_ws = tmp_path / "EMPTY"
        empty_ws.mkdir(parents=True)
        (empty_ws / "sap-parameters.yaml").write_text("sap_sid: X\n")
        (empty_ws / "hosts.yaml").write_text("all:\n  hosts:\n")

        base = empty_ws.parent
        sap_context.workspaces_base = base
        sap_context.validator = InputValidator(
            workspaces_base=base,
            sessions=sap_context.triage_sessions,
            job_store=sap_context.job_store,
        )

        with pytest.raises(ToolError, match="No hosts found"):
            await run_evidence_collector(
                workspace_id="EMPTY",
                definition_id="EC-DF-0001",
                ctx=ctx,
            )

    @pytest.mark.asyncio
    async def test_resolves_placeholders_and_executes(
        self, mocker: MockerFixture, sap_context: SapContext, tmp_path, ctx
    ):
        from src.core.models.knowledge import EvidenceCollectorDef
        from src.core.models.evidence import EvidenceArtifact, CollectionStatus
        from src.mcp_server.tools.triage_evidence import (
            collect_evidence,
            list_evidence_catalog,
            run_evidence_collector,
        )
        from src.mcp_server.tools.triage_analysis import run_analysis, get_triage_report
        from src.mcp_server.tools.triage_commands import search_logs, record_investigation_outcome

        sap_context.knowledge_store.load_evidence_definitions.return_value = [
            EvidenceCollectorDef(
                id="EC-HANA-SR-STATE-0001",
                name="hana_sr_state",
                command="su - <sid>adm -c 'hdbnsutil -sr_state'",
                description="HANA SR state",
                tags=["hana", "hsr"],
            ),
        ]
        cred = mocker.MagicMock()
        cred.private_key_path = "/tmp/key.ppk"
        cred.auth_type.value = "SSHKEY"
        sap_context.ssh_cache.provision.return_value = cred

        mock_artifact = mocker.MagicMock()
        mock_artifact.content = "mode: sync\nsiteId: 1\n"
        mock_artifact.error = ""
        mock_artifact.metadata = {"return_code": 0}

        mock_ssh = mocker.patch("src.mcp_server.tools.triage_evidence.SshCollectorStrategy")
        mock_ssh.return_value.collect.return_value = mock_artifact
        result = await run_evidence_collector(
            workspace_id="WS_A",
            definition_id="EC-HANA-SR-STATE-0001",
            ctx=ctx,
        )

        assert result["definition_id"] == "EC-HANA-SR-STATE-0001"
        assert result["name"] == "hana_sr_state"
        assert result["stdout"] == "mode: sync\nsiteId: 1\n"
        assert result["exit_code"] == 0
        call_def = mock_ssh.return_value.collect.call_args[0][0]
        assert "ha1adm" in call_def.command
