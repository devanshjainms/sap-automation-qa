# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for MCP resource handlers (resources.py).

Each resource is invoked directly with a mock ``Context`` — same
pattern as the tool tests in ``server_test.py``.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.core.models.knowledge import Playbook, Rule
from src.mcp_server.server import SapContext


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_workspaces(tmp_path: Path) -> Path:
    """Workspace tree with sap-parameters.yaml and hosts.yaml."""
    base = tmp_path / "WORKSPACES" / "SYSTEM"

    ws = base / "WS_A"
    ws.mkdir(parents=True)
    (ws / "sap-parameters.yaml").write_text(
        "sap_sid: HA1\ndatabase_high_availability: true\n"
    )
    (ws / "hosts.yaml").write_text(
        "all:\n  hosts:\n    node1:\n    node2:\n"
    )

    return base


@pytest.fixture()
def mock_knowledge_store() -> MagicMock:
    store = MagicMock()
    store.load_rules.return_value = [
        Rule(
            id="DB-HANA-0001",
            name="HANA HSR status",
            description="Check HANA system replication is healthy",
            category="ha_check",
            severity="CRITICAL",
            tags=["hana", "hsr"],
        ),
        Rule(
            id="DB-HANA-0002",
            name="CIB stonith enabled",
            description="Validate STONITH is enabled",
            category="ha_check",
            severity="HIGH",
            tags=["fencing"],
        ),
    ]
    store.load_playbooks.return_value = [
        Playbook(
            id="PB-HANA-HSR-0001",
            name="HSR Failover Recovery",
            description="Steps to recover after HSR failover",
            category="ha_failure",
            symptoms=["secondary not replicating", "SOK != SOK"],
        ),
    ]
    return store


def _make_ctx(sap: SapContext) -> MagicMock:
    ctx = MagicMock()
    ctx.request_context.lifespan_context = sap
    return ctx


def _sap(
    tmp_workspaces: Path,
    knowledge_store: MagicMock,
) -> SapContext:
    """Minimal SapContext with only the fields resources need."""
    return SapContext(
        job_store=MagicMock(),
        knowledge_store=knowledge_store,
        schedule_store=MagicMock(),
        scheduler_service=None,
        analyzer=MagicMock(),
        triage_executor=MagicMock(),
        triage_sessions={},
        workspaces_base=tmp_workspaces,
        core_api_url="http://localhost:8000",
        ssh_provider=MagicMock(),
        validator=MagicMock(),
        formatter=MagicMock(),
        retriever=MagicMock(),
        learning_pipeline=MagicMock(),
    )


# ---------------------------------------------------------------------------
# workspace://{workspace_id}/config
# ---------------------------------------------------------------------------


class TestGetWorkspaceConfig:
    """Test the workspace config resource."""

    def test_returns_parsed_yaml_as_json(
        self, tmp_workspaces: Path, mock_knowledge_store: MagicMock
    ):
        from src.mcp_server.resources import get_workspace_config

        sap = _sap(tmp_workspaces, mock_knowledge_store)
        ctx = _make_ctx(sap)

        result = get_workspace_config(workspace_id="WS_A", ctx=ctx)
        data = json.loads(result)

        assert data["sap_sid"] == "HA1"
        assert data["database_high_availability"] is True

    def test_missing_workspace_returns_error(
        self, tmp_workspaces: Path, mock_knowledge_store: MagicMock
    ):
        from src.mcp_server.resources import get_workspace_config

        sap = _sap(tmp_workspaces, mock_knowledge_store)
        ctx = _make_ctx(sap)

        result = get_workspace_config(workspace_id="NOPE", ctx=ctx)
        data = json.loads(result)

        assert "error" in data
        assert "NOPE" in data["error"]

    def test_invalid_yaml_returns_raw_text(
        self, tmp_workspaces: Path, mock_knowledge_store: MagicMock
    ):
        from src.mcp_server.resources import get_workspace_config

        bad_file = tmp_workspaces / "WS_A" / "sap-parameters.yaml"
        bad_file.write_text(":\n  - [invalid yaml\n")

        sap = _sap(tmp_workspaces, mock_knowledge_store)
        ctx = _make_ctx(sap)

        result = get_workspace_config(workspace_id="WS_A", ctx=ctx)
        # Should fall back to raw text, not raise.
        assert "invalid yaml" in result


# ---------------------------------------------------------------------------
# workspace://{workspace_id}/hosts
# ---------------------------------------------------------------------------


class TestGetWorkspaceHosts:
    """Test the workspace hosts resource."""

    def test_returns_parsed_hosts(
        self, tmp_workspaces: Path, mock_knowledge_store: MagicMock
    ):
        from src.mcp_server.resources import get_workspace_hosts

        sap = _sap(tmp_workspaces, mock_knowledge_store)
        ctx = _make_ctx(sap)

        result = get_workspace_hosts(workspace_id="WS_A", ctx=ctx)
        data = json.loads(result)

        assert "all" in data
        assert "node1" in data["all"]["hosts"]

    def test_missing_hosts_file(
        self, tmp_workspaces: Path, mock_knowledge_store: MagicMock
    ):
        from src.mcp_server.resources import get_workspace_hosts

        sap = _sap(tmp_workspaces, mock_knowledge_store)
        ctx = _make_ctx(sap)

        result = get_workspace_hosts(workspace_id="NOPE", ctx=ctx)
        data = json.loads(result)

        assert "error" in data

    def test_invalid_yaml_returns_raw_text(
        self, tmp_workspaces: Path, mock_knowledge_store: MagicMock
    ):
        from src.mcp_server.resources import get_workspace_hosts

        bad = tmp_workspaces / "WS_A" / "hosts.yaml"
        bad.write_text(":\n  - [invalid\n")

        sap = _sap(tmp_workspaces, mock_knowledge_store)
        ctx = _make_ctx(sap)

        result = get_workspace_hosts(workspace_id="WS_A", ctx=ctx)
        assert "invalid" in result


# ---------------------------------------------------------------------------
# knowledge://rules
# ---------------------------------------------------------------------------


class TestGetKnowledgeRules:
    """Test the knowledge rules resource."""

    def test_returns_all_rules(
        self, tmp_workspaces: Path, mock_knowledge_store: MagicMock
    ):
        from src.mcp_server.resources import get_knowledge_rules

        sap = _sap(tmp_workspaces, mock_knowledge_store)
        ctx = _make_ctx(sap)

        result = get_knowledge_rules(ctx=ctx)
        data = json.loads(result)

        assert len(data) == 2
        assert data[0]["id"] == "DB-HANA-0001"
        assert data[0]["severity"] == "CRITICAL"
        assert data[0]["tags"] == ["hana", "hsr"]
        assert data[1]["id"] == "DB-HANA-0002"

    def test_empty_knowledge_base(
        self, tmp_workspaces: Path
    ):
        from src.mcp_server.resources import get_knowledge_rules

        store = MagicMock()
        store.load_rules.return_value = []

        sap = _sap(tmp_workspaces, store)
        ctx = _make_ctx(sap)

        result = get_knowledge_rules(ctx=ctx)
        assert json.loads(result) == []


# ---------------------------------------------------------------------------
# knowledge://playbooks
# ---------------------------------------------------------------------------


class TestGetKnowledgePlaybooks:
    """Test the knowledge playbooks resource."""

    def test_returns_all_playbooks(
        self, tmp_workspaces: Path, mock_knowledge_store: MagicMock
    ):
        from src.mcp_server.resources import get_knowledge_playbooks

        sap = _sap(tmp_workspaces, mock_knowledge_store)
        ctx = _make_ctx(sap)

        result = get_knowledge_playbooks(ctx=ctx)
        data = json.loads(result)

        assert len(data) == 1
        assert data[0]["id"] == "PB-HANA-HSR-0001"
        assert "secondary not replicating" in data[0]["symptoms"]

    def test_empty_playbooks(self, tmp_workspaces: Path):
        from src.mcp_server.resources import get_knowledge_playbooks

        store = MagicMock()
        store.load_playbooks.return_value = []

        sap = _sap(tmp_workspaces, store)
        ctx = _make_ctx(sap)

        result = get_knowledge_playbooks(ctx=ctx)
        assert json.loads(result) == []
